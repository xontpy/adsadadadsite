import asyncio
import os
import random
import re
import sys
import threading
import time
import traceback
import tls_client
import websockets
import json
from threading import Semaphore

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

CLIENT_TOKEN = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"

# --- Core Logic adapted from kick.py ---
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
            logger(f"Warning: '{file_path}' is empty. Proceeding without proxies - connections may fail or get banned.")
            return []
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

def get_channel_id(logger, channel_name=None):
    """Gets the channel ID using tls_client (from kick.py)."""
    try:
        s = tls_client.Session(client_identifier="chrome_120", random_tls_extension_order=True)
        s.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://kick.com/',
            'Origin': 'https://kick.com',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })

        try:
            response = s.get(f'https://kick.com/api/v2/channels/{channel_name}')
            if response.status_code == 200:
                data = response.json()
                channel_id = data.get("id")
                return channel_id
        except Exception as e:
            pass

        try:
            response = s.get(f'https://kick.com/api/v1/channels/{channel_name}')
            if response.status_code == 200:
                data = response.json()
                channel_id = data.get("id")
                return channel_id
        except Exception as e:
            pass

        try:
            response = s.get(f'https://kick.com/{channel_name}')
            if response.status_code == 200:
                patterns = [
                    r'"id":(\d+).*?"slug":"' + re.escape(channel_name) + r'"',
                    r'"channel_id":(\d+)',
                    r'channelId["\']:\s*(\d+)',
                    r'channel.*?id["\']:\s*(\d+)'
                ]

                for pattern in patterns:
                    match = re.search(pattern, response.text, re.IGNORECASE)
                    if match:
                        channel_id = int(match.group(1))
                        return channel_id
        except Exception as e:
            pass

        logger(f"All methods failed to get channel ID for: {channel_name}")
        return None

    except Exception as e:
        logger(f"Error getting channel ID: {e}")
        return None

def get_token(logger):
    """Gets a viewer token using tls_client (from kick.py)."""
    try:
        s = tls_client.Session(client_identifier="chrome_120", random_tls_extension_order=True)
        s.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })

        try:
            session_resp = s.get("https://kick.com")
            s.headers["X-CLIENT-TOKEN"] = CLIENT_TOKEN
            response = s.get('https://websockets.kick.com/viewer/v1/token')

            if response.status_code == 200:
                data = response.json()
                token = data.get("data", {}).get("token")
                if token:
                    return token
        except Exception as e:
            pass

        token_endpoints = [
            'https://websockets.kick.com/viewer/v1/token',
            'https://kick.com/api/websocket/token',
            'https://kick.com/api/v1/websocket/token'
        ]

        for endpoint in token_endpoints:
            try:
                s.headers["X-CLIENT-TOKEN"] = CLIENT_TOKEN
                response = s.get(endpoint, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    token = data.get("data", {}).get("token") or data.get("token")
                    if token:
                        return token
            except Exception as e:
                continue

        logger("Failed to get WebSocket token from all endpoints")
        return None

    except Exception as e:
        logger(f"Error getting WebSocket token: {e}")
        return None

def start_connection_thread(logger, channel_id, index, stop_event, connected_viewers, total_viewers, thread_semaphore):
    """
    This is the core connection logic adapted from kick.py, using websockets.
    It has been adapted to:
    - Use the `stop_event` to allow graceful shutdown from the UI.
    - Update the `connected_viewers` set for accurate UI reporting.
    - Use semaphore to limit concurrent connections.
    """
    try:
        thread_semaphore.acquire()
        try:
            token = get_token(logger)
            if not token:
                return

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_websocket_worker(token, logger, channel_id, index, stop_event, connected_viewers, total_viewers))
            except Exception as e:
                pass
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        except Exception as e:
            pass
        finally:
            thread_semaphore.release()

    except Exception as e:
        logger(f"Critical error in thread {index}: {e}")

async def _websocket_worker(token, logger, channel_id, index, stop_event, connected_viewers, total_viewers):
    connection_opened = False
    try:
        ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"

        async with websockets.connect(ws_url) as websocket:
            connected_viewers.add(index)
            connection_opened = True
            logger(f"Viewer {index} connected successfully")
            # Update status immediately
            logger({"current_viewers": len(connected_viewers), "target_viewers": total_viewers})

            handshake_msg = {
                "type": "channel_handshake",
                "data": {
                    "message": {"channelId": channel_id}
                }
            }
            await websocket.send(json.dumps(handshake_msg))

            ping_count = 0
            while not stop_event.is_set() and ping_count < 10:
                ping_count += 1

                ping_msg = {"type": "ping"}
                await websocket.send(json.dumps(ping_msg))

                sleep_time = 12 + random.randint(1, 5)
                await asyncio.sleep(sleep_time)

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        logger(f"Connection failed for viewer {index}: {type(e).__name__}")
    finally:
        if connection_opened:
            connected_viewers.discard(index)
            logger({"current_viewers": len(connected_viewers), "target_viewers": total_viewers})

# This is the main entry point called by the web server.
def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes, rapid=False):
    """
    This function orchestrates the bot based on the logic from main(2).py's `if __name__ == "__main__"` block.
    """
    logger = lambda msg: bot_logger(status_updater, msg)

    # Initialize timing variables before try block to avoid UnboundLocalError in finally
    start_time = time.time()
    duration_seconds = duration_minutes * 60 if duration_minutes > 0 else float('inf')
    end_time = start_time + duration_seconds

    try:
        logger("Initializing bot with logic from kick.py...")

        channel_id = get_channel_id(logger, channel)
        if not channel_id:
            logger("Halting: Failed to get channel ID.")
            return

        # This set is necessary to track active viewers for the UI.
        connected_viewers = set()
        thread_semaphore = Semaphore(viewers)
        threads = []

        logger(f"Sending {viewers} views to {channel}")
        # Start viewer threads all at once (no batches)
        for idx in range(1, viewers + 1):
            if stop_event.is_set():
                break
            t = threading.Thread(
                target=start_connection_thread,
                args=(logger, channel_id, idx, stop_event, connected_viewers, viewers, thread_semaphore)
            )
            threads.append(t)
            t.start()

        # --- Monitoring Loop ---
        # This part is an adaptation for the web UI. It checks the stop request,
        # running indefinitely until stopped (no timer like original script).

        while not stop_event.is_set():
            try:
                if duration_minutes > 0 and time.time() >= end_time:
                    stop_event.set()
                    break
                try:
                    # Update the UI with the latest status
                    status_update = {
                        "current_viewers": len(connected_viewers),
                        "target_viewers": viewers,
                        "is_running": True
                    }
                    logger(status_update)
                except Exception as e:
                    logger(f"Error updating status: {e}")
                try:
                    time.sleep(30)  # Less frequent updates to reduce load
                except Exception:
                    break
            except Exception as e:
                logger(f"Unexpected error in monitoring loop: {e}. Continuing...")
                time.sleep(5)  # Brief pause before retrying

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
        logger({"is_running": False, "current_viewers": len(connected_viewers)})
