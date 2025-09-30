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
    if status_updater:
        status_updater.put(message)
    else:
        # Fallback to console if no updater is provided
        sys.stdout.write(f"\r[{time.strftime('%H:%M:%S')}] {message}")
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

async def get_channel_id_async(logger, channel_name=None, proxies_list=None):
    """Gets the channel ID using asynchronous requests."""
    for i in range(5):
        proxy_url = pick_proxy(logger, proxies_list)
        if not proxy_url:
            continue
        try:
            async with AsyncSession(impersonate="firefox135", proxies={"http": proxy_url, "https": proxy_url}, timeout=5) as s:
                r = await s.get(f"https://kick.com/api/v2/channels/{channel_name}")
                if r.status_code == 200:
                    return r.json().get("id")
                else:
                    logger(f"Channel ID attempt {i+1}/5 failed with status: {r.status_code}...\n")
        except Exception as e:
            logger(f"Channel ID attempt {i+1}/5 failed with error: {e}...\n")
        await asyncio.sleep(1)
    logger("Failed to get channel ID after multiple retries.\n")
    return None

async def get_token_async(logger, proxies_list=None):
    """Gets a viewer token asynchronously."""
    for _ in range(3):
        proxy_url = pick_proxy(logger, proxies_list)
        if not proxy_url:
            continue
        try:
            async with AsyncSession(impersonate="firefox135", proxy=proxy_url, timeout=10) as session:
                await session.get("https://kick.com")
                session.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                r = await session.get('https://websockets.kick.com/viewer/v1/token')
                if r.status_code == 200:
                    return r.json()["data"]["token"], proxy_url
        except Exception:
            pass
    return None, None

async def get_tokens_in_bulk_async(logger, proxies_list, count):
    """Fetches multiple tokens concurrently with staggering and retries."""
    logger(f"Fetching {count} tokens...")
    valid_tokens = []
    CONCURRENCY_LIMIT = 500
    last_log_time = time.time()

    while len(valid_tokens) < count:
        needed = count - len(valid_tokens)
        batch_size = min(needed, CONCURRENCY_LIMIT)
        
        tasks = []
        for _ in range(batch_size):
            task = asyncio.create_task(get_token_async(logger, proxies_list))
            tasks.append(task)
            await asyncio.sleep(0.01)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        newly_fetched = [res for res in results if res and isinstance(res, tuple) and res[0]]
        valid_tokens.extend(newly_fetched)

        current_time = time.time()
        if current_time - last_log_time > 1.5 or len(valid_tokens) == count:
            logger(f"Fetching tokens: {len(valid_tokens)}/{count} successful.")
            last_log_time = current_time

        if len(valid_tokens) < count and not newly_fetched:
             logger(f"Token fetch stalled. Retrying in 5s...")
             await asyncio.sleep(5)
        elif len(valid_tokens) < count:
            await asyncio.sleep(1)

    return valid_tokens

async def connection_handler_async(logger, channel_id, index, initial_token, initial_proxy_url, stop_event, proxies_list, connected_viewers_counter):
    """A persistent handler for a single viewer connection."""
    token, proxy_url = initial_token, initial_proxy_url

    while not stop_event.is_set():
        if not token:
            new_token_data = await get_token_async(logger, proxies_list)
            if new_token_data and new_token_data[0]:
                token, proxy_url = new_token_data
            else:
                await asyncio.sleep(15)
                continue

        try:
            async with AsyncSession(impersonate="firefox135", proxy=proxy_url) as session:
                ws = await session.ws_connect(f"wss://websockets.kick.com/viewer/v1/connect?token={token}", timeout=10)
                
                await ws.send_json({"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}})
                connected_viewers_counter.add(index)
                
                while not stop_event.is_set():
                    await asyncio.sleep(random.randint(20, 30))
                    await ws.send_json({"type": "ping"})

        except Exception:
            pass
        finally:
            connected_viewers_counter.discard(index)
            token = None
            if not stop_event.is_set():
                await asyncio.sleep(random.randint(5, 10))

    connected_viewers_counter.discard(index)

def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes):
    """The main async function to run the bot, adapted for the website."""
    logger = lambda msg: bot_logger(status_updater, msg)
    try:
        asyncio.run(run_bot_async(logger, stop_event, channel, viewers, duration_minutes))
    except Exception as e:
        detailed_error = traceback.format_exc()
        logger(f"An unexpected error occurred in the bot's core loop: {e}\nDetails:\n{detailed_error}")
    finally:
        logger("Bot process has stopped.")

async def run_bot_async(logger, stop_event, channel, viewers, duration_minutes):
    """The main async function to run the bot."""
    duration_seconds = duration_minutes * 60

    proxies = await load_proxies_async(logger)
    if not proxies:
        return

    channel_id = await get_channel_id_async(logger, channel, proxies)
    if not channel_id:
        return

    tokens_with_proxies = await get_tokens_in_bulk_async(logger, proxies, viewers)
    if not tokens_with_proxies:
        logger("Halting: No tokens were fetched.\n")
        return

    logger(f"Token fetch complete. Spawning {len(tokens_with_proxies)} viewers...")
    start_time = time.time()
    connected_viewers = set()

    # --- Spawn viewer tasks ---
    viewer_tasks = []
    for i, (token, proxy_url) in enumerate(tokens_with_proxies):
        task = asyncio.create_task(connection_handler_async(logger, channel_id, i, token, proxy_url, stop_event, proxies, connected_viewers))
        viewer_tasks.append(task)
        await asyncio.sleep(0.01)

    logger("All viewers spawned. Monitoring status...")

    # --- Main monitoring loop ---
    end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
    while time.time() < end_time and not stop_event.is_set():
        if duration_seconds > 0:
            remaining = end_time - time.time()
            mins, secs = divmod(remaining, 60)
            status_line = f"Time Left: {int(mins):02d}:{int(secs):02d} | Sending Views: {len(connected_viewers)}/{len(tokens_with_proxies)}"
        else:
            status_line = f"Sending Views: {len(connected_viewers)}/{len(tokens_with_proxies)} (Running indefinitely)"
        logger(status_line)
        await asyncio.sleep(1)

    # --- Shutdown sequence ---
    if not stop_event.is_set():
        logger("Timer finished. Stopping viewers...")
        stop_event.set()
    
    await asyncio.gather(*viewer_tasks, return_exceptions=True)
    logger("All viewers have been stopped.")
