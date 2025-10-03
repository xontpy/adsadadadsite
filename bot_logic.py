import asyncio
import random
import re
import threading
import time
import json
import tls_client
import websockets

def get_channel_id(channel_name):
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
            if response.status_code == 200:
                data = response.json()
                return data.get("id")
        except Exception:
            pass
        
        try:
            response = s.get(f'https://kick.com/api/v1/channels/{channel_name}')
            if response.status_code == 200:
                data = response.json()
                return data.get("id")
        except Exception:
            pass
        
        try:
            response = s.get(f'https://kick.com/{channel_name}')
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
        except Exception:
            pass
        
        return None
        
    except Exception:
        return None

def get_token():
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
            s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
            response = s.get('https://websockets.kick.com/viewer/v1/token')
            
            if response.status_code == 200:
                data = response.json()
                token = data.get("data", {}).get("token")
                if token:
                    return token
        except Exception:
            pass
        
        token_endpoints = [
            'https://websockets.kick.com/viewer/v1/token',
            'https://kick.com/api/websocket/token',
            'https://kick.com/api/v1/websocket/token'
        ]
        
        for endpoint in token_endpoints:
            try:
                s.headers["X-CLIENT-TOKEN"] = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"
                response = s.get(endpoint, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    token = data.get("data", {}).get("token") or data.get("token")
                    if token:
                        return token
            except Exception:
                continue
        
        return None
        
    except Exception:
        return None

async def _websocket_worker(channel_id, index, initial_token):
    token = initial_token
    while True:
        if not token:
            token = get_token()
            if not token:
                await asyncio.sleep(3)
                continue
            print(f"[{index}] Got new token: {token}")
        else:
            print(f"[{index}] Using token: {token}")

        try:
            ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"
            
            async with websockets.connect(ws_url) as websocket:
                handshake_msg = {
                    "type": "channel_handshake",
                    "data": {"message": {"channelId": channel_id}}
                }
                await websocket.send(json.dumps(handshake_msg))
                print(f"[{index}] handshake sent")
                
                ping_count = 0
                while ping_count < 10:
                    ping_count += 1
                    
                    ping_msg = {"type": "ping"}
                    await websocket.send(json.dumps(ping_msg))
                    print(f"[{index}] ping")
                    
                    sleep_time = 12 + random.randint(1, 5)
                    print(f"[{index}] waiting {sleep_time}s")
                    await asyncio.sleep(sleep_time)
            token = None
        except Exception as e:
            if "429" in str(e):
                backoff_time = random.randint(15, 30)
                await asyncio.sleep(backoff_time)
            else:
                await asyncio.sleep(random.randint(4, 8))
            token = None

def start_connection_thread(channel_id, index, initial_token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_websocket_worker(channel_id, index, initial_token))

def fetch_token_job(index, tokens_list):
    tokens_list[index] = get_token()

if __name__ == "__main__":
    channel = input("Channel link or name: ").split("/")[-1]
    total_views = int(input("How many viewers to send: "))

    channel_id = get_channel_id(channel)
    if not channel_id:
        print("Channel not found.")
        exit(1)

    print(f"Fetching {total_views} tokens...")
    tokens = [None] * total_views
    threads = []
    for i in range(total_views):
        t = threading.Thread(target=fetch_token_job, args=(i, tokens))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    valid_tokens = [t for t in tokens if t]
    print(f"Successfully fetched {len(valid_tokens)} tokens. Starting viewers...")

    threads = []
    for i, token in enumerate(valid_tokens):
        t = threading.Thread(target=start_connection_thread, args=(channel_id, i, token))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
