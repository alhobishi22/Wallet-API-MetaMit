import os
import sys
import asyncio
from dotenv import load_dotenv
from telegram_notifier import send_notification_to_user

# تحميل متغيرات البيئة
load_dotenv()

async def send_direct_notification():
    """
    برنامج لإرسال إشعارات مباشرة للمستخدمين للاختبار
    """
    if len(sys.argv) < 3:
        print("Usage: python direct_notification.py <chat_id> <message>")
        return
    
    chat_id = sys.argv[1]
    message = sys.argv[2]
    
    print(f"محاولة إرسال إشعار إلى المستخدم {chat_id}: {message}")
    
    success = await send_notification_to_user(chat_id, message)
    
    if success:
        print("✅ تم إرسال الإشعار بنجاح")
    else:
        print("❌ فشل في إرسال الإشعار")

if __name__ == "__main__":
    asyncio.run(send_direct_notification())
