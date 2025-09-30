# --- Imports ---
import asyncio
import os
import random
import sys
import time
import traceback
from curl_cffi import requests, AsyncSession

# --- Global Cache for Proxies ---
CACHED_PROXIES = None
LAST_MODIFIED_TIME = 0

# --- Core Bot Logic ---

def bot_logger(status_updater, message):
    """A simple logger that sends messages to the web UI."""
    try:
        if status_updater:
            status_updater.put(message)
        else:
            # Fallback to console if no updater is provided
            sys.stdout.write(f"\r[{time.strftime('%H:%M:%S')}] {message}")
            sys.stdout.flush()
    except Exception:
        # If the UI queue fails, log to console to prevent a crash.
        sys.stdout.write(f"\r[UI_LOG_FAIL] {message}")
        sys.stdout.flush()

async def load_proxies_async(logger):
    """Loads proxies from 'proxies.txt' located in the script's directory, with caching."""
    global CACHED_PROXIES, LAST_MODIFIED_TIME
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "proxies.txt")
    
    try:
        current_mtime = os.path.getmtime(file_path)
        
        if current_mtime == LAST_MODIFIED_TIME and CACHED_PROXIES is not None:
            logger(f"Using {len(CACHED_PROXIES)} cached proxies.\n")
            return CACHED_PROXIES

        logger("Proxy file has changed or cache is empty. Reloading proxies...")
        loop = asyncio.get_event_loop()
        proxies = await loop.run_in_executor(
            None,
            lambda: list(set(line.strip() for line in open(file_path, "r") if line.strip()))
        )
        
        if not proxies:
            logger(f"Error: '{file_path}' is empty. Cache invalidated.\n")
            CACHED_PROXIES = None
            LAST_MODIFIED_TIME = 0
            return None
            
        logger(f"Loaded and cached {len(proxies)} unique proxies from: {file_path}\n")
        CACHED_PROXIES = proxies
        LAST_MODIFIED_TIME = current_mtime
        return proxies
        
    except FileNotFoundError:
        logger(f"Error: Proxies file not found: {file_path}. Cache invalidated.\n")
        CACHED_PROXIES = None
        LAST_MODIFIED_TIME = 0
        return None
    except Exception as e:
        logger(f"An error occurred during proxy loading: {e}\n")
        if CACHED_PROXIES is not None:
            logger(f"Returning {len(CACHED_PROXIES)} stale cached proxies due to error.\n")
            return CACHED_PROXIES
        return None

async def get_channel_id_async(logger, channel_name, proxies_list):
    """
    Gets the channel ID by trying all available proxies in a random order.
    Uses synchronous requests in a thread to avoid blocking asyncio loop.
    """
    def sync_get_channel_id():
        if not proxies_list:
            logger("Channel ID Error: No proxies available in the list.\n")
            return None

        shuffled_proxies = random.sample(proxies_list, len(proxies_list))
        
        for i, proxy_str in enumerate(shuffled_proxies):
            try:
                ip, port, user, pwd = proxy_str.split(":")
                proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
            except ValueError:
                # This proxy is malformed, log it and skip.
                if i < 5: # Log first few malformed proxies to avoid spam
                    logger(f"Bad proxy format: {proxy_str}, skipping.\n")
                continue

            try:
                s = requests.Session(impersonate="firefox135", proxies={"http": proxy_url, "https": proxy_url}, timeout=10)
                r = s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                r.raise_for_status()
                data = r.json()
                if "id" in data:
                    logger(f"Successfully found channel ID using proxy {ip} on attempt {i+1}.\n")
                    return data["id"]
                else:
                    # This case is unlikely if status is 200, but good to have.
                    if i < 5:
                        logger(f"Channel ID attempt {i+1}/{len(shuffled_proxies)} failed: 'id' not in response from proxy {ip}.\n")
            except Exception as e:
                error_type = type(e).__name__
                if i < 5: # Log first 5 errors to avoid spamming the UI
                    logger(f"Channel ID attempt {i+1}/{len(shuffled_proxies)} with proxy {ip} failed ({error_type})...\n")
            
        return None # All proxies were tried and failed.

    loop = asyncio.get_event_loop()
    channel_id = await loop.run_in_executor(None, sync_get_channel_id)
    if not channel_id:
        logger("Fatal: Failed to get channel ID after trying all available proxies.\n")
    return channel_id


async def get_token_async(logger, proxies_list):
    """
    Gets a viewer token by trying all available proxies in a random order.
    Uses synchronous requests in a thread.
    """
    def sync_get_token():
        if not proxies_list:
            logger("Token Error: No proxies available in the list.\n")
            return None, None
            
        shuffled_proxies = random.sample(proxies_list, len(proxies_list))

        for i, proxy_str in enumerate(shuffled_proxies):
            try:
                ip, port, user, pwd = proxy_str.split(":")
                proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
            except ValueError:
                if i < 5:
                    logger(f"Bad proxy format: {proxy_str}, skipping.\n")
                continue
            
            try:
                s = requests.Session(impersonate="firefox135", proxies={"http": proxy_url, "https": proxy_url}, timeout=10)
                s.get("https://kick.com") # Warm-up
                s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                r = s.get('https://websockets.kick.com/viewer/v1/token')
                r.raise_for_status()
                logger(f"Token found successfully on attempt {i+1}.\n")
                return r.json()["data"]["token"], proxy_url
            except Exception as e:
                error_type = type(e).__name__
                if i < 5:
                    logger(f"Token attempt {i+1}/{len(shuffled_proxies)} with proxy {ip} failed ({error_type})...\n")
        
        return None, None # All proxies failed

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sync_get_token)


async def connection_handler_async(logger, channel_id, index, stop_event, proxies_list, connected_viewers_counter):
    """A persistent handler for a single viewer connection, inspired by main (2).py."""
    logger(f"[{index}] Viewer task started.")
    
    while not stop_event.is_set():
        token, proxy_url = await get_token_async(logger, proxies_list)
        
        if not token:
            logger(f"[{index}] Failed to get token, retrying in 3-7s...")
            await asyncio.sleep(random.randint(3, 7))
            continue

        ws = None
        session = None
        try:
            logger(f"[{index}] Got token, attempting to connect...")
            session = AsyncSession(impersonate="firefox135", proxy=proxy_url)
            ws = await session.ws_connect(f"wss://websockets.kick.com/viewer/v1/connect?token={token}", timeout=15)
            
            connected_viewers_counter.add(index)
            logger(f"[{index}] Connection successful.")

            # Simplified ping/handshake loop
            while not stop_event.is_set():
                await ws.send_json({"type": "ping"})
                await asyncio.sleep(12)
                await ws.send_json({"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}})
                await asyncio.sleep(12)

        except Exception as e:
            error_type = type(e).__name__
            logger(f"[{index}] Disconnected ({error_type}). Re-establishing connection...")
        finally:
            connected_viewers_counter.discard(index)
            if ws:
                try: await ws.close()
                except: pass
            if session:
                await session.close()
            
            if not stop_event.is_set():
                await asyncio.sleep(random.randint(3, 7))

    logger(f"[{index}] Viewer task stopped.")
    connected_viewers_counter.discard(index)


def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes):
    """The main async function to run the bot, adapted for the website."""
    logger = lambda msg: bot_logger(status_updater, msg)
    try:
        logger("Starting bot_logic.py main asyncio loop...")
        asyncio.run(run_bot_async(logger, stop_event, channel, viewers, duration_minutes))
        logger("bot_logic.py main asyncio loop finished successfully.")
    except Exception as e:
        detailed_error = traceback.format_exc()
        logger(f"An unexpected error occurred in the bot's core loop: {e}\nDetails:\n{detailed_error}")
        stop_event.set()
    finally:
        if not stop_event.is_set():
            stop_event.set()
        logger("Bot process has stopped.")


async def run_bot_async(logger, stop_event, channel, viewers, duration_minutes):
    """The main async function to run the bot."""
    logger("run_bot_async started.")
    duration_seconds = duration_minutes * 60

    proxies = await load_proxies_async(logger)
    if not proxies:
        logger("run_bot_async: No proxies loaded, returning.")
        return

    channel_id = await get_channel_id_async(logger, channel, proxies)
    if not channel_id:
        logger("Failed to get channel ID. Halting.")
        return

    start_time = time.time()
    connected_viewers = set()

    logger(f"Spawning {viewers} viewer tasks...")
    viewer_tasks = [
        asyncio.create_task(connection_handler_async(logger, channel_id, i, stop_event, proxies, connected_viewers))
        for i in range(viewers)
    ]

    # --- Main monitoring loop ---
    last_proxy_reload_time = time.time()
    end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
    while time.time() < end_time and not stop_event.is_set():
        # --- Proxy Health Check & Reload ---
        # Reload proxies every 10 minutes if they seem to be failing.
        if time.time() - last_proxy_reload_time > 600:
            logger("Performing periodic proxy health check...")
            # A simple health check: if view count is 0, try reloading proxies.
            if len(connected_viewers) == 0 and viewers > 0:
                logger("View count is 0, attempting to reload proxies to get a fresh list.")
                new_proxies = await load_proxies_async(logger)
                if new_proxies and new_proxies != proxies:
                    proxies = new_proxies
                    # To apply the new proxies, we must restart the viewer tasks.
                    logger("Restarting all viewer tasks to apply new proxies...")
                    for task in viewer_tasks:
                        task.cancel()
                    await asyncio.gather(*viewer_tasks, return_exceptions=True)
                    
                    viewer_tasks = [
                        asyncio.create_task(connection_handler_async(logger, channel_id, i, stop_event, proxies, connected_viewers))
                        for i in range(viewers)
                    ]
                    logger(f"{len(viewer_tasks)} viewer tasks have been restarted.")
                else:
                    logger("Proxy reload did not yield a new list. Continuing with current proxies.")
            last_proxy_reload_time = time.time()

        if duration_seconds > 0:
            remaining = end_time - time.time()
            mins, secs = divmod(remaining, 60)
            status_line = f"Time Left: {int(mins):02d}:{int(secs):02d} | Sending Views: {len(connected_viewers)}/{viewers}"
        else:
            status_line = f"Sending Views: {len(connected_viewers)}/{viewers} (Running indefinitely)"
        logger(status_line)
        await asyncio.sleep(1)

    # --- Shutdown sequence ---
    if not stop_event.is_set():
        logger("Timer finished. Stopping viewers...")
        stop_event.set()
    
    await asyncio.gather(*viewer_tasks, return_exceptions=True)
    logger("All viewers have been stopped.")
    logger("run_bot_async finished.")
