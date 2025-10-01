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
            # Avoid logging proxy details for security
            log_message = str(message)
            if "proxy" not in log_message and "token" not in log_message:
                status_updater.put({'log_line': log_message})
    except Exception:
        sys.stdout.write(f"\r[UI_LOG_FAIL] {message}")
        sys.stdout.flush()

# --- Logic from main (2).py, adapted for Web UI ---

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
    for i in range(max_attempts):
        proxy_dict, _ = pick_proxy(logger, proxies_list)
        if not proxy_dict:
            continue
        try:
            with requests.Session(impersonate="firefox135", proxies=proxy_dict, timeout=10) as s:
                r = s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                if r.status_code == 200:
                    logger(f"Successfully found channel ID for {channel_name}.")
                    return r.json().get("id")
                else:
                    logger(f"Channel ID (Status: {r.status_code}), retrying...")
        except Exception as e:
            logger(f"Channel ID (Error: {e}), retrying...")
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
                s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                r = s.get('https://websockets.kick.com/viewer/v1/token')
                if r.status_code == 200:
                    token = r.json()["data"]["token"]
                    return token, proxy_url
                else:
                    logger(f"Token (Status: {r.status_code}), retrying...")
        except Exception as e:
            logger(f"Token (Error: {e}), retrying...")
        time.sleep(1)
    return None, None

def start_connection_thread(logger, channel_id, index, stop_event, connected_viewers, proxies_list, total_viewers):
    """The main logic for a single viewer thread."""
    
    async def connection_handler():
        while not stop_event.is_set():
            token, proxy_url = get_token(logger, proxies_list)
            if not token:
                logger(f"Viewer {index}: Failed to get token, retrying in 3s...")
                await asyncio.sleep(3)
                continue

            try:
                async with AsyncSession(proxy=proxy_url, timeout=20) as s:
                    ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"
                    ws = await s.ws_connect(ws_url, timeout=15)
                    connected_viewers.add(index)
                    logger(f"Viewer {index} connected.")
                    logger({"current_viewers": len(connected_viewers), "target_viewers": total_viewers, "is_running": True})
                    
                    counter = 0
                    while not stop_event.is_set():
                        counter += 1
                        if counter % 2 == 0:
                            await ws.send_json({"type": "ping"})
                        else:
                            await ws.send_json({"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}})
                        
                        delay = 11 + random.randint(2, 7)
                        await asyncio.sleep(delay)

            except Exception as e:
                logger(f"Viewer {index} error: {e}. Retrying...")
                await asyncio.sleep(random.randint(4, 8))
            finally:
                connected_viewers.discard(index)
                if not stop_event.is_set():
                     logger(f"Viewer {index} disconnected.")
                logger({"current_viewers": len(connected_viewers), "target_viewers": total_viewers, "is_running": not stop_event.is_set()})

    try:
        asyncio.run(connection_handler())
    except Exception as e:
        logger(f"Critical error in thread {index}: {e}\n{traceback.format_exc()}")

def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes, ramp_up_time):
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
        threads = []
        thread_counter = 0

        # --- Ramp-up Calculation ---
        # We'll divide the ramp-up into a fixed number of batches for smooth delivery.
        NUM_BATCHES = 20 
        
        if ramp_up_time > 0 and viewers > 0:
            # Calculate batch size and delay, ensuring batch_size is at least 1.
            batch_size = max(1, viewers // NUM_BATCHES)
            # Calculate delay, but handle case where ramp_up_time is small
            try:
                # Calculate the number of batches that will actually run
                num_actual_batches = (viewers + batch_size - 1) // batch_size
                delay_between_batches = ramp_up_time / num_actual_batches if num_actual_batches > 1 else 0
            except ZeroDivisionError:
                delay_between_batches = 0
        else:
            # If ramp-up is 0, send all at once.
            batch_size = viewers if viewers > 0 else 1
            delay_between_batches = 0

        logger(f"Ramp-up: {batch_size} viewers per batch with a {delay_between_batches:.2f}s delay.")

        # --- Main monitoring and management loop ---
        duration_seconds = duration_minutes * 60
        end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')

        while time.time() < end_time and not stop_event.is_set():
            # Clean up dead threads from the list
            threads = [t for t in threads if t.is_alive()]

            # Calculate how many new threads are needed for the next batch
            num_to_spawn = viewers - len(threads)

            if num_to_spawn > 0:
                # Determine the size of this specific batch
                current_batch_size = min(batch_size, num_to_spawn)
                logger(f"Spawning a batch of {current_batch_size} viewers...")

                for _ in range(current_batch_size):
                    if stop_event.is_set():
                        break
                    thread_counter += 1
                    t = threading.Thread(
                        target=start_connection_thread,
                        args=(logger, channel_id, thread_counter, stop_event, connected_viewers, proxies, viewers)
                    )
                    threads.append(t)
                    t.start()
            
            status_update = {
                "current_viewers": len(connected_viewers),
                "target_viewers": viewers,
                "is_running": not stop_event.is_set()
            }
            logger(status_update)
            
            # Determine sleep time. Use the calculated delay during ramp-up, otherwise a standard poll interval.
            if num_to_spawn > batch_size: # Still in the ramp-up phase
                 sleep_duration = delay_between_batches if delay_between_batches > 0 else 1
            else: # Ramp-up complete or not applicable
                sleep_duration = 5 # Standard polling interval

            time.sleep(sleep_duration)

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
