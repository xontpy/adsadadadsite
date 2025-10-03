import asyncio
import json
import random
import re
import threading
import time
import queue
import tls_client
from fake_useragent import UserAgent

# --- Configuration from kick.py ---
ua = UserAgent()
CLIENT_TOKEN = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
WS_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
    'User-Agent': ua.random,
    'sec-ch-ua': '"Chromium";v="137", "Google Chrome";v="137", "Not-A.Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
}

# --- Functions from kick.py (adapted) ---

def extract_channel_name(input_str):
    if "kick.com/" in input_str:
        parts = input_str.split("kick.com/")
        channel = parts[1].split("/")[0].split("?")[0]
        return channel.lower()
    return input_str.lower()

def get_channel_id(channel_name, status_queue):
    try:
        s = tls_client.Session(client_identifier="chrome_120", random_tls_extension_order=True)
        s.headers.update({
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://kick.com/',
            'Origin': 'https://kick.com',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })
        
        try:
            response = s.get(f'https://kick.com/api/v2/channels/{channel_name}')
            status_queue.put({'log_line': f"get_channel_id (v2) status: {response.status_code}"})
            if response.status_code == 200:
                return response.json().get("id")
        except Exception as e:
            status_queue.put({'log_line': f"get_channel_id (v2) failed: {e}"})

        try:
            response = s.get(f'https://kick.com/api/v1/channels/{channel_name}')
            status_queue.put({'log_line': f"get_channel_id (v1) status: {response.status_code}"})
            if response.status_code == 200:
                return response.json().get("id")
        except Exception as e:
            status_queue.put({'log_line': f"get_channel_id (v1) failed: {e}"})

        try:
            response = s.get(f'https://kick.com/{channel_name}')
            status_queue.put({'log_line': f"get_channel_id (scrape) status: {response.status_code}"})
            if response.status_code == 200:
                patterns = [
                    r'"id":(\d+).*?"slug":"' + re.escape(channel_name) + r'"',
                    r'"channel_id":(\d+)',
                    r'channelId["\']:\s*(\d+)',
                    r'channel.*?id["\']:\s*(\d+)'
                ]
                for pattern in patterns:
                    match = re.search(pattern, response.text, re.IGNORECASE)
                    if match:
                        return int(match.group(1))
        except Exception as e:
            status_queue.put({'log_line': f"get_channel_id (scrape) failed: {e}"})
        
        status_queue.put({'log_line': f"All methods failed to get channel ID for: {channel_name}"})
        return None
        
    except Exception as e:
        status_queue.put({'log_line': f"Error getting channel ID: {e}"})
        return None

def get_token(status_queue):
    try:
        s = tls_client.Session(client_identifier="chrome_120", random_tls_extension_order=True)
        s.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })
        
        try:
            s.get("https://kick.com")
            s.headers["X-CLIENT-TOKEN"] = CLIENT_TOKEN
            response = s.get('https://websockets.kick.com/viewer/v1/token')
            if response.status_code == 200:
                data = response.json()
                token = data.get("data", {}).get("token")
                if token:
                    return token
        except Exception as e:
            status_queue.put({'log_line': f"get_token (primary) failed: {e}"})

        token_endpoints = [
            'https://websockets.kick.com/viewer/v1/token',
            'https://kick.com/api/websocket/token',
            'https://kick.com/api/v1/websocket/token'
        ]
        for endpoint in token_endpoints:
            try:
                s.headers["X-CLIENT-TOKEN"] = CLIENT_TOKEN
                response = s.get(endpoint, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    token = data.get("data", {}).get("token") or data.get("token")
                    if token:
                        return token
            except Exception as e:
                status_queue.put({'log_line': f"get_token (fallback {endpoint}) failed: {e}"})
                continue
        
        status_queue.put({'log_line': "Failed to get WebSocket token from all endpoints"})
        return None
        
    except Exception as e:
        status_queue.put({'log_line': f"Error getting WebSocket token: {e}"})
        return None

async def _websocket_worker(channel_id, initial_token, stop_event, status_queue):
    token = initial_token
    while not stop_event.is_set():
        if not token:
            token = get_token(status_queue)
            if not token:
                await asyncio.sleep(3)
                continue

        try:
            ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"
            async with websockets.connect(ws_url) as websocket:
                handshake_msg = {"type": "channel_handshake", "data": {"message": {"channelId": channel_id}}}
                await websocket.send(json.dumps(handshake_msg))
                
                ping_count = 0
                while ping_count < 10 and not stop_event.is_set():
                    ping_count += 1
                    await websocket.send(json.dumps({"type": "ping"}))
                    
                    for _ in range(12 + random.randint(1, 5)):
                        if stop_event.is_set():
                            break
                        await asyncio.sleep(1)
                    if stop_event.is_set():
                        break
            token = None
        except Exception as e:
            status_queue.put({'log_line': f"Websocket error: {e}"})
            await asyncio.sleep(random.randint(4, 8))
            token = None

def start_connection_thread(channel_id, initial_token, stop_event, status_queue):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_websocket_worker(channel_id, initial_token, stop_event, status_queue))

def fetch_token_job(index, tokens_list, status_queue):
    tokens_list[index] = get_token(status_queue)

def run_viewbot_logic(status_queue, stop_event, channel, total_views, duration, rapid):
    try:
        channel = extract_channel_name(channel)
        status_queue.put({'log_line': f"Fetching channel ID for: {channel}"})
        channel_id = get_channel_id(channel, status_queue)
        if not channel_id:
            status_queue.put({'log_line': "Channel not found."})
            return

        status_queue.put({'log_line': f"Channel ID found: {channel_id}"})
        status_queue.put({'log_line': f"Fetching {total_views} tokens..."})

        tokens = []
        while len(tokens) < total_views and not stop_event.is_set():
            needed = total_views - len(tokens)
            status_queue.put({'log_line': f"Need to fetch {needed} more tokens..."})

            newly_fetched = [None] * needed
            threads = []
            for i in range(needed):
                if stop_event.is_set(): break
                t = threading.Thread(target=fetch_token_job, args=(i, newly_fetched, status_queue))
                threads.append(t)
                t.start()
                if rapid:
                    time.sleep(0.1)

            for t in threads:
                t.join()

            valid_new_tokens = [t for t in newly_fetched if t]
            tokens.extend(valid_new_tokens)

            status_queue.put({'log_line': f"Fetched {len(valid_new_tokens)} new tokens. Total: {len(tokens)}/{total_views}"})
            status_queue.put({'current_viewers': len(tokens)})

            if len(tokens) < total_views and not stop_event.is_set():
                status_queue.put({'log_line': "Some token fetches failed, retrying in 3 seconds..."})
                time.sleep(3)

        if stop_event.is_set():
            status_queue.put({'log_line': "Bot stopping during token fetch."})
            return

        status_queue.put({'log_line': f"Successfully fetched {len(tokens)} tokens. Starting viewers..."})

        threads = []
        for i, token in enumerate(tokens):
            if stop_event.is_set(): break
            t = threading.Thread(target=start_connection_thread, args=(channel_id, token, stop_event, status_queue))
            t.daemon = True
            threads.append(t)
            t.start()

        start_time = time.time()
        end_time = start_time + duration * 60 if duration > 0 else float('inf')

        while time.time() < end_time and not stop_event.is_set():
            alive_count = sum(1 for t in threads if t.is_alive())
            status_queue.put({'current_viewers': alive_count})
            time.sleep(2)

        stop_event.set()
        status_queue.put({'log_line': "Bot stopping..."})

    except Exception as e:
        status_queue.put({'log_line': f"An error occurred: {e}"})
    finally:
        status_queue.put({'log_line': "Viewbot logic finished."})
        status_queue.put({'is_running': False})

if __name__ == "__main__":
    channel = input("Channel link or name: ").split("/")[-1]
    total_views = int(input("How many viewers to send: "))
    duration = int(input("Enter duration in minutes (0 for unlimited): "))

    status_queue = queue.Queue()
    stop_event = threading.Event()

    bot_thread = threading.Thread(target=run_viewbot_logic, args=(status_queue, stop_event, channel, total_views, duration, False))
    bot_thread.start()

    try:
        while bot_thread.is_alive():
            try:
                item = status_queue.get_nowait()
                print(item)
            except queue.Empty:
                time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping bot...")
        stop_event.set()
    
    bot_thread.join()
    print("Bot has been shut down.")
