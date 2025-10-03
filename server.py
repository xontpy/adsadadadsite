import os
# This environment variable MUST be set before any other imports that might
# use it, especially FastAPI, Starlette, and Authlib. It tells the OAuth
# library that it's okay to operate over plain HTTP, which is necessary
# for local development.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

import asyncio
import threading
import queue
import time
import requests
import sys
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel
from bot_logic import run_viewbot_logic
from twitch import run_twitch_viewbot_logic
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from collections import deque

# --- Pydantic Models ---
class StartBotPayload(BaseModel):
    channel: str
    views: int
    duration: int
    rapid: bool = False

class ProxiesSaveRequest(BaseModel):
    proxies: str

# --- Environment Variables ---
load_dotenv()
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
SECRET_KEY = os.getenv("SECRET_KEY")
OWNER_ROLE_ID = os.getenv("OWNER_ROLE_ID")
PRO_ROLE_ID = os.getenv("PRO_ROLE_ID")
ALGORITHM = os.getenv("ALGORITHM")

# --- FastAPI App ---
app = FastAPI()

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Role Permissions ---
ROLE_PERMISSIONS = {
    OWNER_ROLE_ID: {"max_views": 10000, "level": "owner"},
    PRO_ROLE_ID: {"max_views": 1000, "level": "pro"},
    "default": {"max_views": 100, "level": "user"},
}

# --- Bot State Management ---
user_bot_sessions = {}

# --- User Data Cache ---
user_cache = {}
CACHE_DURATION = 300

# --- Authentication Dependency ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        return None

    if token in user_cache and time.time() - user_cache[token].get('timestamp', 0) < CACHE_DURATION:
        return user_cache[token]['data']

    user_headers = {"Authorization": f"Bearer {token}"}
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers)
    if user_r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Discord token.")
    user_json = user_r.json()

    guild_member_r = requests.get(f'https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member', headers=user_headers)
    
    guild_roles = guild_member_r.json().get('roles', []) if guild_member_r.status_code == 200 else []

    user_json['roles'] = guild_roles
    
    default_permission = ROLE_PERMISSIONS.get("default")
    user_level = default_permission["level"]
    max_views = default_permission["max_views"]
    is_premium = False

    is_owner = OWNER_ROLE_ID in guild_roles if OWNER_ROLE_ID else False

    if is_owner:
        permission = ROLE_PERMISSIONS.get(OWNER_ROLE_ID, {})
        user_level = permission.get("level", user_level)
        max_views = permission.get("max_views", max_views)
        is_premium = True
    elif PRO_ROLE_ID and PRO_ROLE_ID in guild_roles:
        permission = ROLE_PERMISSIONS.get(PRO_ROLE_ID, {})
        user_level = permission.get("level", user_level)
        max_views = permission.get("max_views", max_views)
        is_premium = True
        
    user_json['level'] = user_level
    user_json['max_views'] = max_views
    user_json['is_owner'] = is_owner
    user_json['is_premium'] = is_premium
    
    user_cache[token] = {'timestamp': time.time(), 'data': user_json}
    
    return user_json

# --- API Endpoints ---

@app.get("/login")
def login_with_discord(request: Request):
    # Dynamically build redirect_uri based on current request
    port = f":{request.url.port}" if request.url.port and request.url.port != 80 and request.url.port != 443 else ""
    redirect_uri = f"{request.url.scheme}://{request.url.hostname}{port}/callback"
    return RedirectResponse(f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={redirect_uri}&response_type=code&scope=identify%20guilds.members.read")

@app.get("/callback")
async def callback(code: str, request: Request):
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)
    # Dynamically build redirect_uri based on current request
    port = f":{request.url.port}" if request.url.port and request.url.port != 80 and request.url.port != 443 else ""
    redirect_uri = f"{request.url.scheme}://{request.url.hostname}{port}/callback"
    token_data = {
        'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect_uri,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    try:
        token_r = requests.post('https://discord.com/api/oauth2/token', data=token_data, headers=headers)
        token_r.raise_for_status()
        discord_access_token = token_r.json()['access_token']
        return RedirectResponse(url=f"/#token={discord_access_token}")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with Discord: {e}")

@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        'id': user['id'], 'username': user['username'], 'avatar': user['avatar'],
        'max_views': user['max_views'], 'level': user['level'], 'is_owner': user['is_owner'],
        'is_premium': user.get('is_premium', False)
    }

@app.post("/api/start")
async def start_bot(payload: StartBotPayload, user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user_id = user['id']

    session = user_bot_sessions.get(user_id)
    if session and session['thread'].is_alive():
        raise HTTPException(status_code=400, detail="You already have a bot running.")

    if payload.views > user.get('max_views', 0):
        raise HTTPException(status_code=403, detail=f"You are not allowed to start more than {user.get('max_views', 0)} views.")

    try:
        stop_event = threading.Event()
        status_queue = queue.Queue()

        thread = threading.Thread(
            target=run_viewbot_logic,
            args=(status_queue, stop_event, payload.channel, payload.views, payload.duration, payload.rapid)
        )
        thread.start()

        user_bot_sessions[user_id] = {
            'thread': thread,
            'stop_event': stop_event,
            'status_queue': status_queue,
            'last_status': {"is_running": True, "status_line": "Initializing..."},
            'start_time': time.time(),
            'duration': payload.duration * 60,
            'target_viewers': payload.views,
            'logs': deque(maxlen=100)
        }

        return {"message": "Bot started successfully"}
    except Exception as e:
        if user_id in user_bot_sessions:
            del user_bot_sessions[user_id]
        raise HTTPException(status_code=500, detail=f"Server error: {e}")

@app.post("/api/start-twitch")
async def start_twitch_bot(payload: StartBotPayload, user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user_id = user['id']

    session = user_bot_sessions.get(user_id)
    if session and session['thread'].is_alive():
        raise HTTPException(status_code=400, detail="You already have a bot running.")

    if payload.views > user.get('max_views', 0):
        raise HTTPException(status_code=403, detail=f"You are not allowed to start more than {user.get('max_views', 0)} views.")

    try:
        stop_event = threading.Event()
        status_queue = queue.Queue()

        thread = threading.Thread(
            target=run_twitch_viewbot_logic,
            args=(status_queue, stop_event, payload.channel, payload.views, payload.duration)
        )
        thread.start()

        user_bot_sessions[user_id] = {
            'thread': thread,
            'stop_event': stop_event,
            'status_queue': status_queue,
            'last_status': {"is_running": True, "status_line": "Initializing..."},
            'start_time': time.time(),
            'duration': payload.duration * 60,
            'target_viewers': payload.views,
            'logs': deque(maxlen=100)
        }

        return {"message": "Twitch bot started successfully"}
    except Exception as e:
        if user_id in user_bot_sessions:
            del user_bot_sessions[user_id]
        raise HTTPException(status_code=500, detail=f"Server error: {e}")

@app.post("/api/stop")
async def stop_bot(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")

    user_id = user['id']
    session = user_bot_sessions.get(user_id)

    if session and session['thread'].is_alive():
        try:
            session['stop_event'].set()
            session['thread'].join(timeout=10)
        except Exception:
            pass
        finally:
            if user_id in user_bot_sessions:
                del user_bot_sessions[user_id]

        return {"message": "Bot stopped successfully"}
    else:
        if user_id in user_bot_sessions:
            del user_bot_sessions[user_id]
        raise HTTPException(status_code=400, detail="Bot is not running or has already stopped.")

@app.get("/api/status")
async def get_bot_status(user: dict = Depends(get_current_user)):
    if not user:
        return {"is_running": False, "logs": []}

    user_id = user['id']
    session = user_bot_sessions.get(user_id)

    if not session:
        return {"is_running": False, "logs": []}

    # Always drain the queue to get the latest messages
    while not session['status_queue'].empty():
        message = session['status_queue'].get_nowait()
        if isinstance(message, dict):
            if 'log_line' in message:
                session['logs'].append(message['log_line'])
            else:
                session['last_status'].update(message)
        else:
            # To be safe, handle non-dict messages as simple status lines
            session['last_status']['status_line'] = str(message)


    if session['thread'].is_alive():
        elapsed_time = time.time() - session['start_time']
        duration = session.get('duration', 0)
        if duration > 0:
            remaining_time = max(0, duration - elapsed_time)
            progress = (elapsed_time / duration) * 100
            mins, secs = divmod(remaining_time, 60)
            time_remaining_str = f"{int(mins):02d}:{int(secs):02d}"
        else:
            remaining_time = float('inf')
            progress = 0
            time_remaining_str = "Unlimited"

        last_status = session.get('last_status', {})

        total_duration_minutes = duration // 60 if duration > 0 else 0
        total_duration_str = f"{total_duration_minutes} min" if total_duration_minutes > 0 else "Unlimited"

        return {
            "is_running": True,
            "current_viewers": last_status.get('current_viewers', 0),
            "target_viewers": session.get('target_viewers', 0),
            "total_duration_str": total_duration_str,
            "time_remaining_str": time_remaining_str,
            "progress_percent": min(100, progress),
            "logs": list(session['logs'])
        }
    else:
        # The thread is dead, clean up the session and return final status
        if user_id in user_bot_sessions:
            del user_bot_sessions[user_id]

        return {"is_running": False, "logs": list(session['logs'])}

@app.post("/api/save-proxies")
async def save_proxies(payload: ProxiesSaveRequest, user: dict = Depends(get_current_user)):
    if not user or not user.get('is_owner'):
        raise HTTPException(status_code=403, detail="Permission denied.")

    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")
    try:
        with open(proxies_path, "w") as f:
            f.write(payload.proxies)
        return {"message": "Proxies saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save proxies: {e}')

@app.get("/api/get-proxies")
async def get_proxies(user: dict = Depends(get_current_user)):
    if not user or not user.get('is_owner'):
        raise HTTPException(status_code=403, detail="Permission denied.")
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")
    try:
        with open(proxies_path, "r") as f:
            proxies_content = f.read()
        return {"proxies": proxies_content}
    except FileNotFoundError:
        return {"proxies": ""}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to read proxies: {e}')

# --- Serve Frontend ---
app.mount("/", StaticFiles(directory=".", html=True), name="static")


# --- Environment Setup ---
# This is the crucial fix: By setting this environment variable, we are telling the OAuth
# library that it's acceptable to handle redirects over plain HTTP. This is safe and
# necessary for a local development environment that isn't running with a TLS certificate.
