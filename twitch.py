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
from fake_useragent import UserAgent
import tls_client
import requests
from playwright.async_api import async_playwright

ua = UserAgent()

CLIENT_ID = "tioio8r22d5mjlhze4bo9lobd4g7vd"  # Twitch client ID

class TwitchViewerBot:
    def __init__(self, nb_of_threads, channel_name, status_updater=None, stop_event=None):
        self.nb_of_threads = int(nb_of_threads)
        self.channel_name = self.extract_channel_name(channel_name)
        self.request_count = 0
        self.processes = []
        self.thread_semaphore = Semaphore(int(nb_of_threads))
        self.active_threads = 0
        self.should_stop = False
        self.status = {
            'state': 'initialized',
            'message': 'Bot initialized',
            'proxy_count': 0,
            'proxy_loading_progress': 0,
            'startup_progress': 0
        }
        self.status_updater = status_updater
        self.stop_event = stop_event

        self._stats_lock = threading.Lock()
        self.open_websockets = 0
        self.websocket_attempts = 0
        self.live_streamer = False
        self.start_time = None
        self.stats_worker_thread = None
        self.messages_sent = 0

    def logger(self, message):
        if self.status_updater:
            try:
                self.status_updater.put({'log_line': str(message)})
            except:
                pass
        else:
            print(message)

    def get_channel_id(self):
        try:
            headers = {
                'Client-ID': CLIENT_ID,
                'Accept': 'application/vnd.twitchtv.v5+json',
                'User-Agent': ua.random,
            }

            response = requests.get(f'https://api.twitch.tv/kraken/channels/{self.channel_name}', headers=headers)
            if response.status_code == 200:
                data = response.json()
                self.channel_id = data.get("_id")
                return self.channel_id

            # Try Helix API
            token = self.get_oauth_token()
            if token:
                headers_helix = {
                    'Client-ID': CLIENT_ID,
                    'Authorization': 'Bearer ' + token,
                }
                response = requests.get(f'https://api.twitch.tv/helix/users?login={self.channel_name}', headers=headers_helix)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('data'):
                        self.channel_id = data['data'][0]['id']
                        return self.channel_id

            self.logger(f"Failed to get channel ID for: {self.channel_name}")
            return None

        except Exception as e:
            self.logger(f"Error getting channel ID: {e}")
            return None

    def get_oauth_token(self):
        # This would require Twitch app registration for proper OAuth
        # For demo purposes, using anonymous token
        try:
            response = requests.post('https://id.twitch.tv/oauth2/token', data={
                'client_id': CLIENT_ID,
                'client_secret': '',  # Would need actual secret
                'grant_type': 'client_credentials'
            })
            if response.status_code == 200:
                return response.json().get('access_token')
        except:
            pass
        return None

    def extract_channel_name(self, input_str):
        if "twitch.tv/" in input_str:
            parts = input_str.split("twitch.tv/")
            channel = parts[1].split("/")[0].split("?")[0]
            return channel.lower()
        return input_str.lower()

    def _stats_worker(self):
        print()
        print()
        os.system('cls' if os.name == 'nt' else 'clear')
        while not self.should_stop and (not self.stop_event or not self.stop_event.is_set()):
            try:
                with self._stats_lock:
                    if self.start_time:
                        elapsed = datetime.datetime.now() - self.start_time
                        duration_str = f"{int(elapsed.total_seconds())}s"
                    else:
                        duration_str = "0s"

                    open_ws = self.open_websockets
                    attempts = self.websocket_attempts
                    messages = self.messages_sent

                print("\033[2A", end="")
                print(f"\033[2K\r[x] Active Connections: \033[32m{open_ws}\033[0m | Attempts: \033[32m{attempts}\033[0m | Messages: \033[32m{messages}\033[0m | Duration: \033[32m{duration_str}\033[0m")
                sys.stdout.flush()

                if self.status_updater:
                    self.status_updater.put({
                        "current_viewers": open_ws,
                        "target_viewers": self.nb_of_threads,
                        "is_running": True,
                        "log_line": f"Active connections: {open_ws}, Attempts: {attempts}, Messages: {messages}, Duration: {duration_str}"
                    })

                time.sleep(1)
            except Exception as e:
                time.sleep(1)

    def update_status(self, state, message, proxy_count=None, proxy_loading_progress=None, startup_progress=None):
        self.status.update({
            'state': state,
            'message': message,
            **(({'proxy_count': proxy_count} if proxy_count is not None else {})),
            **(({'proxy_loading_progress': proxy_loading_progress} if proxy_loading_progress is not None else {})),
            **(({'startup_progress': startup_progress} if startup_progress is not None else {}))
        })

    def stop(self):
        self.should_stop = True

        for thread in self.processes:
            if thread.is_alive():
                thread.join(timeout=1)

        self.processes.clear()
        self.active_threads = 0

    def send_twitch_view(self):
        self.active_threads += 1
        with self._stats_lock:
            self.websocket_attempts += 1

        try:
            # Twitch IRC connection for chat (simulates viewer activity)
            # Note: This is a simplified example. Real Twitch bots require more complex implementation
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._irc_worker())
            except Exception as e:
                self.logger(f"IRC connection error: {e}")
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        except Exception as e:
            self.logger(f"Error in send_twitch_view: {e}")
        finally:
            self.active_threads -= 1
            self.thread_semaphore.release()

    async def _irc_worker(self):
        # Real Twitch viewer bot using Playwright browser automation
        try:
            self.logger("Launching browser viewer...")

            async with async_playwright() as p:
                browser = await p.firefox.launch(
                    headless=True
                )

                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 720},
                    user_agent=ua.random
                )

                page = await context.new_page()

                # Navigate to Twitch stream
                await page.goto(f"https://twitch.tv/{self.channel_name}", wait_until='domcontentloaded')

                # Wait for stream to be available
                try:
                    await page.wait_for_selector('video', timeout=15000)

                    # Mute the stream
                    await page.evaluate('''() => {
                        const video = document.querySelector('video');
                        if (video) {
                            video.muted = true;
                            video.volume = 0;
                        }
                    }''')

                    self.logger("Stream loaded and muted, watching...")

                    with self._stats_lock:
                        self.open_websockets += 1
                        self.messages_sent += 1

                    # Watch for extended period (5 minutes)
                    await asyncio.sleep(300)

                    self.logger("Viewer session completed")

                except Exception as e:
                    self.logger(f"Stream not available or failed to load: {e}")

                await browser.close()

        except Exception as e:
            self.logger(f"Browser viewer error: {e}")
        finally:
            with self._stats_lock:
                if self.open_websockets > 0:
                    self.open_websockets -= 1

    def main(self):
        print(f"Starting Twitch viewer bot for channel: {self.channel_name}")
        start = datetime.datetime.now()
        self.start_time = start

        self.processes = []
        self.live_streamer = True

        self.stats_worker_thread = Thread(target=self._stats_worker, daemon=True)
        self.stats_worker_thread.start()

        while not self.should_stop and (not self.stop_event or not self.stop_event.is_set()):
            for i in range(0, int(self.nb_of_threads)):
                acquired = self.thread_semaphore.acquire()
                if acquired:
                    threaded = Thread(target=self.send_twitch_view)
                    self.processes.append(threaded)
                    threaded.daemon = True
                    threaded.start()

                    time.sleep(0.35)

            if self.should_stop or (self.stop_event and self.stop_event.is_set()):
                for _ in range(self.nb_of_threads):
                    try:
                        self.thread_semaphore.release()
                    except ValueError:
                        pass
                break

        for t in self.processes:
            t.join()


# Web interface wrapper
def run_twitch_viewbot_logic(status_updater, stop_event, channel, viewers, duration_minutes, rapid=False):
    """
    Twitch viewer bot wrapper for web interface
    """
    def bot_logger(message):
        if callable(status_updater):
            try:
                if isinstance(message, dict):
                    status_updater.put(message)
                else:
                    status_updater.put({'log_line': str(message)})
            except:
                pass
        else:
            print(message)

    try:
        bot_logger("Initializing Twitch viewer bot...")

        bot = TwitchViewerBot(
            nb_of_threads=int(viewers),
            channel_name=channel,
            status_updater=status_updater,
            stop_event=stop_event
        )

        # Modify bot to check stop_event
        original_should_stop = bot.should_stop
        def check_stop():
            return original_should_stop or (hasattr(stop_event, 'is_set') and stop_event.is_set())
        bot.should_stop = property(check_stop)

        # Run the bot
        bot.main()

    except Exception as e:
        bot_logger(f"Critical error in Twitch bot: {e}")
    finally:
        bot_logger("Twitch bot process has stopped.")
        try:
            status_updater.put({"is_running": False, "current_viewers": 0})
        except:
            pass


if __name__ == "__main__":
    try:
        channel = input("Enter Twitch channel name or URL: ").strip()
        if not channel:
            print("Channel name is needed.")
            sys.exit(1)

        while True:
            try:
                threads = int(input("Enter number of viewers: ").strip())
                if threads > 0:
                    break
                else:
                    print("Number of threads must be bigger than 0")
            except ValueError:
                print("Please enter a valid number")

        bot = TwitchViewerBot(
            nb_of_threads=threads,
            channel_name=channel
        )
        bot.main()
    except KeyboardInterrupt:
        if 'bot' in locals():
            bot.stop()
        sys.exit(0)