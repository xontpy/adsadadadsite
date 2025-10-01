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
        if isinstance(message, dict):
            # This is a structured status update (with viewers, etc.)
            status_updater.put(message)
        else:
            # This is a simple string log message, but don't log proxy details
            if "Using proxy" not in str(message):
                 status_updater.put({'log_line': str(message)})
    except Exception:
        sys.stdout.write(f"\r[UI_LOG_FAIL] {message}")
        sys.stdout.flush()

async def load_proxies_async(logger):
    """Loads proxies from 'proxies.txt' with caching."""
    global CACHED_PROXIES, LAST_MODIFIED_TIME
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, "proxies.txt")
    
    try:
        current_mtime = os.path.getmtime(file_path)
        
        if current_mtime == LAST_MODIFIED_TIME and CACHED_PROXIES is not None:
            logger(f"Using {len(CACHED_PROXIES)} cached proxies.")
            return CACHED_PROXIES

        logger("Reloading proxies...")
        with open(file_path, "r") as f:
            proxies = list(set(line.strip() for line in f if line.strip()))
        
        if not proxies:
            logger(f"Error: '{file_path}' is empty.")
            CACHED_PROXIES = None
            return None
            
        logger(f"Loaded and cached {len(proxies)} unique proxies.")
        CACHED_PROXIES = proxies
        LAST_MODIFIED_TIME = current_mtime
        return proxies
        
    except FileNotFoundError:
        logger(f"Error: Proxies file not found: {file_path}.")
        CACHED_PROXIES = None
        return None
    except Exception as e:
        logger(f"An error occurred during proxy loading: {e}")
        return CACHED_PROXIES # Return stale cache if available

async def get_channel_id(session, channel_name, logger):
    try:
        async with session.get(f"https://kick.com/api/v2/channels/{channel_name}") as response:
            response.raise_for_status()
            data = await response.json()
            if "id" in data:
                logger(f"Successfully found channel ID for {channel_name}.")
                return data["id"]
            else:
                logger(f"Could not find channel ID in response for {channel_name}.")
                return None
    except Exception as e:
        logger(f"Failed to get channel ID for {channel_name}: {e}")
        return None

async def send_view(channel_id, proxy, stop_event, logger, connected_viewers_counter, viewer_index):
    """Handles the lifecycle of a single viewer."""
    proxy_url = f"http://{proxy}"
    
    try:
        async with AsyncSession(impersonate="firefox110", proxy=proxy_url, timeout=20) as s:
            # Step 1: Get viewer token
            await s.get("https://kick.com")
            s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
            
            async with s.get('https://websockets.kick.com/viewer/v1/token') as r:
                r.raise_for_status()
                token_data = await r.json()
                token = token_data["data"]["token"]

            # Step 2: Connect to WebSocket
            ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"
            async with s.ws_connect(ws_url, timeout=15) as ws:
                connected_viewers_counter.add(viewer_index)
                logger(f"Viewer {viewer_index} connected.")

                # Step 3: Handshake and Ping loop
                while not stop_event.is_set():
                    await ws.send_json({"type": "ping"})
                    await asyncio.sleep(12)
                    await ws.send_json({"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}})
                    await asyncio.sleep(12)

    except Exception as e:
        logger(f"Viewer {viewer_index} failed: {type(e).__name__}")
    finally:
        connected_viewers_counter.discard(viewer_index)
        logger(f"Viewer {viewer_index} disconnected.")


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

    # Get channel ID using a random proxy
    async with AsyncSession(impersonate="firefox110", proxy=f"http://{random.choice(proxies)}") as s:
        channel_id = await get_channel_id(s, channel, logger)

    if not channel_id:
        logger("Failed to get channel ID. Halting.")
        return

    start_time = time.time()
    connected_viewers = set()

    logger(f"Spawning {viewers} viewer tasks...")
    
    tasks = []
    for i in range(viewers):
        if stop_event.is_set():
            break
        proxy = random.choice(proxies)
        task = asyncio.create_task(send_view(channel_id, proxy, stop_event, logger, connected_viewers, i + 1))
        tasks.append(task)
        await asyncio.sleep(0.1) # Stagger connections slightly

    logger(f"{len(tasks)} tasks spawned.")

    # --- Main monitoring loop ---
    end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
    while time.time() < end_time and not stop_event.is_set():
        if duration_seconds > 0:
            remaining = end_time - time.time()
            mins, secs = divmod(remaining, 60)
            status_line = f"Time Left: {int(mins):02d}:{int(secs):02d}"
        else:
            status_line = "Running indefinitely"
        
        status_update = {
            "status_line": status_line,
            "current_viewers": len(connected_viewers),
            "target_viewers": viewers,
            "is_running": not stop_event.is_set()
        }
        logger(status_update)
        await asyncio.sleep(1)

    # --- Shutdown sequence ---
    if not stop_event.is_set():
        logger("Timer finished or stop requested. Stopping viewers...")
        stop_event.set()
    
    await asyncio.gather(*tasks, return_exceptions=True)
    logger("All viewers have been stopped.")
    logger("run_bot_async finished.")
