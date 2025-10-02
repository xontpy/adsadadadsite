import sys
import time
import random
import datetime
import threading
import asyncio
import websockets
import json
import os
from threading import Thread
from threading import Semaphore
import tls_client

# This function is required by the web server to send logs and status updates to the UI.
def bot_logger(status_updater, message):
    """A simple logger that sends messages to the web UI."""
    try:
        if isinstance(message, dict):
            status_updater.put(message)
        else:
            log_message = str(message)
            # Avoid logging sensitive details
            if "proxy" not in log_message and "token" not in log_message:
                status_updater.put({'log_line': log_message})
    except Exception:
        # Fallback to console if UI logging fails
        sys.stdout.write(f"\r[UI_LOG_FAIL] {message}")
        sys.stdout.flush()

CLIENT_TOKEN = "e1393935a959b4020a4491574f6490129f678acdaa92760471263db43487f823"

class ViewerBot:
    def __init__(self, nb_of_threads, channel_name, status_updater, stop_event):
        self.nb_of_threads = int(nb_of_threads)
        self.channel_name = self.extract_channel_name(channel_name)
        self.request_count = 0
        self.processes = []
        self.channel_url = "https://kick.com/" + self.channel_name
        self.thread_semaphore = Semaphore(int(nb_of_threads))
        self.active_threads = 0
        self.should_stop = stop_event.is_set
        self.request_per_second = 0
        self.requests_in_current_second = 0
        self.last_request_time = time.time()
        self.status = {
            'state': 'initialized',
            'message': 'Bot initialized',
            'proxy_count': 0,
            'proxy_loading_progress': 0,
            'startup_progress': 0
        }
        self.stream_url_cache = None
        self.stream_url_last_updated = 0
        self.stream_url_lock = threading.Lock()
        self.stream_url_cache_duration = 0.5
        self.channel_id = None

        self._stats_lock = threading.Lock()
        self.open_websockets = 0
        self.websocket_attempts = 0
        self.live_streamer = False
        self.start_time = None
        self.stats_worker_thread = None
        self.pings_sent = 0
        self.heartbeats_sent = 0
        self.status_updater = status_updater
        self.logger = lambda msg: bot_logger(status_updater, msg)

    def get_channel_id(self):
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
                response = s.get(f'https://kick.com/api/v2/channels/{self.channel_name}')
                if response.status_code == 200:
                    data = response.json()
                    self.channel_id = data.get("id")
                    return self.channel_id
            except Exception as e:
                pass

            try:
                response = s.get(f'https://kick.com/api/v1/channels/{self.channel_name}')
                if response.status_code == 200:
                    data = response.json()
                    self.channel_id = data.get("id")
                    return self.channel_id
            except Exception as e:
                pass

            try:
                response = s.get(f'https://kick.com/{self.channel_name}')
                if response.status_code == 200:
                    import re
                    patterns = [
                        r'"id":(\d+).*?"slug":"' + re.escape(self.channel_name) + r'"',
                        r'"channel_id":(\d+)',
                        r'channelId["\']:\s*(\d+)',
                        r'channel.*?id["\']:\s*(\d+)'
                    ]

                    for pattern in patterns:
                        match = re.search(pattern, response.text, re.IGNORECASE)
                        if match:
                            self.channel_id = int(match.group(1))
                            return self.channel_id
            except Exception as e:
                pass

            self.logger(f"All methods failed to get channel ID for: {self.channel_name}")
            return None

        except Exception as e:
            self.logger(f"Error getting channel ID: {e}")
            return None

    def get_websocket_token(self):
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
                session_resp = s.get("https://kick.com")
                s.headers["X-CLIENT-TOKEN"] = CLIENT_TOKEN
                response = s.get('https://websockets.kick.com/viewer/v1/token')

                if response.status_code == 200:
                    data = response.json()
                    token = data.get("data", {}).get("token")
                    if token:
                        return token
            except Exception as e:
                pass

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
                    continue

            self.logger("Failed to get WebSocket token from all endpoints")
            return None

        except Exception as e:
            self.logger(f"Error getting WebSocket token: {e}")
            return None

    def extract_channel_name(self, input_str):
        if "kick.com/" in input_str:
            parts = input_str.split("kick.com/")
            channel = parts[1].split("/")[0].split("?")[0]
            return channel.lower()
        return input_str.lower()

    def stop(self):
        self.should_stop = lambda: True

        for thread in self.processes:
            if thread.is_alive():
                thread.join(timeout=1)

        self.processes.clear()
        self.active_threads = 0

    def open_url(self):
        self.send_websocket_view()

    def send_websocket_view(self):
        self.active_threads += 1
        with self._stats_lock:
            self.websocket_attempts += 1
        try:
            token = self.get_websocket_token()
            if not token:
                return

            if not self.channel_id:
                self.channel_id = self.get_channel_id()
                if not self.channel_id:
                    return

            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._websocket_worker(token))
            except Exception as e:
                pass
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        except Exception as e:
            pass
        finally:
            self.active_threads -= 1
            self.thread_semaphore.release()

    async def _websocket_worker(self, token):
        connection_opened = False
        try:
            ws_url = f"wss://websockets.kick.com/viewer/v1/connect?token={token}"

            async with websockets.connect(ws_url) as websocket:
                with self._stats_lock:
                    self.open_websockets += 1
                connection_opened = True

                self.logger({"current_viewers": self.open_websockets, "target_viewers": self.nb_of_threads})

                handshake_msg = {
                    "type": "channel_handshake",
                    "data": {
                        "message": {"channelId": self.channel_id}
                    }
                }
                await websocket.send(json.dumps(handshake_msg))
                with self._stats_lock:
                    self.heartbeats_sent += 1

                ping_count = 0
                while not self.should_stop() and ping_count < 10:
                    ping_count += 1

                    ping_msg = {"type": "ping"}
                    await websocket.send(json.dumps(ping_msg))
                    with self._stats_lock:
                        self.pings_sent += 1
                    self.request_count += 1

                    sleep_time = 12 + random.randint(1, 5)
                    await asyncio.sleep(sleep_time)

        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            pass
        finally:
            if connection_opened:
                with self._stats_lock:
                    if self.open_websockets > 0:
                        self.open_websockets -= 1

# This is the main entry point called by the web server.
def run_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes, rapid=False):
    logger = lambda msg: bot_logger(status_updater, msg)

    if not channel or not channel.strip():
        logger("Channel name is required.")
        return

    bot = ViewerBot(viewers, channel, status_updater, stop_event)
    bot.start_time = datetime.datetime.now()

    bot.channel_id = bot.get_channel_id()
    bot.processes = []
    bot.live_streamer = True

    try:
        while True:
            for i in range(0, int(bot.nb_of_threads)):
                acquired = bot.thread_semaphore.acquire()
                if acquired:
                    threaded = Thread(target=bot.open_url)
                    bot.processes.append(threaded)
                    threaded.daemon = True
                    threaded.start()

                    time.sleep(0.35)

            if stop_event.is_set():
                for _ in range(bot.nb_of_threads):
                    try:
                        bot.thread_semaphore.release()
                    except ValueError:
                        pass
                break

        for t in bot.processes:
            t.join()

    except KeyboardInterrupt:
        bot.stop()
