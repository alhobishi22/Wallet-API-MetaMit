from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import asyncio
import nest_asyncio
import logging
import os
import tempfile

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تمكين تداخل event loops
nest_asyncio.apply()

TELEGRAM_BOT_TOKEN = "8068331897:AAHa8V519tgNs7vFSEs9OdAyykx8yWH-Xx0"
WEB_APP_URL = "https://kyc-verification-app-teon.onrender.com"  # تم تحديث الرابط
_bot_app = None  # متغير عام للتطبيق
_lock_file = os.path.join(tempfile.gettempdir(), 'telegram_bot.lock')

def set_webapp_url(url: str):
    """تحديث رابط التطبيق"""
    global WEB_APP_URL
    WEB_APP_URL = url

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج الأخطاء الغير متوقعة"""
    logger.error(f"حدث خطأ غير متوقع: {context.error}")
    if update:
        await update.message.reply_text(
            "عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى لاحقاً."
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEB_APP_URL:
        await update.message.reply_text(
            "عذراً، التطبيق غير متاح حالياً. الرجاء المحاولة لاحقاً."
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            "توثيق الحساب",
            web_app=WebAppInfo(url=WEB_APP_URL)
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "مرحباً بك في خدمة توثيق الحساب!\nاضغط على الزر أدناه لبدء عملية التوثيق.",
        reply_markup=reply_markup
    )

async def send_status_notification(chat_id: int, request_id: str, status: str, custom_message: str = None):
    """إرسال إشعار بحالة الطلب للمستخدم"""
    global _bot_app
    
    try:
        if _bot_app is None:
            _bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        if custom_message:
            message = f"{custom_message}\nرقم الطلب: {request_id}"
        else:
            status_messages = {
                'قيد المراجعة': 'تم استلام طلبك وهو قيد المراجعة',
                'مقبول': 'تم قبول طلب التوثيق الخاص بك!',
                'مرفوض': 'عذراً، تم رفض طلب التوثيق.'
            }
            message = f"{status_messages[status]}\nرقم الطلب: {request_id}"
        
        async with _bot_app:
            await _bot_app.bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        logger.error(f"خطأ في إرسال الإشعار: {e}")

def is_bot_running():
    """التحقق مما إذا كان البوت قيد التشغيل"""
    try:
        if os.path.exists(_lock_file):
            # التحقق من صحة ملف القفل
            with open(_lock_file, 'r') as f:
                pid = int(f.read().strip())
                try:
                    # التحقق مما إذا كانت العملية لا تزال نشطة
                    os.kill(pid, 0)
                    return True
                except OSError:
                    # العملية غير موجودة
                    os.remove(_lock_file)
        return False
    except Exception as e:
        logger.error(f"خطأ في التحقق من حالة البوت: {e}")
        return False

def create_lock_file():
    """إنشاء ملف قفل للبوت"""
    try:
        with open(_lock_file, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        logger.error(f"خطأ في إنشاء ملف القفل: {e}")

def remove_lock_file():
    """إزالة ملف قفل البوت"""
    try:
        if os.path.exists(_lock_file):
            os.remove(_lock_file)
    except Exception as e:
        logger.error(f"خطأ في إزالة ملف القفل: {e}")

def run_bot():
    """تشغيل بوت التلجرام"""
    global _bot_app
    
    try:
        # التحقق من عدم وجود نسخة أخرى من البوت
        if is_bot_running():
            logger.error("البوت قيد التشغيل بالفعل!")
            return
        
        # إنشاء ملف القفل
        create_lock_file()
        
        # إنشاء event loop جديد
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # إنشاء تطبيق البوت إذا لم يكن موجوداً
        if _bot_app is None:
            _bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
            
            # إضافة الأوامر
            _bot_app.add_handler(CommandHandler("start", start))
            
            # إضافة معالج الأخطاء
            _bot_app.add_error_handler(error_handler)
        
        # تشغيل البوت
        _bot_app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        logger.error(f"خطأ في تشغيل البوت: {e}")
        raise
    finally:
        # إزالة ملف القفل عند الإغلاق
        remove_lock_file()
