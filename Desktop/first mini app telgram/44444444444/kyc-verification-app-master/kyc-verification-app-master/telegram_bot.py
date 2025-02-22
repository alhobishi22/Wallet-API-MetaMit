import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# الحصول على المتغيرات البيئية
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
WEB_APP_URL = os.getenv('WEB_APP_URL', 'https://localhost:5000')

# التأكد من أن الرابط يستخدم HTTPS
if not WEB_APP_URL.startswith('https://'):
    logger.warning("تحذير: يجب أن يبدأ رابط التطبيق بـ HTTPS")
    if WEB_APP_URL.startswith('http://'):
        WEB_APP_URL = WEB_APP_URL.replace('http://', 'https://', 1)

# إعدادات قاعدة البيانات
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://metabit_kyc_user:o8X1GbhjuT7fDGHrH8gfn0OiXRm9MykO@dpg-cul0mt23esus73b1r0a0-a.singapore-postgres.render.com/metabit_kyc')

def get_db_connection():
    """إنشاء اتصال بقاعدة البيانات"""
    try:
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        return psycopg2.connect(DATABASE_URL)
    except Exception as e:
        logger.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /start"""
    try:
        chat_id = update.effective_chat.id
        
        # إنشاء زر التوثيق
        keyboard = [
            [InlineKeyboardButton(
                "توثيق الحساب",
                web_app=WebAppInfo(url=WEB_APP_URL)
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "مرحباً بك في خدمة توثيق الحساب!\n"
            "اضغط على الزر أدناه لبدء عملية التوثيق.",
            reply_markup=reply_markup
        )
        logger.info(f"تم إرسال رسالة الترحيب للمستخدم {chat_id}")
            
    except Exception as e:
        logger.error(f"خطأ في معالجة أمر البدء: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى لاحقاً."
        )

# متغير عام للبوت
_bot_instance = None
_bot_running = False

def create_application():
    """إنشاء تطبيق البوت"""
    global _bot_instance, _bot_running
    try:
        if _bot_instance is not None:
            logger.warning("محاولة إنشاء نسخة جديدة من البوت بينما توجد نسخة نشطة")
            return _bot_instance

        if not TELEGRAM_BOT_TOKEN:
            logger.error("لم يتم تعيين TELEGRAM_BOT_TOKEN")
            return None

        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        _bot_instance = app
        _bot_running = True
        
        logger.info("تم إنشاء تطبيق البوت بنجاح")
        return app
    except Exception as e:
        logger.error(f"خطأ في إنشاء تطبيق البوت: {e}")
        return None

async def run_bot(app):
    """تشغيل البوت"""
    global _bot_running
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
        _bot_running = True
        logger.info("تم بدء تشغيل البوت بنجاح")
        
        # انتظار حتى يتم إيقاف البوت
        while _bot_running:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.warning("تم إلغاء عملية البوت")
                break
            
    except Exception as e:
        logger.error(f"خطأ في تشغيل البوت: {e}")
        _bot_running = False
    finally:
        _bot_running = False
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.error(f"خطأ في إيقاف البوت: {e}")

async def send_status_notification(chat_id: int, status: str, message: str = None):
    """إرسال إشعار بحالة الطلب للمستخدم"""
    try:
        if not chat_id:
            logger.error("لم يتم تحديد chat_id")
            return

        global _bot_instance
        if _bot_instance is None:
            logger.error("البوت غير مهيأ")
            return

        # تحضير نص الرسالة
        if status == 'approved':
            text = f"تم قبول طلبك! كود التسجيل الخاص بك هو: {message}"
        elif status == 'rejected':
            text = f"تم رفض طلبك للأسف. السبب: {message}"
        else:
            text = f"تم تحديث حالة طلبك إلى: {status}"
            if message:
                text += f"\nملاحظة: {message}"

        await _bot_instance.bot.send_message(chat_id=chat_id, text=text)
        logger.info(f"تم إرسال إشعار الحالة إلى {chat_id}")
        
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار الحالة: {e}")

async def shutdown_bot():
    """إيقاف تشغيل البوت بشكل آمن"""
    global _bot_instance, _bot_running
    if _bot_instance is not None:
        try:
            _bot_running = False
            if _bot_instance.updater and _bot_instance.updater.running:
                await _bot_instance.updater.stop()
            if _bot_instance.running:
                await _bot_instance.stop()
            await _bot_instance.shutdown()
            _bot_instance = None
            logger.info("تم إيقاف البوت بنجاح")
        except Exception as e:
            logger.error(f"خطأ في إيقاف البوت: {e}")
            # حتى في حالة الخطأ، نقوم بتنظيف المتغيرات
            _bot_instance = None
            _bot_running = False

# تشغيل البوت
if __name__ == "__main__":
    app = create_application()
    if app:
        asyncio.run(run_bot(app))
