# Cache-busting comment
import asyncio
import random
import time
import curl_cffi
from curl_cffi import requests, AsyncSession
import sys

# --- Core Bot Logic ---

def console_logger(message):
    """A simple logger that prints to the console."""
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

def load_proxies_sync(logger=console_logger, file_path="proxies.txt"):
    """Loads proxies from the specified file (SYNC)."""
    try:
        with open(file_path, "r") as f:
            # Use a set to automatically handle duplicates, then convert to list
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

def pick_proxy(logger=console_logger, proxies_list=None):
    """Picks a random proxy from the provided list."""
    if not proxies_list:
        return None, None
    proxy = random.choice(proxies_list)
    try:
        ip, port, user, pwd = proxy.split(":")
        # Corrected proxy format
        full_url = f"http://{user}:{pwd}@{ip}:{port}"
        proxy_dict = {"http": full_url, "https": full_url}
        return proxy_dict, full_url
    except ValueError:
        logger(f"Bad proxy format: {proxy}, (use ip:port:user:pass)")
        return None, None
    except Exception as e:
        logger(f"Proxy error: {proxy}, {e}")
        return None, None

def get_channel_id_sync(logger=console_logger, channel_name=None, proxies_list=None):
    """Gets the channel ID using synchronous requests (SYNC)."""
    for _ in range(5):
        s = requests.Session(impersonate="firefox135")
        proxy_dict, _ = pick_proxy(logger, proxies_list)
        if not proxy_dict:
            continue
        s.proxies = proxy_dict
        try:
            r = s.get(f"https://kick.com/api/v2/channels/{channel_name}", timeout=5)
            if r.status_code == 200:
                return r.json().get("id")
            else:
                logger(f"Channel ID: {r.status_code}, retrying...")
        except Exception as e:
            logger(f"Channel ID error: {e}, retrying...")
        time.sleep(1)
    logger("Failed to get channel ID after multiple retries.")
    return None

def get_token_sync(logger=console_logger, proxies_list=None):
    """Gets a viewer token using synchronous requests (SYNC)."""
    for _ in range(5):
        s = requests.Session(impersonate="firefox135")
        proxy_dict, proxy_url = pick_proxy(logger, proxies_list)
        if not proxy_dict:
            continue
        s.proxies = proxy_dict
        try:
            s.get("https://kick.com", timeout=5)
            s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
            r = s.get('https://websockets.kick.com/viewer/v1/token', timeout=5)
            if r.status_code == 200:
                return r.json()["data"]["token"], proxy_url
            else:
                logger(f"Token: {r.status_code}, trying another proxy...")
        except Exception as e:
            logger(f"Token error: {e}, trying another proxy...")
        time.sleep(1)
    return None, None

# --- Async wrappers for Discord Bot ---

async def load_proxies_async(logger=console_logger, file_path="proxies.txt"):
    return await asyncio.to_thread(load_proxies_sync, logger, file_path)

async def get_channel_id_async(logger=console_logger, channel_name=None, proxies_list=None):
    return await asyncio.to_thread(get_channel_id_sync, logger, channel_name, proxies_list)

async def get_token_async(logger=console_logger, proxies_list=None):
    """Gets a viewer token using fully asynchronous requests for maximum speed."""
    # This function is designed for speed and high concurrency.
    # It will retry up to 3 times with different proxies if it fails.
    for _ in range(3):
        _, proxy_url = pick_proxy(logger, proxies_list)
        if not proxy_url:
            continue # Try to get another proxy if the format was bad

        try:
            # Use AsyncSession for non-blocking I/O
            async with AsyncSession(impersonate="firefox135", proxy=proxy_url, timeout=10) as session:
                # The first request warms up the session and gets cookies
                await session.get("https://kick.com")
                
                # Set the required header for the token request
                session.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                
                # Make the actual token request
                r = await session.get('https://websockets.kick.com/viewer/v1/token')
                
                if r.status_code == 200:
                    token = r.json()["data"]["token"]
                    return token, proxy_url # Success
        except Exception:
            # Silently ignore errors and retry with a new proxy
            pass
            
    return None, None # Failed after all retries


# --- Main connection logic (used by both GUI and Discord bot) ---

async def get_tokens_in_bulk_async(logger, proxies_list, count):
    """Fetches multiple tokens concurrently in batches, retrying until the desired count is met."""
    logger(f"Fetching {count} tokens with high concurrency...")
    valid_tokens = []
    # Set a much higher concurrency limit for extreme speed
    CONCURRENCY_LIMIT = 500

    while len(valid_tokens) < count:
        needed = count - len(valid_tokens)
        
        # Determine the size of the next batch
        batch_size = min(needed, CONCURRENCY_LIMIT)
        
        logger(f"Requesting a new batch of {batch_size} tokens...")
        tasks = [get_token_async(logger, proxies_list) for _ in range(batch_size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter for successful results and extract them
        newly_fetched = [res for res in results if res and isinstance(res, tuple) and res[0]]
        failed_count = batch_size - len(newly_fetched)

        valid_tokens.extend(newly_fetched)

        logger(f"Batch summary: {len(newly_fetched)} successful, {failed_count} failed. Total tokens: {len(valid_tokens)}/{count}.")

        if len(valid_tokens) < count:
            # Brief pause before the next batch to avoid getting rate-limited
            await asyncio.sleep(2)

    logger(f"Successfully fetched all {count} tokens.")
    return valid_tokens


async def connection_handler_async(logger, channel_id, index, initial_token, initial_proxy_url, stop_event, proxies_list, connected_viewers_counter):
    """
    A persistent handler for a single viewer connection.
    It uses an initial token but will fetch new ones if the connection drops.
    """
    token = initial_token
    proxy_url = initial_proxy_url

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

        ws = None
        try:
            # Reverted to user's requested logic, but keeping impersonate for better connection success
            async with AsyncSession(impersonate="firefox135", proxy=proxy_url) as session:
                ws = await session.ws_connect(
                    f"wss://websockets.kick.com/viewer/v1/connect?token={token}",
                    timeout=10
                )
                
                connected_viewers_counter.add(index)
                counter = 0
                while not stop_event.is_set():
                    counter += 1
                    if counter % 2 == 0:
                        await ws.send_json({"type": "ping"})
                    else:
                        await ws.send_json({
                            "type": "channel_handshake",
                            "data": {"message": {"channelId": channel_id}}
                        })
                    
                    delay = 11 + random.randint(2, 7)
                    await asyncio.sleep(delay)

        except (curl_cffi.errors.CurlError, asyncio.TimeoutError) as e:
            logger(f"[{index}] Connection error: {e}. Reconnecting with new token...")
        except Exception as e:
            logger(f"[{index}] Unexpected error: {e}. Reconnecting with new token...")
        finally:
            if ws:
                await ws.close()
            
            connected_viewers_counter.discard(index)
            
            # Force a new token on any kind of disconnect
            token = None 
            
            if not stop_event.is_set():
                # Wait before trying to reconnect
                await asyncio.sleep(random.randint(5, 10))

    logger(f"[{index}] Viewer task stopped.")
    connected_viewers_counter.discard(index)

async def start_viewbot_async(channel_name, viewers, duration, stop_event, discord_user=None):
    """Asynchronously starts the viewbot logic and returns a future."""
    loop = asyncio.get_running_loop()
    
    def thread_target():
        # This function is what the thread will execute.
        # It runs the synchronous viewbot logic.
        run_viewbot_logic(channel_name, viewers, duration, stop_event, discord_user)

    # loop.run_in_executor schedules the function to run in a thread pool
    # and returns a Future object that can be awaited and cancelled.
    future = loop.run_in_executor(
        None,  # Use the default executor (a ThreadPoolExecutor)
        thread_target
    )
    
    return future

def run_viewbot_logic(channel_name, viewers, duration, stop_event, discord_user=None, proxies_path="proxies.txt", status_dict=None):
    """The core logic for running the viewbot, using the async connection handler."""
    
    # A simple logger that can be redirected if needed
    def logger(message):
        print(f"[{time.strftime('%H:%M:%S')}] {message}")
        if status_dict is not None:
            status_dict["status_line"] = message

    try:
        duration_text = f"for {duration // 60} minutes" if duration else "indefinitely"
        log_message = f"Starting viewbot for {channel_name} with {viewers} viewers {duration_text}."
        if discord_user:
            log_message += f" (Requested by {discord_user})"
        logger(log_message)

        proxies = load_proxies_sync(logger, file_path=proxies_path)
        if not proxies:
            logger("❌ No proxies loaded. Stopping.")
            return

        channel_id = get_channel_id_sync(logger, channel_name, proxies)
        if not channel_id:
            logger(f"❌ Failed to get channel ID for {channel_name}. Stopping.")
            return

        # This async function will be the entry point for our asyncio event loop.
        async def main():
            # 1. Fetch tokens concurrently
            tokens_with_proxies = await get_tokens_in_bulk_async(logger, proxies, viewers)
            if not tokens_with_proxies:
                logger("Halting: No tokens were fetched.")
                return

            # 2. Initialize state
            logger("Token acquisition finished.")
            start_time = time.time()
            end_time = start_time + duration if duration else float('inf')
            connected_viewers = set()
            
            # 3. Spawn viewer tasks with a stagger
            logger(f"Sending {len(tokens_with_proxies)} viewers to {channel_name}...")
            
            viewer_tasks = []
            for i, (token, proxy_url) in enumerate(tokens_with_proxies):
                task = asyncio.create_task(
                    connection_handler_async(logger, channel_id, i, token, proxy_url, stop_event, proxies, connected_viewers)
                )
                viewer_tasks.append(task)
                # Stagger the launch of each connection to avoid overwhelming the server/network
                await asyncio.sleep(0.1) 

            # 4. Main monitoring loop
            logger("All viewer tasks have been launched. Monitoring session.")
            while time.time() < end_time and not stop_event.is_set():
                if duration:
                    remaining = end_time - time.time()
                    mins, secs = divmod(remaining, 60)
                    status_line = f"Time Left: {int(mins):02d}:{int(secs):02d} | Sending Views: {len(connected_viewers)}/{len(tokens_with_proxies)}"
                else: # Indefinite
                    status_line = f"Sending Views: {len(connected_viewers)}/{len(tokens_with_proxies)}"
                
                logger(status_line)
                await asyncio.sleep(5)

            # 5. Shutdown sequence
            if not stop_event.is_set():
                logger("Timer finished. Signaling all viewer tasks to stop.")
                stop_event.set()
            else:
                logger("Bot was stopped externally. Stopping viewer tasks...")

            # Wait for all viewer tasks to gracefully shut down
            await asyncio.gather(*viewer_tasks, return_exceptions=True)
            logger("All viewer tasks have been terminated.")

        asyncio.run(main())

    except Exception as e:
        error_message = f"An error occurred in the viewbot: {e}"
        logger(error_message)
        if status_dict is not None:
            status_dict["status_line"] = error_message
    finally:
        completion_message = f"Viewbot session for {channel_name} has finished."
        logger(completion_message)
        if status_dict is not None:
            status_dict["running"] = False
            status_dict["status_line"] = completion_message
