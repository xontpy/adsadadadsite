import asyncio
import os
import random
import sys
import threading
import time
import traceback
from curl_cffi import requests, AsyncSession

# This function is required by the web server to send logs and status updates to the UI.
def bot_logger(status_updater, message):
    """A simple logger that sends messages to the web UI."""
    try:
        if isinstance(message, dict):
            status_updater.put(message)
        else:
            log_message = str(message)
            # Avoid logging sensitive details
            if "proxy" not in log_message and "token" not in log_message:
                status_updater.put({'log_line': log_message})
    except Exception:
        # Fallback to console if UI logging fails
        sys.stdout.write(f"\r[UI_LOG_FAIL] {message}")
        sys.stdout.flush()

# --- Core Logic adapted from main(2).py ---
# The following functions are taken directly from main(2).py and adapted to use the
# web UI logger and to handle errors gracefully without exiting the entire application.

def load_proxies(logger):
    """Loads proxies from 'proxies.txt'."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "proxies.txt")
    try:
        with open(file_path, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
        if not proxies:
            logger(f"Error: '{file_path}' is empty. Please add proxies.")
            return None
        logger(f"Loaded {len(proxies)} proxies.")
        return proxies
    except FileNotFoundError:
        logger(f"Error: Proxies file not found: {file_path}.")
        return None
    except Exception as e:
        logger(f"An error occurred during proxy loading: {e}")
        return None

def pick_proxy(logger, proxies_list):
    """Picks a random proxy and formats it."""
    if not proxies_list:
        logger("Cannot pick proxy, the proxy list is empty.")
        return None, None
    proxy = random.choice(proxies_list)
    try:
        ip, port, user, pwd = proxy.split(":")
        full_url = f"http://{user}:{pwd}@{ip}:{port}"
        proxy_dict = {"http": full_url, "https": full_url}
        return proxy_dict, full_url
    except ValueError:
        logger(f"Bad proxy format: {proxy}, (use ip:port:user:pass)")
        return None, None
    except Exception as e:
        logger(f"Proxy error: {proxy}, {e}")
        return None, None

def get_channel_id(logger, channel_name, proxies_list):
    """Gets the channel ID using a synchronous request."""
    max_attempts = 5
    for _ in range(max_attempts):
        proxy_dict, _ = pick_proxy(logger, proxies_list)
        if not proxy_dict:
            continue
        try:
            # Using firefox135 impersonation for better compatibility
            with requests.Session(impersonate="firefox135", proxies=proxy_dict, timeout=10) as s:
                r = s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                if r.status_code == 200:
                    logger(f"Successfully found channel ID for {channel_name}.")
                    return r.json().get("id")
                else:
                    pass
        except Exception as e:
            pass
        time.sleep(1)
    logger("Failed to get channel ID after multiple attempts.")
    return None

def get_token(logger, proxies_list):
    """Gets a viewer token using a synchronous request."""
    max_attempts = 5
    for _ in range(max_attempts):
        proxy_dict, proxy_url = pick_proxy(logger, proxies_list)
        if not proxy_dict:
            continue
        try:
            with requests.Session(impersonate="firefox135", proxies=proxy_dict, timeout=15) as s:
                s.get("https://kick.com")
                r = s.get('https://websockets.kick.com/viewer/v1/token')
                if r.status_code == 200:
                    token = r.json()["data"]["token"]
                    return token, proxy_url
                else:
                    logger(f"Token request failed with status {r.status_code}, retrying...")
        except Exception as e:
            pass  # logger(f"Token (Error: {e}), retrying...")
        time.sleep(1)
    return None, None

def start_connection_thread(logger, channel_id, index, stop_event, proxies_list, connected_viewers, total_viewers):
    """
    This is the core connection logic from main(2).py, running in a loop for a single thread.
    It has been adapted to:
    - Use the `stop_event` to allow graceful shutdown from the UI.
    - Update the `connected_viewers` set for accurate UI reporting.
    """
    async def connection_handler():
        while not stop_event.is_set():
            token, proxy_url = get_token(logger, proxies_list)
            if not token:
                await asyncio.sleep(5)
                continue

            try:
                # Using AsyncSession for the WebSocket connection as in the original script
                async with AsyncSession(impersonate="firefox135") as s:
                    ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"
                    ws = await s.ws_connect(ws_url, proxy=proxy_url)
                    
                    # --- Viewer Connected ---
                    logger(f"Viewer {index} connected successfully")
                    connected_viewers.add(index)
                    
                    counter = 0
                    while not stop_event.is_set():
                        counter += 1
                        payload = {"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}} if counter % 2 == 0 else {"type": "ping"}
                        await ws.send_json(payload)
                        # Delay between pings/handshakes
                        await asyncio.sleep(11 + random.randint(2, 7))

            except Exception as e:
                logger(f"Connection failed for viewer {index}: {type(e).__name__}")
            finally:
                # --- Viewer Disconnected ---
                connected_viewers.discard(index)

            # Wait before retrying connection if the bot is still running
            if not stop_event.is_set():
                await asyncio.sleep(random.randint(5, 10))

    try:
        # Each thread runs its own asyncio event loop, as in the original script
        asyncio.run(connection_handler())
    except Exception as e:
        logger(f"Critical error in thread {index}: {e}\n{traceback.format_exc()}")

# This is the main entry point called by the web server.
def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes):
    """
    This function orchestrates the bot based on the logic from main(2).py's `if __name__ == "__main__"` block.
    """
    logger = lambda msg: bot_logger(status_updater, msg)
    
    try:
        logger("Initializing bot with logic from main(2).py...")
        
        proxies = load_proxies(logger)
        if not proxies:
            logger("Halting: No proxies loaded.")
            return

        channel_id = get_channel_id(logger, channel, proxies)
        if not channel_id:
            logger("Halting: Failed to get channel ID.")
            return

        # This set is necessary to track active viewers for the UI.
        connected_viewers = set()
        threads = []

        logger(f"Sending {viewers} views to {channel}")
        # Start viewer threads in batches to avoid detection
        batch_size = 10
        for i in range(0, viewers, batch_size):
            if stop_event.is_set():
                break
            for j in range(min(batch_size, viewers - i)):
                idx = i + j + 1
                t = threading.Thread(
                    target=start_connection_thread,
                    args=(logger, channel_id, idx, stop_event, proxies, connected_viewers, viewers)
                )
                threads.append(t)
                t.start()
            time.sleep(5)  # Delay between batches

        # --- Monitoring Loop ---
        # This part is an adaptation for the web UI. It checks the timer and stop request,
        # which is not part of the original command-line script.
        start_time = time.time()
        duration_seconds = duration_minutes * 60 if duration_minutes > 0 else float('inf')
        end_time = start_time + duration_seconds

        while time.time() < end_time and not stop_event.is_set():
            # Update the UI with the latest status
            status_update = {
                "current_viewers": len(connected_viewers),
                "target_viewers": viewers,
                "is_running": True
            }
            logger(status_update)
            time.sleep(15)  # Less frequent updates to reduce load

    except Exception as e:
        detailed_error = traceback.format_exc()
        logger(f"A critical error occurred in the main bot loop: {e}\nDetails:\n{detailed_error}")
    finally:
        # --- Shutdown Logic ---
        shutdown_reason = "an unknown error occurred"
        if stop_event.is_set():
            shutdown_reason = "stop request received"
        elif duration_seconds > 0 and time.time() >= end_time:
            shutdown_reason = "timer finished"

        logger(f"Shutting down ({shutdown_reason}). Stopping all viewer threads...")
        
        if not stop_event.is_set():
            stop_event.set()
        
        # Wait for all threads to finish
        for t in threads:
            t.join(timeout=3) # Give threads 3 seconds to exit cleanly
            
        logger("Bot process has stopped.")
        logger({"is_running": False, "current_viewers": 0})
