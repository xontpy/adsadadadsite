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
            status_updater.put(message)
        else:
            # Fallback for simple string messages
            status_updater.put({'status_line': message})
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

async def get_channel_id_async(logger, channel_name, proxies_list):
    """Gets the channel ID using available proxies."""
    if not proxies_list:
        logger("Channel ID Error: No proxies available.")
        return None

    shuffled_proxies = random.sample(proxies_list, len(proxies_list))
    
    for i, proxy_str in enumerate(shuffled_proxies):
        try:
            ip, port, user, pwd = proxy_str.split(":")
            proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
        except ValueError:
            continue

        try:
            async with AsyncSession(impersonate="firefox110", proxy=proxy_url, timeout=10) as s:
                r = await s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                r.raise_for_status()
                data = r.json()
                if "id" in data:
                    logger(f"Successfully found channel ID.")
                    return data["id"]
        except Exception:
            continue
            
    logger("Fatal: Failed to get channel ID after trying all available proxies.")
    return None

async def get_token_async(logger, proxies_list):
    """Gets a viewer token using available proxies."""
    if not proxies_list:
        logger("Token Error: No proxies available.")
        return None, None
            
    shuffled_proxies = random.sample(proxies_list, len(proxies_list))

    for i, proxy_str in enumerate(shuffled_proxies):
        try:
            ip, port, user, pwd = proxy_str.split(":")
            proxy_url = f"http://{user}:{pwd}@{ip}:{port}"
        except ValueError:
            continue
        
        try:
            async with AsyncSession(impersonate="firefox110", proxy=proxy_url, timeout=10) as s:
                await s.get("https://kick.com")
                s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                r = await s.get('https://websockets.kick.com/viewer/v1/token')
                r.raise_for_status()
                return r.json()["data"]["token"], proxy_url
        except Exception:
            continue
    
    return None, None

async def connection_handler_async(logger, channel_id, index, stop_event, proxies_list, connected_viewers_counter):
    """A persistent handler for a single viewer connection."""
    while not stop_event.is_set():
        token, proxy_url = await get_token_async(logger, proxies_list)
        
        if not token:
            await asyncio.sleep(random.randint(3, 7))
            continue

        try:
            async with AsyncSession(impersonate="firefox110", proxy=proxy_url) as session:
                async with session.ws_connect(f"wss://websockets.kick.com/viewer/v1/connect?token={token}", timeout=15) as ws:
                    connected_viewers_counter.add(index)
                    
                    while not stop_event.is_set():
                        await ws.send_json({"type": "ping"})
                        await asyncio.sleep(12)
                        await ws.send_json({"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}})
                        await asyncio.sleep(12)

        except Exception:
            pass
        finally:
            connected_viewers_counter.discard(index)
            if not stop_event.is_set():
                await asyncio.sleep(random.randint(3, 7))

    connected_viewers_counter.discard(index)

def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes, ramp_up_minutes):
    """The main async function to run the bot, adapted for the website."""
    logger = lambda msg: bot_logger(status_updater, msg)
    try:
        logger("Starting bot logic...")
        asyncio.run(run_bot_async(logger, stop_event, channel, viewers, duration_minutes, ramp_up_minutes))
        logger("Bot logic finished.")
    except Exception as e:
        detailed_error = traceback.format_exc()
        logger(f"An unexpected error occurred in the bot's core loop: {e}\nDetails:\n{detailed_error}")
    finally:
        stop_event.set()
        logger("Bot process has stopped.")

async def run_bot_async(logger, stop_event, channel, viewers, duration_minutes, ramp_up_minutes):
    """The main async function to run the bot."""
    duration_seconds = duration_minutes * 60
    ramp_up_seconds = ramp_up_minutes * 60

    proxies = await load_proxies_async(logger)
    if not proxies:
        return

    channel_id = await get_channel_id_async(logger, channel, proxies)
    if not channel_id:
        return

    start_time = time.time()
    connected_viewers = set()
    
    viewer_tasks = []

    # --- Main monitoring loop ---
    end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
    while time.time() < end_time and not stop_event.is_set():
        
        # Ramp-up logic
        elapsed_ramp_up = time.time() - start_time
        if ramp_up_seconds > 0 and elapsed_ramp_up < ramp_up_seconds:
            current_target_viewers = int(viewers * (elapsed_ramp_up / ramp_up_seconds))
        else:
            current_target_viewers = viewers

        # Adjust viewer tasks based on current target
        while len(viewer_tasks) < current_target_viewers:
            task_index = len(viewer_tasks)
            task = asyncio.create_task(connection_handler_async(logger, channel_id, task_index, stop_event, proxies, connected_viewers))
            viewer_tasks.append(task)

        status_payload = {
            'current_viewers': len(connected_viewers),
            'target_viewers': viewers
        }
        logger(status_payload)
        
        await asyncio.sleep(1)

    # --- Shutdown sequence ---
    stop_event.set()
    await asyncio.gather(*viewer_tasks, return_exceptions=True)
    logger("All viewers have been stopped.")
