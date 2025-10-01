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
            with requests.Session(impersonate="chrome120", proxies=proxy_dict, timeout=10) as s:
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

def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes):
    """The main function to run the bot, rewritten for asyncio."""
    logger = lambda msg: bot_logger(status_updater, msg)

    try:
        logger("Initializing bot...")
        
        proxies = load_proxies(logger)
        if not proxies:
            logger("Halting: No proxies loaded.")
            return

        channel_id = get_channel_id(logger, channel, proxies)
        if not channel_id:
            logger("Halting: Failed to get channel ID.")
            return

        # --- Main Async Logic ---
        asyncio.run(main_async_runner(logger, stop_event, channel_id, viewers, duration_minutes, proxies))

    except Exception as e:
        detailed_error = traceback.format_exc()
        logger(f"A critical error occurred: {e}\nDetails:\n{detailed_error}")
    finally:
        logger("Bot process has stopped.")


async def main_async_runner(logger, stop_event, channel_id, viewers, duration_minutes, proxies):
    """Orchestrates the entire async bot operation."""
    
    async def get_token_async(proxies_list):
        """Gets a viewer token asynchronously."""
        max_attempts = 5
        for _ in range(max_attempts):
            proxy_dict, proxy_url = pick_proxy(logger, proxies_list)
            if not proxy_dict: continue
            try:
                async with AsyncSession(impersonate="chrome120", proxies=proxy_dict, timeout=15) as s:
                    await s.get("https://kick.com")
                    s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                    r = await s.get('https://websockets.kick.com/viewer/v1/token')
                    if r.status_code == 200:
                        return r.json()["data"]["token"], proxy_url
                    logger(f"Token (Status: {r.status_code}), retrying...")
            except Exception as e:
                logger(f"Token (Error: {e}), retrying...")
            await asyncio.sleep(1)
        return None, None

    async def connection_handler(index, connected_viewers_set, sem):
        """Handles a single viewer connection asynchronously."""
        while not stop_event.is_set():
            was_connected = False
            await sem.acquire()
            try:
                token, proxy_url = await get_token_async(proxies)
                if not token: raise ConnectionError("Failed to get token")

                async with AsyncSession(proxy=proxy_url, timeout=20) as s:
                    ws = await s.ws_connect(f"wss://websockets.kick.com/viewer/v1/connect?token={token}", timeout=15)
                    
                    sem.release()
                    was_connected = True
                    connected_viewers_set.add(index)
                    logger({"current_viewers": len(connected_viewers_set)})

                    counter = 0
                    while not stop_event.is_set():
                        counter += 1
                        payload = {"type": "ping"} if counter % 2 == 0 else {"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}}
                        await ws.send_json(payload)
                        await asyncio.sleep(11 + random.randint(2, 7))

            except (asyncio.CancelledError, ConnectionResetError):
                break
            except Exception:
                pass
            finally:
                if sem.locked(): sem.release()
                connected_viewers_set.discard(index)
                if was_connected and not stop_event.is_set():
                    logger({"current_viewers": len(connected_viewers_set)})
            
            if not stop_event.is_set():
                await asyncio.sleep(random.randint(4, 8))

    # --- Orchestration ---
    MAX_CONCURRENT_CONNECTIONS = 200
    connection_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONNECTIONS)
    logger(f"Bot configured for {viewers} viewers with {MAX_CONCURRENT_CONNECTIONS} concurrent connections.")

    connected_viewers = set()
    tasks = [asyncio.create_task(connection_handler(i, connected_viewers, connection_semaphore)) for i in range(viewers)]
    
    start_time = time.time()
    duration_seconds = duration_minutes * 60 if duration_minutes > 0 else float('inf')
    
    try:
        while time.time() - start_time < duration_seconds and not stop_event.is_set():
            logger({
                "current_viewers": len(connected_viewers),
                "target_viewers": viewers,
                "is_running": True
            })
            await asyncio.sleep(5)
    finally:
        shutdown_reason = "stop request received" if stop_event.is_set() else "timer finished"
        logger(f"Shutting down ({shutdown_reason}). Stopping viewers...")
        stop_event.set()
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger({"is_running": False, "current_viewers": 0})
