import os
import logging
from dotenv import load_dotenv
from telegram_bot import main
import sqlite3

# Load environment variables from .env file if it exists
load_dotenv()

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
        level=logging.INFO
    )
    
    # Initialize database if needed
    try:
        # Ensure the instance directory exists
        os.makedirs('instance', exist_ok=True)
        
        # Check if the database file exists
        if not os.path.exists('instance/telegram_codes.db'):
            print("Telegram database not found. Initializing...")
            # Import and run the initialization script
            from init_telegram_db import init_telegram_db
            init_telegram_db()
    except Exception as e:
        print(f"Warning: Failed to initialize database: {e}")
        print("Will attempt to continue anyway...")
    
    # Check if token is set
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("Warning: TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("Please set it or update the token in telegram_bot.py")
    
    # Run the bot
    main()
