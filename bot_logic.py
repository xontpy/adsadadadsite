# --- Imports ---
import asyncio
import random
import sys
import time
from curl_cffi import requests, AsyncSession

# --- Bot Status Logger ---
def status_updater(status_dict, message):
    """Updates the shared status dictionary for the web UI."""
    if status_dict:
        status_dict["status_line"] = message

# --- Core Bot Logic (No changes from the previous version) ---
def load_proxies_sync(logger, file_path="proxies.txt"):
    """Loads proxies from the specified file."""
    try:
        with open(file_path, "r") as f:
            proxies = list(set(line.strip() for line in f if line.strip()))
        if not proxies:
            logger(f"Error: '{file_path}' is empty.")
            return None
        logger(f"Loaded {len(proxies)} unique proxies from: {file_path}")
        return proxies
    except FileNotFoundError:
        logger(f"Error: Proxies file not found: {file_path}")
        return None
    except Exception as e:
        logger(f"Proxy load error: {e}")
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
        logger(f"Bad proxy format: {proxy}, (use ip:port:user:pass)")
        return None
    except Exception as e:
        logger(f"Proxy error: {proxy}, {e}")
        return None

def get_channel_id_sync(logger, channel_name=None, proxies_list=None):
    """Gets the channel ID using synchronous requests."""
    for i in range(5):
        proxy_url = pick_proxy(logger, proxies_list)
        if not proxy_url:
            continue
        try:
            s = requests.Session(impersonate="firefox135", proxies={"http": proxy_url, "https": proxy_url})
            r = s.get(f"https://kick.com/api/v2/channels/{channel_name}", timeout=5)
            if r.status_code == 200:
                return r.json().get("id")
            else:
                logger(f"Channel ID attempt {i+1}/5 failed with status: {r.status_code}...")
        except Exception as e:
            logger(f"Channel ID attempt {i+1}/5 failed with error: {e}...")
        time.sleep(1)
    logger("Failed to get channel ID after multiple retries.")
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
    logger(f"Fetching {count} tokens with high concurrency...")
    valid_tokens = []
    CONCURRENCY_LIMIT = 500

    while len(valid_tokens) < count:
        needed = count - len(valid_tokens)
        batch_size = min(needed, CONCURRENCY_LIMIT)
        logger(f"Requesting a new batch of {batch_size} tokens (staggered)...")
        
        tasks = []
        for _ in range(batch_size):
            task = asyncio.create_task(get_token_async(logger, proxies_list))
            tasks.append(task)
            await asyncio.sleep(0.01)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        newly_fetched = [res for res in results if res and isinstance(res, tuple) and res[0]]
        failed_count = batch_size - len(newly_fetched)
        valid_tokens.extend(newly_fetched)

        logger(f"Batch summary: {len(newly_fetched)} successful, {failed_count} failed. Total tokens: {len(valid_tokens)}/{count}.")

        if len(valid_tokens) < count:
            if failed_count > 0:
                logger("Pausing for 5s before next batch due to failures...")
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(2)

    logger(f"Successfully fetched all {count} tokens.")
    return valid_tokens

async def connection_handler_async(logger, channel_id, index, initial_token, initial_proxy_url, stop_event, proxies_list, connected_viewers_counter):
    """A persistent handler for a single viewer connection."""
    token, proxy_url = initial_token, initial_proxy_url

    while not stop_event.is_set():
        if not token:
            logger(f"[{index}] Attempting to get a new token...")
            new_token_data = await get_token_async(logger, proxies_list)
            if new_token_data and new_token_data[0]:
                token, proxy_url = new_token_data
                logger(f"[{index}] Successfully got new token.")
            else:
                logger(f"[{index}] Failed to get a new token, retrying in 15s...")
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

        except Exception as e:
            logger(f"[{index}] Connection error. Reconnecting with new token... Error: {e}")
        finally:
            connected_viewers_counter.discard(index)
            token = None
            if not stop_event.is_set():
                await asyncio.sleep(random.randint(5, 10))

    logger(f"[{index}] Viewer task stopped.")
    connected_viewers_counter.discard(index)

# --- Main Logic for Web Integration ---
async def run_bot_async(channel, viewers, duration_seconds, stop_event, status_dict, proxies_path):
    """The main async function to run the bot, adapted for web server integration."""
    logger = lambda msg: status_updater(status_dict, msg)
    
    logger("Bot process started. Loading proxies...")
    proxies = load_proxies_sync(logger, file_path=proxies_path)
    if not proxies:
        logger("Halting: No proxies loaded.")
        return

    logger(f"Getting channel ID for '{channel}'...")
    channel_id = get_channel_id_sync(logger, channel, proxies)
    if not channel_id:
        logger(f"Halting: Could not get channel ID for '{channel}'.")
        return

    logger(f"Acquiring {viewers} viewer tokens...")
    tokens_with_proxies = await get_tokens_in_bulk_async(logger, proxies, viewers)
    if not tokens_with_proxies:
        logger("Halting: No tokens were fetched.")
        return

    logger("Token acquisition finished. Spawning viewers...")
    start_time = time.time()
    connected_viewers = set()

    viewer_tasks = []
    for i, (token, proxy_url) in enumerate(tokens_with_proxies):
        task = asyncio.create_task(connection_handler_async(logger, channel_id, i, token, proxy_url, stop_event, proxies, connected_viewers))
        viewer_tasks.append(task)
        await asyncio.sleep(0.01)

    logger("All viewer tasks launched. Monitoring session.")

    end_time = start_time + duration_seconds if duration_seconds > 0 else float('inf')
    while time.time() < end_time and not stop_event.is_set():
        if duration_seconds > 0:
            remaining = end_time - time.time()
            mins, secs = divmod(remaining, 60)
            status_line = f"Time Left: {int(mins):02d}:{int(secs):02d} | Sending Views: {len(connected_viewers)}/{len(tokens_with_proxies)}"
        else:
            status_line = f"Sending Views: {len(connected_viewers)}/{len(tokens_with_proxies)} (Running indefinitely)"
        logger(status_line)
        await asyncio.sleep(5)

    if not stop_event.is_set():
        logger("Timer finished. Signaling all viewer tasks to stop.")
        stop_event.set()
    
    await asyncio.gather(*viewer_tasks, return_exceptions=True)
    logger("All viewer tasks have been terminated.")
    status_dict["running"] = False

def run_viewbot_logic(channel, num_viewers, duration_seconds, stop_event, username, proxies_path, status_dict):
    """Synchronous wrapper to be called by the multiprocessing Process."""
    try:
        asyncio.run(run_bot_async(channel, num_viewers, duration_seconds, stop_event, status_dict, proxies_path))
    except KeyboardInterrupt:
        # This is unlikely to be triggered in a subprocess but is good practice
        pass
    finally:
        status_updater(status_dict, "Bot process has shut down.")
        status_dict["running"] = False
