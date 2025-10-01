import asyncio
import os
import random
import sys
import threading
import time
import traceback
from curl_cffi import requests, AsyncSession

# --- Logger ---
def bot_logger(status_updater, message):
    """A simple logger that sends messages to the web UI."""
    try:
        if isinstance(message, dict):
            status_updater.put(message)
        else:
            if "Using proxy" not in str(message):
                status_updater.put({'log_line': str(message)})
    except Exception:
        sys.stdout.write(f"\r[UI_LOG_FAIL] {message}")
        sys.stdout.flush()

# --- Adapted Logic from main (2).py ---

def load_proxies(logger):
    """Loads proxies from 'proxies.txt'."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "proxies.txt")
    try:
        with open(file_path, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
        if not proxies:
            logger(f"Error: '{file_path}' is empty.")
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
    proxy = random.choice(proxies_list)
    try:
        # Assuming proxy format is ip:port:user:pass
        ip, port, user, pwd = proxy.split(":")
        full_url = f"http://{user}:{pwd}@{ip}:{port}"
        proxy_dict = {"http": full_url, "https": full_url}
        return proxy_dict, full_url
    except ValueError:
        logger(f"Warning: Bad proxy format: {proxy}. Assuming user:pass@ip:port or ip:port.")
        # Fallback for other formats
        if "@" in proxy:
            return {"http": f"http://{proxy}", "https": f"http://{proxy}"}, f"http://{proxy}"
        else:
             return {"http": f"http://{proxy}", "https": f"http://{proxy}"}, f"http://{proxy}"
    except Exception as e:
        logger(f"Proxy error: {proxy}, {e}")
        return None, None

def get_channel_id(logger, channel_name, proxies_list):
    """Gets the channel ID using a synchronous request."""
    max_attempts = 5
    for i in range(max_attempts):
        proxy_dict, _ = pick_proxy(logger, proxies_list)
        if not proxy_dict:
            continue
        try:
            with requests.Session(impersonate="firefox110", proxies=proxy_dict, timeout=10) as s:
                r = s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                if r.status_code == 200:
                    logger(f"Successfully found channel ID for {channel_name}.")
                    return r.json().get("id")
                else:
                    logger(f"Attempt {i+1}: Failed to get channel ID (Status: {r.status_code}). Retrying...")
        except Exception as e:
            logger(f"Attempt {i+1}: Failed to get channel ID (Error: {e}). Retrying...")
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
            with requests.Session(impersonate="firefox110", proxies=proxy_dict, timeout=15) as s:
                s.get("https://kick.com")
                s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                r = s.get('https://websockets.kick.com/viewer/v1/token')
                if r.status_code == 200:
                    token = r.json()["data"]["token"]
                    return token, proxy_url
                else:
                    logger(f"Token Error: Status {r.status_code}. Retrying...")
        except Exception as e:
            logger(f"Token Error: {e}. Retrying...")
        time.sleep(1)
    return None, None

def start_connection_thread(logger, channel_id, index, stop_event, connected_viewers_counter, proxies_list):
    """The main logic for a single viewer thread."""
    
    async def connection_handler():
        while not stop_event.is_set():
            token, proxy_url = get_token(logger, proxies_list)
            if not token:
                logger(f"Viewer {index}: Failed to get token, retrying in 3s...")
                await asyncio.sleep(3)
                continue

            try:
                async with AsyncSession(impersonate="firefox110", proxy=proxy_url, timeout=20) as s:
                    ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"
                    async with s.ws_connect(ws_url, timeout=15) as ws:
                        connected_viewers_counter.add(index)
                        logger(f"Viewer {index} connected.")
                        
                        # Handshake and Ping loop
                        while not stop_event.is_set():
                            await ws.send_json({"type": "ping"})
                            await asyncio.sleep(12)
                            if stop_event.is_set(): break
                            await ws.send_json({"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}})
                            await asyncio.sleep(12)

            except Exception as e:
                logger(f"Viewer {index} error: {type(e).__name__}. Retrying...")
                await asyncio.sleep(random.randint(3, 7))
            finally:
                connected_viewers_counter.discard(index)
                if not stop_event.is_set():
                     logger(f"Viewer {index} disconnected.")

    try:
        asyncio.run(connection_handler())
    except Exception as e:
        logger(f"Critical error in thread {index}: {e}")


def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes):
    """The main function to run the bot, adapted for the website."""
    logger = lambda msg: bot_logger(status_updater, msg)
    
    try:
        logger("Starting bot logic...")
        
        proxies = load_proxies(logger)
        if not proxies:
            logger("Halting: No proxies loaded.")
            return

        channel_id = get_channel_id(logger, channel, proxies)
        if not channel_id:
            logger("Halting: Failed to get channel ID.")
            return

        start_time = time.time()
        connected_viewers = set()

        logger(f"Spawning {viewers} viewer threads...")
        threads = []
        for i in range(viewers):
            if stop_event.is_set():
                break
            t = threading.Thread(target=start_connection_thread, args=(logger, channel_id, i + 1, stop_event, connected_viewers, proxies))
            threads.append(t)
            t.start()
            time.sleep(0.1)

        logger(f"{len(threads)} threads spawned.")

        # --- Main monitoring loop ---
        duration_seconds = duration_minutes * 60
        end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
        while time.time() < end_time and not stop_event.is_set():
            status_update = {
                "current_viewers": len(connected_viewers),
                "target_viewers": viewers,
                "is_running": not stop_event.is_set()
            }
            logger(status_update)
            time.sleep(1)

    except Exception as e:
        detailed_error = traceback.format_exc()
        logger(f"An unexpected error occurred in the bot's core loop: {e}\nDetails:\n{detailed_error}")
    finally:
        if not stop_event.is_set():
            logger("Timer finished or stop requested. Stopping viewers...")
            stop_event.set()
        
        for t in threads:
            t.join(timeout=5)
            
        logger("Bot process has stopped.")
