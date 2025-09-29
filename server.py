import os
import asyncio
import multiprocessing
import time
import requests  # Use the standard requests library
import sys  # Import the sys module
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
import uvicorn
# REMOVE: from starlette.middleware.sessions import SessionMiddleware
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request
# --- Correctly Import the main bot function ---
from script import run_viewbot_logic


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

# --- Middleware -- REMOVED SessionMiddleware ---
# The SECRET_KEY is no longer needed for session management but might be used for other things.
# Keep it loaded but the app doesn't need to be configured with it here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all origins
    allow_credentials=True,
    allow_methods=["*"], # Allows all methods
    allow_headers=["*"], # Allows all headers
)


# --- Role Permissions ---
ROLE_PERMISSIONS = {
    OWNER_ROLE_ID: {"max_views": 10000, "level": "owner"},
    PRO_ROLE_ID: {"max_views": 1000, "level": "pro"},
    "default": {"max_views": 100, "level": "user"},
}

# --- Bot State ---
bot_process = None
bot_start_time = None
bot_duration = 0
bot_stop_event = None # Event to signal the bot to stop gracefully

# --- Authentication Dependency ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    if not token:
        return None

    user_headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Fetch user's identity
    user_r = requests.get('https://discord.com/api/users/@me', headers=user_headers)
    if user_r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Discord token. Please log in again.")
    user_json = user_r.json()

    # 2. Fetch user's roles in the specific guild
    guild_member_r = requests.get(f'https://discord.com/api/users/@me/guilds/{DISCORD_GUILD_ID}/member', headers=user_headers)
    guild_roles = guild_member_r.json().get('roles', []) if guild_member_r.status_code == 200 else []
    user_json['roles'] = guild_roles
    
    # 3. Determine user's permission level and add it to the user object
    default_permission = ROLE_PERMISSIONS.get("default", {"max_views": 100, "level": "user"})
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
    
    return user_json


# --- API Endpoints ---

@app.get("/login")
def login_with_discord():
    """Redirects the user to Discord for authorization."""
    return RedirectResponse(
        f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify%20guilds.members.read"
    )

@app.get("/callback")
async def callback(request: Request, code: str):
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)
    
    token_data = {
        'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code', 'code': code, 'redirect_uri': DISCORD_REDIRECT_URI,
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    try:
        token_r = requests.post('https://discord.com/api/oauth2/token', data=token_data, headers=headers)
        token_r.raise_for_status() # Raise an exception for bad status codes
        
        discord_access_token = token_r.json()['access_token']
        
        # Redirect to the main page with the token in the hash.
        response = RedirectResponse(url=f"/#token={discord_access_token}")
        return response
    except requests.exceptions.RequestException as e:
        print(f"Error during Discord token exchange: {e}")


@app.get("/logout")
async def logout(request: Request):
    # On the frontend, the token is cleared from localStorage.
    # This endpoint just needs to redirect back.
    return RedirectResponse(url="/")

@app.get("/api/me")
async def get_me(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # The user object from the dependency now contains all necessary info
    return {
        'id': user['id'], 'username': user['username'], 'avatar': user['avatar'],
        'max_views': user['max_views'], 'level': user['level'],
    }

@app.post("/api/start")
async def start_bot(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    # REMOVED: Permission check to allow any authenticated user to start the bot.
    # if user['level'] not in ['owner', 'pro']:
    #     raise HTTPException(status_code=403, detail="You do not have permission to start the bot.")

    global bot_process, bot_stop_event

    if bot_process and bot_process.is_alive():
        raise HTTPException(status_code=400, detail="Bot is already running")

    data = await request.json()
    channel = data.get("channel")
    num_viewers = data.get("views")
    duration_minutes = data.get("duration") # Duration from frontend is in minutes
    username = user.get("username", "UnknownUser") # Get username from user object
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")


    if not all([channel, num_viewers, duration_minutes]):
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        # Convert duration from minutes to seconds
        duration_seconds = duration_minutes * 60

        # Create a stop event for graceful shutdown
        bot_stop_event = multiprocessing.Event()
        
        # Update the Process call to include all required arguments
        bot_process = multiprocessing.Process(
            target=run_viewbot_logic, 
            args=(channel, num_viewers, duration_seconds, bot_stop_event, username, proxies_path)
        )
        bot_process.start()
        return {"message": "Bot started successfully"}
    except Exception as e:
        print(f"Error starting bot: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {e}")


@app.post("/api/stop")
async def stop_bot(user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    # REMOVED: Permission check to allow any authenticated user to stop the bot.
    # if user['level'] not in ['owner', 'pro']:
    #     raise HTTPException(status_code=403, detail="You do not have permission to stop the bot.")
        
    global bot_process, bot_stop_event

    if bot_process and bot_process.is_alive():
        if bot_stop_event:
            bot_stop_event.set() # Signal the process to stop
        
        bot_process.join(timeout=10) # Wait for a graceful shutdown

        if bot_process.is_alive():
            bot_process.terminate() # Force terminate if it doesn't stop
            bot_process.join()

        bot_process = None
        bot_stop_event = None
        return {"message": "Bot stopped successfully"}
    else:
        raise HTTPException(status_code=400, detail="Bot is not running")

@app.post("/api/save-proxies")
async def save_proxies(request: Request, user: dict = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=403, detail="Unauthorized")
    # REMOVED: Permission check to allow any authenticated user to save proxies.
    # if not user or user.get('level') != 'owner':
    #     raise HTTPException(status_code=403, detail="Unauthorized")
    
    body = await request.json()
    proxies = body.get("proxies")

    # Define the path to proxies.txt in the same directory as the script
    proxies_path = os.path.join(os.path.dirname(__file__), "proxies.txt")
    
    try:
        with open(proxies_path, "w") as f:
            f.write(proxies)
        return {"message": f"Proxies saved successfully to {proxies_path}."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to save proxies: {e}')


@app.get("/api/status")
async def get_bot_status(user: dict = Depends(get_current_user)):
    global bot_process, bot_start_time, bot_duration

    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if bot_process and bot_process.is_alive():
        status = "running"
        elapsed_time = time.time() - bot_start_time
        time_left = bot_duration - elapsed_time
        if time_left < 0:
            time_left = 0
        
        # Check if the process has finished on its own
        if not bot_process.is_alive():
            return {"status": "Idle", "message": "Bot has finished its run.", "time_left": "N/A"}

        return {
            "status": "Running",
            "message": "Bot is currently active.",
            "time_left": f"{int(time_left // 60)}m {int(time_left % 60)}s"
        }
    return {"status": "Idle", "message": "Bot is not running.", "time_left": "N/A"}


# --- Serve Frontend ---
# This single mount handles all static files (HTML, CSS, JS).
# The `html=True` argument tells FastAPI to automatically serve `index.html` for the root path (`/`).
# This replaces the previous, more complex setup.
app.mount("/", StaticFiles(directory=".", html=True), name="static")


# The if __name__ == "__main__" block has been removed.
# The server must be started using run_server.py for multiprocessing to work correctly.
