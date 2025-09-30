# Cache-busting comment to ensure Render picks up the change
import os
import asyncio
import multiprocessing
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

# --- Bot State ---
bot_process = None
bot_stop_event = None

# --- Shared Status for UI ---
manager = multiprocessing.Manager()
bot_status = manager.dict()
bot_status["running"] = False
bot_status["status_line"] = ""

# --- Authentication Dependency ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        return None
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

    if OWNER_ROLE_ID and OWNER_ROLE_ID in guild_roles:
        permission = ROLE_PERMISSIONS.get(OWNER_ROLE_ID, {})
        user_level = permission.get("level", user_level)
        max_views = permission.get("max_views", max_views)
    elif PRO_ROLE_ID and PRO_ROLE_ID in guild_roles:
        permission = ROLE_PERMISSIONS.get(PRO_ROLE_ID, {})
        user_level = permission.get("level", user_level)
        max_views = permission.get("max_views", max_views)
        
    user_json['level'] = user_level
    user_json['max_views'] = max_views
    user_json['is_owner'] = OWNER_ROLE_ID in guild_roles if OWNER_ROLE_ID else False
    
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
async def start_bot(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    
    global bot_process, bot_stop_event
    if bot_process and bot_process.is_alive():
        raise HTTPException(status_code=400, detail="Bot is already running")

    data = await request.json()
    channel = data.get("channel")
    num_viewers = data.get("num_viewers")
    duration_minutes = data.get("duration_minutes")
    username = user.get("username", "UnknownUser")
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")

    if not all([channel, num_viewers, duration_minutes]):
        raise HTTPException(status_code=400, detail="Missing required parameters.")

    try:
        duration_seconds = duration_minutes * 60
        bot_stop_event = multiprocessing.Event()
        bot_status["running"] = True
        bot_status["status_line"] = "Initializing..."

        bot_process = multiprocessing.Process(
            target=run_viewbot_logic, 
            args=(channel, num_viewers, duration_seconds, bot_stop_event, username, proxies_path, bot_status)
        )
        bot_process.start()
        return {"message": "Bot started successfully"}
    except Exception as e:
        bot_status["running"] = False
        bot_status["status_line"] = f"Error: {e}"
        raise HTTPException(status_code=500, detail=f"Server error: {e}")

@app.post("/api/stop")
async def stop_bot(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
        
    global bot_process, bot_stop_event
    if bot_process and bot_process.is_alive():
        if bot_stop_event:
            bot_stop_event.set()
        bot_process.join(timeout=10)
        if bot_process.is_alive():
            bot_process.terminate()
            bot_process.join()
        bot_process = None
        bot_stop_event = None
        bot_status["running"] = False
        bot_status["status_line"] = "Bot stopped."
        return {"message": "Bot stopped successfully"}
    else:
        # If the bot is not running, ensure the status is correct
        bot_status["running"] = False
        bot_status["status_line"] = "Bot is not running."
        raise HTTPException(status_code=400, detail="Bot is not running")

@app.get("/api/status")
async def get_bot_status():
    status_dict = dict(bot_status)
    # Ensure the key 'is_running' is what the frontend expects
    status_dict['is_running'] = status_dict.get('running', False)
    return status_dict

@app.post("/api/save-proxies")
async def save_proxies(request: Request, user: dict = Depends(get_current_user)):
    if not user or not user.get('is_owner'):
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    global bot_process, bot_stop_event
    body = await request.json()
    proxies = body.get("proxies")
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")
    
    try:
        with open(proxies_path, "w") as f:
            f.write(proxies)
        
        message = "Proxies saved successfully."
        # If bot is running, stop it to apply new proxies on next run
        if bot_process and bot_process.is_alive():
            if bot_stop_event:
                bot_stop_event.set()
            bot_process.join(timeout=15)
            if bot_process.is_alive():
                bot_process.terminate()
                bot_process.join()
            
            bot_process = None
            bot_stop_event = None
            bot_status["running"] = False
            bot_status["status_line"] = "Bot stopped to apply new proxies. Please restart."
            message = "Proxies saved. Bot stopped to apply changes, please restart."

        return {"message": message}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save proxies: {e}')

@app.get("/api/get-proxies")
async def get_proxies(user: dict = Depends(get_current_user)):
    if not user or not user.get('is_owner'):
        raise HTTPException(status_code=403, detail="Unauthorized")
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
