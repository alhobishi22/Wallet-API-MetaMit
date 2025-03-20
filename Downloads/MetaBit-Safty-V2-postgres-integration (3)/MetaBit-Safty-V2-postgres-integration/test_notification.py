import asyncio
import os
from dotenv import load_dotenv
from telegram_bot import send_new_report_notification

# Load environment variables from .env file
load_dotenv()

async def test_notification():
    # Test report data
    report_data = {
        'scammer_name': 'اسم تجريبي للاختبار',
        'type': 'scam'
    }
    
    # Send notification
    print("Sending test notification...")
    result = await send_new_report_notification(report_data)
    
    if result:
        print("✅ Notification sent successfully!")
    else:
        print("❌ Failed to send notification.")

if __name__ == "__main__":
    asyncio.run(test_notification())
