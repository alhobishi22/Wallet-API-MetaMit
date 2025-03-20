import os
import logging
from dotenv import load_dotenv
from telegram_bot import main

# Load environment variables from .env file if it exists
load_dotenv()

if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
        level=logging.INFO
    )
    
    # Check if token is set
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print("Warning: TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("Please set it or update the token in telegram_bot.py")
    
    # Run the bot
    main()
