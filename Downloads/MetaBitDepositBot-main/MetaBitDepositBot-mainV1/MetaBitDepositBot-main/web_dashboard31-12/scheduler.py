import os
import time
import psycopg2
from psycopg2.extras import DictCursor
from datetime import datetime, timezone
import asyncio
from telegram import Bot
import logging

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('scheduler')

# تكوين قاعدة البيانات
DATABASE_URL = "postgres://alhubaishi:jAtNbIdExraRUo1ZosQ1f0EEGz3fMZWt@dpg-csserj9u0jms73ea9gmg-a.singapore-postgres.render.com/meta_bit_database"

# تكوين البوت
BOT_TOKEN = "8068331897:AAHa8V519tgNs7vFSEs9OdAyykx8yWH-Xx0"
bot = Bot(token=BOT_TOKEN)

def get_db_connection():
    """إنشاء اتصال بقاعدة البيانات"""
    return psycopg2.connect(DATABASE_URL, sslmode='require')

async def send_message(user_id: int, message: str, files=None):
    """إرسال رسالة عبر تيليجرام"""
    try:
        # إرسال النص
        await bot.send_message(chat_id=user_id, text=message)
        
        # إرسال الملفات إذا وجدت
        if files:
            for file_path in files:
                if os.path.exists(file_path):
                    # تحديد نوع الملف
                    if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                        with open(file_path, 'rb') as f:
                            await bot.send_photo(chat_id=user_id, photo=f)
                    else:
                        with open(file_path, 'rb') as f:
                            await bot.send_document(chat_id=user_id, document=f)
        
        return True
    except Exception as e:
        logger.error(f"Error sending message to {user_id}: {e}")
        return False

async def process_scheduled_messages():
    """معالجة الرسائل المجدولة"""
    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=DictCursor)
            
            # البحث عن الرسائل المجدولة التي حان وقت إرسالها
            cur.execute("""
                SELECT id, user_ids, message_text, files
                FROM scheduled_messages
                WHERE status = 'pending'
                AND scheduled_time <= NOW()
                ORDER BY scheduled_time
            """)
            
            messages = cur.fetchall()
            
            for msg in messages:
                logger.info(f"Processing scheduled message {msg['id']}")
                success_count = 0
                failed_users = []
                
                # إرسال الرسالة لكل مستخدم
                for user_id in msg['user_ids']:
                    try:
                        success = await send_message(
                            user_id=user_id,
                            message=msg['message_text'],
                            files=msg['files']
                        )
                        
                        if success:
                            success_count += 1
                        else:
                            failed_users.append(user_id)
                            
                    except Exception as e:
                        logger.error(f"Error processing user {user_id} for message {msg['id']}: {e}")
                        failed_users.append(user_id)
                
                # تحديث حالة الرسالة
                status = 'completed' if not failed_users else 'partial'
                error_message = f"Failed users: {failed_users}" if failed_users else None
                
                cur.execute("""
                    UPDATE scheduled_messages
                    SET status = %s,
                        sent_at = NOW(),
                        error_message = %s
                    WHERE id = %s
                """, (status, error_message, msg['id']))
                
                # حذف الملفات المؤقتة
                if msg['files']:
                    for file_path in msg['files']:
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                        except Exception as e:
                            logger.error(f"Error deleting file {file_path}: {e}")
                
                conn.commit()
                
                logger.info(f"Message {msg['id']} processed: {success_count} successful, {len(failed_users)} failed")
            
            cur.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error in process_scheduled_messages: {e}")
        
        # انتظار 60 ثانية قبل التحقق مرة أخرى
        await asyncio.sleep(60)

async def main():
    """الدالة الرئيسية"""
    logger.info("Starting message scheduler")
    await process_scheduled_messages()

if __name__ == "__main__":
    asyncio.run(main())