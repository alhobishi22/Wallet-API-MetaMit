# run.py

import os
import sys
import time
import threading
import logging
import asyncio
from dotenv import load_dotenv
import codecs
import psycopg2
import re
from utils.database import Database
import platform

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    PicklePersistence
)
from werkzeug.serving import make_server

# تعيين ترميز المخرجات لـ UTF-8 في Windows
if sys.platform.startswith('win'):
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# تكوين التسجيل
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler("bot.log", encoding='utf-8')
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

from config.config import BOT_TOKEN, States, ADMIN_GROUP_ID, WALLETS, NETWORK_INFO, COMMISSION_SETTINGS, CURRENCIES, EXCHANGE_RATES

# استيراد معالجات المستخدمين والمشرفين
from handlers.user_handlers import (
    start, verify_registration_code, 
    transfer_type_selected, local_currency_selected, wallet_selected,
    account_number_entered, usdt_network_selected, amount_entered,
    recipient_name_entered, recipient_number_entered, verify_txid,
    request_txid, cancel, handle_pending_operation, handle_recipient_confirmation,
    handle_recipient_notes, digital_currency_selected, handle_transfer_agency, start_new_transfer,
    show_help
)

from handlers.admin_handlers import (
    admin_response_handler,
    handle_transfer_info_message,
    handle_rejection_reason,
    cancel_admin_action,
    handle_transfer_info,
    confirm_transfer_info,
    edit_transfer_info
)


def run_dashboard():
    """تشغيل لوحة التحكم في خيط (Thread) منفصل."""
    try:
        from dashboard.dashboard import app
        logger.info("🌐 جاري تشغيل لوحة التحكم...")
        server = make_server('0.0.0.0', 5000, app)
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ خطأ في تشغيل لوحة التحكم: {e}", exc_info=True)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأخطاء"""
    logger.error(f"حدث خطأ: {context.error}", exc_info=True)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى باستخدام /start"
            )
    except Exception as e:
        logger.error(f"❌ خطأ في معالج الأخطاء: {e}", exc_info=True)

def check_requirements():
    """التحقق من تثبيت المتطلبات."""
    try:
        import flask
        from telegram.ext import Application
        import aiohttp
        return True
    except ImportError as e:
        logger.error(f"بعض المتطلبات غير مثبتة: {e}")
        logger.info("جاري تثبيت المتطلبات...")
        try:
            import subprocess
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            logger.info("✅ تم تثبيت المتطلبات بنجاح")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ فشل تثبيت المتطلبات: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ حدث خطأ غير متوقع أثناء تثبيت المتطلبات: {e}")
            return False

def check_environment():
    """التحقق من متغيرات البيئة."""
    required_vars = ['BOT_TOKEN', 'ADMIN_GROUP_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"❌ المتغيرات الإلزامية التالية مفقودة: {', '.join(missing_vars)}")
        return False

    blockchain_vars = {
        'TRONGRID_API_KEY': 'TRC20',
        'BSCSCAN_API_KEY': 'BEP20',
        'ETHERSCAN_API_KEY': 'ERC20'
    }

    missing_apis = [key for key, network in blockchain_vars.items() if not os.getenv(key)]
    if missing_apis:
        affected_networks = [blockchain_vars[key] for key in missing_apis]
        logger.warning(f"⚠️ تنبيه: المفاتيح التالية غير متوفرة: {', '.join(missing_apis)}")
        logger.warning(f"⚠️ الشبكات التالية لن تعمل: {', '.join(affected_networks)}")

    return True

def create_directories():
    directories = ['data', 'logs']
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"✅ تم التأكد من وجود المجلد: {directory}")

# إنشاء كائن قاعدة البيانات عالمي
db = Database()

def run_bot():
    """تشغيل البوت"""
    # استخدام Persistence لحفظ الحالة
    persistence = PicklePersistence(filepath="bot_data.pkl")

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .concurrent_updates(True)
        .connection_pool_size(8)
        .get_updates_connection_pool_size(8)
        .get_updates_read_timeout(30.0)
        .get_updates_write_timeout(30.0)
        .get_updates_connect_timeout(30.0)
        .get_updates_pool_timeout(30.0)
        .build()
    )
    async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [KeyboardButton("💰 ايداع"), KeyboardButton("🏧 سحب")]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)
        await update.message.reply_text(
            "👋 مرحباً بك في بوت التحويلات!\n"
            "برجاء اختيار العملية المطلوبة:",
            reply_markup=reply_markup
        )

    application.bot_data['db'] = db

    # محادثة المستخدم
    conv_handler = ConversationHandler(
    entry_points=[
        CommandHandler('start', start),
        # زر "إعادة بدء تحويل" عبر CallbackQuery
        CallbackQueryHandler(start_new_transfer, pattern='^start_new$'),
        # زر اختيار نوع التحويل (تحويل بالاسم أو بالحساب)
        CallbackQueryHandler(transfer_type_selected, pattern='^(name_transfer|transfer_account)$'),
        # أي رسالة تحتوي "سحب" تعتبر Entry Point أيضًا
        MessageHandler(filters.Regex("^(🏧 سحب|سحب)$"), start),
        CallbackQueryHandler(cancel, pattern='^cancel$')
    ],

    states={
        # إذا كان لدى المستخدم عملية معلّقة
        States.HANDLE_PENDING: [
            CallbackQueryHandler(handle_pending_operation, pattern='^(continue_current|start_new)$')
        ],

        # مرحلة إدخال كود التسجيل
        States.ENTER_REGISTRATION_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, verify_registration_code),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # اختيار نوع التحويل (بالاسم أو بالحساب)
        States.SELECT_TRANSFER_TYPE: [
            CallbackQueryHandler(transfer_type_selected, pattern='^(name_transfer|transfer_account)$'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # اختيار العملة المحلية
        States.SELECT_LOCAL_CURRENCY: [
            CallbackQueryHandler(local_currency_selected, pattern='^currency_'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # اختيار المحفظة (إذا كانت عملة رقمية) أو بنك محلي
        States.SELECT_WALLET: [
            CallbackQueryHandler(wallet_selected, pattern='^wallet_'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال رقم الحساب
        States.ENTER_ACCOUNT_NUMBER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, account_number_entered),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # اختيار العملة الرقمية
        States.SELECT_DIGITAL_CURRENCY: [
            CallbackQueryHandler(digital_currency_selected, pattern='^digital_'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # اختيار شبكة الـ USDT (TRC20, ERC20, BEP20, ...)
        States.SELECT_USDT_NETWORK: [
            CallbackQueryHandler(usdt_network_selected, pattern='^network_'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال المبلغ
        States.ENTER_AMOUNT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, amount_entered),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال اسم المستلم
        States.ENTER_RECIPIENT_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, recipient_name_entered),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال رقم المستلم
        States.ENTER_RECIPIENT_NUMBER: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, recipient_number_entered),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال (الوكالة أو الشركة) - إن كان التحويل بالاسم
        States.ENTER_TRANSFER_AGENCY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_transfer_agency),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # تأكيد معلومات المستلم
        States.CONFIRM_RECIPIENT_INFO: [
            CallbackQueryHandler(handle_recipient_confirmation, pattern='^(confirm_recipient_info|edit_recipient_info)$'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # انتظار الإثبات (في حال احتجت إدخال TxID أو إثبات التحويل)
        States.WAITING_DEPOSIT: [
            CallbackQueryHandler(request_txid, pattern='^enter_txid$'),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال TxID
        States.ENTER_TXID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, verify_txid),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # في حالة طلب إرسال معلومات التحويل للمشرف
        States.ENTER_TRANSFER_INFO: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_transfer_info),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],

        # إدخال ملاحظات إضافية عن المستلم أو العملية
        States.ENTER_RECIPIENT_NOTES: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_recipient_notes),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ]
    },

    # لو المستخدم كتب /cancel أو ضغط زر إلغاء، نخرج من المحادثة
    fallbacks=[
        CommandHandler('start', start),
        CommandHandler('cancel', cancel),
        CallbackQueryHandler(cancel, pattern='^cancel$')
    ],

    # إعدادات إضافية للمحادثة
    per_chat=True,           # محادثة مستقلة لكل محادثة (chat)
    per_user=True,           # أو لكل مستخدم
    allow_reentry=True,      # السماح بدخول المحادثة من جديد
    name="main_conversation",
    persistent=True          # حفظ حالة المحادثة في التخزين (persistence) إذا تم تفعيله
)

    # محادثة المشرف
    admin_conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                admin_response_handler,
                pattern='^(admin_approve|admin_reject|send_transfer_info|admin_back)_[a-zA-Z0-9-]+$'
            )
        ],
        states={
            States.ADMIN_INITIAL: [
                CallbackQueryHandler(
                    admin_response_handler,
                    pattern='^(admin_approve|admin_reject|admin_back)_[a-zA-Z0-9-]+$'
                )
            ],
            States.SEND_TRANSFER_INFO: [
                MessageHandler(
                    (filters.PHOTO | filters.Document.ALL | filters.TEXT) & ~filters.COMMAND,
                    handle_transfer_info_message
                ),
                CallbackQueryHandler(admin_response_handler, pattern='^admin_back_')
            ],
            States.REVIEW_TRANSFER_INFO: [
                CallbackQueryHandler(confirm_transfer_info, pattern='^confirm_send_[a-zA-Z0-9-]+$'),
                CallbackQueryHandler(edit_transfer_info, pattern='^edit_info_[a-zA-Z0-9-]+$')
            ],
            States.ENTER_REJECTION_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rejection_reason),
                CallbackQueryHandler(
                    admin_response_handler,
                    pattern='^(admin_back)_[a-zA-Z0-9-]+$'
                ),
                CallbackQueryHandler(cancel_admin_action, pattern='^cancel$')
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel_admin_action),
            CallbackQueryHandler(cancel_admin_action, pattern='^cancel$')
        ],
        per_chat=True,
        allow_reentry=True,
        name="admin_conversation"
    )

    # إضافة المعالجات
    application.add_handler(conv_handler, group=0)  # مجموعة 0 للمحادثات الرئيسية
    application.add_handler(admin_conv_handler, group=0)
    from handlers.user_handlers import handle_menu_selection
    application.add_handler(MessageHandler(
        filters.Regex("^(💰 ايداع|ايداع|🏧 سحب|سحب)$"), 
        handle_menu_selection,
        block=True
    ), group=1)  # مجموعة 1 لأزرار القائمة
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", show_help))
    application.add_error_handler(error_handler)

    logger.info("🤖 جاري تشغيل البوت...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "chat_member"]
    )

def check_transfer_exists(db: 'Database', transfer_id: str) -> bool:
    exists = db.check_transfer_exists(transfer_id)
    if not exists:
        logger.warning(f"❌ لم يتم العثور على التحويل بمعرف: {transfer_id}")
    else:
        logger.info(f"✅ تم العثور على التحويل: {transfer_id}")
    return exists

def main():
    logger.info("🚀 بدء تشغيل النظام...")

    if not check_requirements():
        logger.error("❌ فشل التحقق من المتطلبات")
        return

    if not check_environment():
        logger.error("❌ فشل التحقق من متغيرات البيئة")
        return

    create_directories()

    try:
        # تشغيل لوحة التحكم في خيط منفصل
        dashboard_thread = threading.Thread(target=run_dashboard)
        dashboard_thread.daemon = True
        dashboard_thread.start()
        logger.info("✅ تم بدء تشغيل لوحة التحكم")

        # تشغيل البوت في الخيط الرئيسي
        run_bot()
    except KeyboardInterrupt:
        logger.info("🔒 تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ حدث خطأ غير متوقع: {e}", exc_info=True)
    finally:
        logger.info("🔄 تم إيقاف النظام بنجاح")

if __name__ == '__main__':
    main()
