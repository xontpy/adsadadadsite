import os
import sys
import uvicorn
import multiprocessing

# Add the script's directory to the Python path to resolve module not found errors.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from server import app

if __name__ == "__main__":
    # This is essential for multiprocessing to work correctly on Windows
    # when the application is frozen to a standalone executable.
    multiprocessing.freeze_support()
    
    print("Starting server... Open http://127.0.0.1:8000 in your browser.")
    # We run the server programmatically here.
    # The reload=True option is great for development but can cause issues
    # with multiprocessing. Let's run it without auto-reloading for now.
    uvicorn.run(app, host="0.0.0.0", port=8000)
