import os
import sqlite3
import logging

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def init_telegram_db():
    """Initialize the telegram database with required tables"""
    try:
        # Ensure the instance directory exists
        os.makedirs('instance', exist_ok=True)
        logger.info("Instance directory verified")
        
        # Connect to the database
        db_path = 'instance/telegram_codes.db'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        logger.info(f"Connected to database at {db_path}")
        
        # Create registration_codes table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS registration_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            is_used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create registered_users table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS registered_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            code TEXT NOT NULL,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (code) REFERENCES registration_codes(code)
        )
        ''')
        
        conn.commit()
        logger.info("Telegram database tables created successfully")
        
        # Check if tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        logger.info(f"Tables in database: {[table[0] for table in tables]}")
        
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error initializing telegram database: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Starting telegram database initialization...")
    success = init_telegram_db()
    if success:
        logger.info("Telegram database initialization completed successfully")
    else:
        logger.error("Telegram database initialization failed")
