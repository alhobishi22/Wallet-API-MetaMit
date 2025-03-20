import subprocess
import os
import sys
import time

def run_both_apps():
    print("Starting Flask app and Telegram bot...")
    
    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Command to run app.py
    app_cmd = [sys.executable, os.path.join(current_dir, "app.py")]
    
    # Command to run run_telegram_bot.py
    bot_cmd = [sys.executable, os.path.join(current_dir, "run_telegram_bot.py")]
    
    # Start both processes
    flask_process = subprocess.Popen(app_cmd, cwd=current_dir)
    print("Flask app started.")
    
    # Wait a bit to let Flask initialize
    time.sleep(2)
    
    telegram_process = subprocess.Popen(bot_cmd, cwd=current_dir)
    print("Telegram bot started.")
    
    print("Both applications are now running.")
    print("Press Ctrl+C to stop both applications.")
    
    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        # Handle Ctrl+C
        print("\nStopping applications...")
        flask_process.terminate()
        telegram_process.terminate()
        print("Applications stopped.")

if __name__ == "__main__":
    run_both_apps()
