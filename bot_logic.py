# --- Imports ---
import asyncio
import random
import sys
import time
import traceback
from curl_cffi import requests, AsyncSession

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

async def load_proxies_async(logger, file_path="proxies.txt"):
    """Loads proxies from the specified file asynchronously."""
    try:
        loop = asyncio.get_event_loop()
        proxies = await loop.run_in_executor(
            None,  # Uses the default executor (a ThreadPoolExecutor)
            lambda: list(set(line.strip() for line in open(file_path, "r") if line.strip()))
        )
        if not proxies:
            logger(f"Error: '{file_path}' is empty.\n")
            return None
        logger(f"Loaded {len(proxies)} unique proxies from: {file_path}\n")
        return proxies
    except FileNotFoundError:
        logger(f"Error: Proxies file not found: {file_path}\n")
        return None
    except Exception as e:
        logger(f"Proxy load error: {e}\n")
        return None

def pick_proxy(logger, proxies_list=None):
    """Picks a random proxy from the provided list."""
    if not proxies_list:
        return None
    proxy = random.choice(proxies_list)
    try:
        ip, port, user, pwd = proxy.split(":")
        return f"http://{user}:{pwd}@{ip}:{port}"
    except ValueError:
        logger(f"Bad proxy format: {proxy}, (use ip:port:user:pass)\n")
        return None
    except Exception as e:
        logger(f"Proxy error: {proxy}, {e}\n")
        return None

async def get_channel_id_async(logger, channel_name, proxies_list):
    """Gets the channel ID using synchronous requests in a thread to avoid blocking."""
    def sync_get_channel_id():
        for i in range(5):
            proxy_url = pick_proxy(logger, proxies_list)
            if not proxy_url:
                time.sleep(0.1)
                continue
            try:
                s = requests.Session(impersonate="firefox135", proxies={"http": proxy_url, "https": proxy_url}, timeout=10)
                r = s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                r.raise_for_status()
                data = r.json()
                if "id" in data:
                    return data["id"]
                else:
                    logger(f"Channel ID attempt {i+1}/5 failed: 'id' not in response.")
            except Exception as e:
                error_type = type(e).__name__
                logger(f"Channel ID attempt {i+1}/5 failed ({error_type})...")
            
            if i < 4:
                time.sleep(1)
        return None

    loop = asyncio.get_event_loop()
    channel_id = await loop.run_in_executor(None, sync_get_channel_id)
    if not channel_id:
        logger("Fatal: Failed to get channel ID after 5 attempts.")
    return channel_id


async def get_token_async(logger, proxies_list):
    """Gets a viewer token using synchronous requests in a thread."""
    def sync_get_token():
        for i in range(5):
            proxy_url = pick_proxy(logger, proxies_list)
            if not proxy_url:
                time.sleep(0.1)
                continue
            try:
                s = requests.Session(impersonate="firefox135", proxies={"http": proxy_url, "https": proxy_url}, timeout=10)
                s.get("https://kick.com") # Warm-up
                s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                r = s.get('https://websockets.kick.com/viewer/v1/token')
                r.raise_for_status()
                return r.json()["data"]["token"], proxy_url
            except Exception as e:
                error_type = type(e).__name__
                logger(f"Token attempt {i+1}/5 failed ({error_type})...")
                time.sleep(1)
        return None, None

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
    end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
    while time.time() < end_time and not stop_event.is_set():
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
