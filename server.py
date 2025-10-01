import os
import asyncio
import multiprocessing
from multiprocessing import Process, Queue, Event
import psutil
import time
import requests
import sys
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from pydantic import BaseModel
from bot_logic import run_viewbot_logic
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from collections import deque

# --- Pydantic Models ---
class StartBotPayload(BaseModel):
    channel: str
    views: int
    duration: int

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
manager = multiprocessing.Manager()
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
def login_with_discord():
    return RedirectResponse(f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds.members.read")

@app.get("/callback")
async def callback(code: str):
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)
    token_data = {
        'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': DISCORD_REDIRECT_URI,
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

    if user_id in user_bot_sessions and psutil.pid_exists(user_bot_sessions[user_id].get('pid', -1)):
        raise HTTPException(status_code=400, detail="You already have a bot running.")

    if payload.views > user.get('max_views', 0):
        raise HTTPException(status_code=403, detail=f"You are not allowed to start more than {user.get('max_views', 0)} views.")

    try:
        duration_seconds = payload.duration * 60
        stop_event = multiprocessing.Event()
        status_dict = manager.dict({"running": True, "status_line": "Initializing..."})

        status_queue = manager.Queue()

        process = multiprocessing.Process(
            target=run_viewbot_logic, 
            args=(status_queue, stop_event, payload.channel, payload.views, payload.duration)
        )
        process.start()

        # Store the PID and status queue for the user
        user_bot_sessions[user_id] = {
            'pid': process.pid,
            'stop_event': stop_event,
            'status_queue': status_queue,
            'last_status': {"is_running": True, "status_line": "Initializing..."},
            'start_time': time.time(),
            'duration': payload.duration * 60,
            'target_viewers': payload.views
        }

        return {"message": "Bot started successfully"}
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

    if session and psutil.pid_exists(session['pid']):
        try:
            proc = psutil.Process(session['pid'])
            session['stop_event'].set()
            proc.join(timeout=10)
            if proc.is_running():
                proc.terminate()
                proc.join()
        except psutil.NoSuchProcess:
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
        return {"is_running": False, "status_line": "Not logged in."}

    user_id = user['id']
    session = user_bot_sessions.get(user_id)

    if session and psutil.pid_exists(session['pid']):
        while not session['status_queue'].empty():
            session['last_status'] = session['status_queue'].get_nowait()
        
        elapsed_time = time.time() - session['start_time']
        remaining_time = max(0, session['duration'] - elapsed_time)
        progress = (elapsed_time / session['duration']) * 100 if session['duration'] > 0 else 0
        
        mins, secs = divmod(remaining_time, 60)
        time_remaining_str = f"{int(mins):02d}:{int(secs):02d}"

        last_status = session.get('last_status', {})
        
        return {
            "is_running": True,
            "current_viewers": last_status.get('current_viewers', 0),
            "target_viewers": session.get('target_viewers', 0),
            "time_elapsed_str": time_remaining_str,
            "progress_percent": min(100, progress)
        }
    else:
        if user_id in user_bot_sessions:
            del user_bot_sessions[user_id]
        return {"is_running": False}

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
