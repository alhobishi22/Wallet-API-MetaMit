import os
import logging
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import string
import random
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
def setup_db():
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registration_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        is_used INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registered_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        code TEXT NOT NULL,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

# Generate a random code that can include both Arabic and English characters
def generate_random_code(length=8):
    # English alphanumeric characters
    english_chars = string.ascii_letters + string.digits
    # Arabic characters (basic set)
    arabic_chars = 'أبتثجحخدذرزسشصضطظعغفقكلمنهوي'
    # Combined character set
    all_chars = english_chars + arabic_chars
    
    # Generate a code with a mix of characters
    return ''.join(random.choice(all_chars) for _ in range(length))

# Clean and normalize code for comparison
def normalize_code(code):
    # Remove whitespace and normalize
    return re.sub(r'\s+', '', code).strip().lower()

# Verify registration code
def verify_code(code):
    if not code:
        return False
        
    normalized_code = normalize_code(code)
    
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    
    # Get all unused codes
    cursor.execute("SELECT code FROM registration_codes WHERE is_used = 0")
    all_codes = cursor.fetchall()
    
    # Check if the normalized input matches any normalized code
    for db_code in all_codes:
        if normalized_code == normalize_code(db_code[0]):
            conn.close()
            return db_code[0]  # Return the actual code from DB
    
    conn.close()
    return None

# Mark code as used
def mark_code_used(code, user_id, username):
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE registration_codes SET is_used = 1 WHERE code = ?", (code,))
    cursor.execute("INSERT INTO registered_users (user_id, username, code) VALUES (?, ?, ?)", 
                  (user_id, username, code))
    conn.commit()
    conn.close()

# Check if user is registered
def is_user_registered(user_id):
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM registered_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Get all registered users
def get_all_registered_users():
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM registered_users")
    users = cursor.fetchall()
    conn.close()
    return [user[0] for user in users]

# Send notification to a specific user
async def send_notification_to_user(bot, user_id, message, keyboard=None):
    try:
        # إرسال الرسالة بدون علامات تنسيق نصي
        if keyboard:
            await bot.send_message(
                chat_id=user_id,
                text=message,
                reply_markup=keyboard,
                parse_mode=None  # تعطيل وضع التنسيق
            )
        else:
            await bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=None  # تعطيل وضع التنسيق
            )
        return True
    except Exception as e:
        logging.error(f"Error sending notification to user {user_id}: {e}")
        return False

# Send notification to all registered users
async def send_notification_to_all_users(message, include_button=True):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("TELEGRAM_BOT_TOKEN not set. Cannot send notifications.")
        return False
    
    try:
        application = Application.builder().token(token).build()
        bot = application.bot
        
        # Get all registered users
        users = get_all_registered_users()
        
        # Create keyboard if needed
        keyboard = None
        if include_button:
            # تأكد من أن عنوان URL صحيح وكامل
            webapp_url = "https://kyc-metabit-test.onrender.com/"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    text="فتح تطبيق MetaBit Safety",
                    web_app=WebAppInfo(url=webapp_url)
                )]
            ])
        
        # Send notification to each user
        success_count = 0
        for user_id in users:
            success = await send_notification_to_user(bot, user_id, message, keyboard)
            if success:
                success_count += 1
        
        logging.info(f"Notification sent to {success_count}/{len(users)} users")
        return success_count > 0
    except Exception as e:
        logging.error(f"Error sending notifications: {e}")
        return False

# Send notification about new report
async def send_new_report_notification(report_data):
    """
    Send notification about a new report to all registered users
    
    Args:
        report_data: Dictionary containing report information
    
    Returns:
        bool: True if notification was sent successfully
    """
    # Create message with report details
    scammer_name = report_data.get('scammer_name', 'غير محدد').split('|')[0]
    report_type = report_data.get('type', 'غير محدد')
    
    # Translate report type to Arabic
    report_type_ar = {
        'scam': 'نصب واحتيال',
        'debt': 'مديونية',
        'other': 'آخر'
    }.get(report_type, report_type)
    
    message = f"⚠️ تنبيه: تم إضافة بلاغ جديد ⚠️\n\n"
    message += f"📌 نوع البلاغ: {report_type_ar}\n"
    message += f"👤 اسم المبلغ عنه: {scammer_name}\n"
    message += f"\nلمزيد من التفاصيل، يرجى فتح التطبيق."
    
    # Send notification to all registered users
    return await send_notification_to_all_users(message)

# Command handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    
    # Check if user is already registered
    if is_user_registered(user.id):
        # Create a button that opens the web app
        webapp_url = "https://kyc-metabit-test.onrender.com/"
        keyboard = [
            [InlineKeyboardButton(
                text="فتح تطبيق MetaBit Safety",
                web_app=WebAppInfo(url=webapp_url)
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_html(
            f"مرحباً {user.mention_html()}! أنت مسجل بالفعل في نظام MetaBit Safety.\n"
            f"يمكنك الآن دخول نظام الحمايه.",
            reply_markup=reply_markup
        )
    else:
        # Ask for registration code
        await update.message.reply_html(
            f"مرحباً {user.mention_html()}! للوصول إلى تطبيق MetaBit Safety،\n"
            f"يرجى إدخال كود التسجيل الخاص بك."
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(
        "هذا البوت يتيح لك الوصول إلى تطبيق MetaBit Safety.\n"
        "استخدم الأوامر التالية:\n"
        "/start - لبدء استخدام البوت\n"
        "/help - لعرض هذه الرسالة المساعدة\n"
        "/open - لفتح التطبيق المصغر (متاح فقط للمستخدمين المسجلين)"
    )

async def open_app(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Open the mini app if user is registered."""
    user = update.effective_user
    
    if is_user_registered(user.id):
        webapp_url = "https://kyc-metabit-test.onrender.com/"
        keyboard = [
            [InlineKeyboardButton(
                text="فتح تطبيق MetaBit Safety",
                web_app=WebAppInfo(url=webapp_url)
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "اضغط على الزر أدناه لفتح التطبيق المصغر:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "عذراً، يجب عليك التسجيل أولاً باستخدام كود التسجيل.\n"
            "استخدم الأمر /start للبدء."
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages with potential registration codes."""
    user = update.effective_user
    
    # Skip if user is already registered
    if is_user_registered(user.id):
        webapp_url = "https://kyc-metabit-test.onrender.com/"
        keyboard = [
            [InlineKeyboardButton(
                text="فتح تطبيق MetaBit Safety",
                web_app=WebAppInfo(url=webapp_url)
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "أنت مسجل بالفعل! يمكنك فتح التطبيق المصغر:",
            reply_markup=reply_markup
        )
        return
    
    # Check if message is a potential registration code
    input_code = update.message.text.strip()
    
    # Verify the code
    valid_code = verify_code(input_code)
    
    if valid_code:
        # Valid code, register user
        mark_code_used(valid_code, user.id, user.username)
        
        webapp_url = "https://kyc-metabit-test.onrender.com/"
        keyboard = [
            [InlineKeyboardButton(
                text="فتح تطبيق MetaBit Safety",
                web_app=WebAppInfo(url=webapp_url)
            )]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "تم التحقق من كود التسجيل بنجاح! يمكنك الآن دخول نظام الحمايه:",
            reply_markup=reply_markup
        )
    else:
        # Invalid code
        await update.message.reply_text(
            "عذراً، كود التسجيل غير صالح. يرجى التحقق من الكود وإعادة المحاولة."
        )

def main() -> None:
    """Start the bot."""
    # Setup database
    setup_db()
    
    # Create the Application
    application = Application.builder().token(os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("open", open_app))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
