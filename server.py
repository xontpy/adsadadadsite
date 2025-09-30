# Cache-busting comment to ensure Render picks up the change
import os
import asyncio
import multiprocessing
import psutil
import time
import requests
import sys
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from bot_logic import run_viewbot_logic
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

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
# A dictionary to hold the bot state for each user, keyed by user_id
# Each value will be a dictionary: {'pid': process.pid, 'status': bot_status}
user_bot_sessions = {}

# --- User Data Cache ---
user_cache = {}
CACHE_DURATION = 300  # Cache user data for 5 minutes

# --- Authentication Dependency ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        return None

    # Check cache first
    if token in user_cache and time.time() - user_cache[token].get('timestamp', 0) < CACHE_DURATION:
        return user_cache[token]['data']

    user_headers = {"Authorization": f"Bearer {token}"}
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers)
    if user_r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Discord token.")
    user_json = user_r.json()

    guild_member_r = requests.get(f'https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member', headers=user_headers)
    
    if guild_member_r.status_code == 200:
        guild_roles = guild_member_r.json().get('roles', [])
    else:
        guild_roles = []
        # Log the error but don't crash the request. Proceed with default permissions.
        print(f"Could not fetch member details from guild for user {user_json.get('id')}. Status: {guild_member_r.status_code}, Response: {guild_member_r.text}")

    user_json['roles'] = guild_roles
    
    default_permission = ROLE_PERMISSIONS.get("default")
    user_level = default_permission["level"]
    max_views = default_permission["max_views"]

    is_owner = OWNER_ROLE_ID in guild_roles if OWNER_ROLE_ID else False

    if is_owner:
        permission = ROLE_PERMISSIONS.get(OWNER_ROLE_ID, {})
        user_level = permission.get("level", user_level)
        max_views = permission.get("max_views", max_views)
    elif PRO_ROLE_ID and PRO_ROLE_ID in guild_roles:
        permission = ROLE_PERMISSIONS.get(PRO_ROLE_ID, {})
        user_level = permission.get("level", user_level)
        max_views = permission.get("max_views", max_views)
        
    user_json['level'] = user_level
    user_json['max_views'] = max_views
    user_json['is_owner'] = is_owner
    
    # Cache the processed data
    user_cache[token] = {
        'timestamp': time.time(),
        'data': user_json
    }
    
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
        print(f"Error during Discord token exchange: {e}")
        raise HTTPException(status_code=500, detail="Failed to authenticate with Discord.")

@app.get("/logout")
async def logout():
    return RedirectResponse(url="/")

@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        'id': user['id'], 'username': user['username'], 'avatar': user['avatar'],
        'max_views': user['max_views'], 'level': user['level'], 'is_owner': user['is_owner'],
    }

@app.post("/api/start")
async def start_bot(payload: StartBotPayload, user: dict = Depends(get_current_user)):
    print("--- /api/start endpoint hit ---") # DEBUG
    if not user:
        print("Authentication failed: No user object.") # DEBUG
        raise HTTPException(status_code=401, detail="Authentication required.")

    user_id = user['id']
    print(f"Request from user_id: {user_id}") # DEBUG

    if user_id in user_bot_sessions:
        session = user_bot_sessions[user_id]
        pid = session.get('pid')
        pid_exists = psutil.pid_exists(pid) if pid else False
        print(f"Found existing session for user {user_id}. PID: {pid}, PID exists: {pid_exists}") # DEBUG
        if pid_exists:
            print(f"Bot is already running for user {user_id}. Rejecting request.") # DEBUG
            raise HTTPException(status_code=400, detail="You already have a bot running.")
        else:
            print(f"Stale session found for user {user_id}. Cleaning up.") # DEBUG
            del user_bot_sessions[user_id]
    else:
        print(f"No existing session found for user {user_id}. Proceeding to start.") # DEBUG

    # Validate against user's max_views
    if payload.views > user.get('max_views', 0):
        raise HTTPException(status_code=403, detail=f"You are not allowed to start more than {user.get('max_views', 0)} views.")

    username = user.get("username", "UnknownUser")
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")

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
            'last_status': 'Initializing...'  # Store the last known status
        }

        return {"message": "Bot started successfully"}
    except Exception as e:
        # Clean up if something goes wrong
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
        # Non-blockingly get the latest message from the queue
        while not session['status_queue'].empty():
            session['last_status'] = session['status_queue'].get_nowait()
        
        return {"is_running": True, "status_line": session['last_status']}
    else:
        if user_id in user_bot_sessions:
            del user_bot_sessions[user_id]
        return {"is_running": False, "status_line": "Bot is not running."}@app.post("/api/save-proxies")
async def save_proxies(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in again.")
    if not user.get('is_owner'):
        raise HTTPException(status_code=403, detail="Permission denied. You do not have owner privileges.")

    body = await request.json()
    proxies = body.get("proxies")
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")

    try:
        with open(proxies_path, "w") as f:
            f.write(proxies)

        # Stop all running bot instances to apply new proxies
        for user_id, session in list(user_bot_sessions.items()):
            if psutil.pid_exists(session['pid']):
                try:
                    proc = psutil.Process(session['pid'])
                    session['stop_event'].set()
                    proc.join(timeout=5)
                    if proc.is_running():
                        proc.terminate()
                except psutil.NoSuchProcess:
                    pass # Already gone
            del user_bot_sessions[user_id]

        return {"message": "Proxies saved. All running bots have been stopped to apply changes."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save proxies: {e}')

@app.get("/api/get-proxies")
async def get_proxies(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in again.")
    if not user.get('is_owner'):
        raise HTTPException(status_code=403, detail="Permission denied. You do not have owner privileges.")
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

# The server must be started using run_server.py for multiprocessing to work correctly.
