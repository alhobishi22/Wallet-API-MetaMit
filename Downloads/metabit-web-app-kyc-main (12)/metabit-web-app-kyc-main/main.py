import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
import requests
from dotenv import load_dotenv
import uvicorn
import json
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import psycopg2
from psycopg2 import sql
from datetime import datetime
import database
import telegram_notifier
from telegram_notifier import (
    send_notification_to_user, 
    send_admin_notification,
    send_kyc_notification, 
    validate_chat_id, 
    update_telegram_message
)
import auth
from auth import verify_password

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_GROUP_ID = os.getenv('ADMIN_GROUP_ID')
WEB_APP_URL = "https://metabit-kyc-v2.onrender.com"

# التحقق من وجود متغيرات البيئة الضرورية
if not TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not found in environment variables!")
    TELEGRAM_BOT_TOKEN = "missing_token"  # قيمة افتراضية لتجنب الأخطاء
    
if not ADMIN_GROUP_ID:
    logger.error("ADMIN_GROUP_ID not found in environment variables!")
    ADMIN_GROUP_ID = "0"  # قيمة افتراضية لتجنب الأخطاء
else:
    # تحويل معرف المجموعة إلى رقم صحيح
    try:
        ADMIN_GROUP_ID = int(ADMIN_GROUP_ID)
    except ValueError:
        logger.error(f"ADMIN_GROUP_ID is not a valid integer: {ADMIN_GROUP_ID}")
        ADMIN_GROUP_ID = 0

logger.info(f"Bot Token: {TELEGRAM_BOT_TOKEN[:5] if TELEGRAM_BOT_TOKEN else 'Not Set'}...")
logger.info(f"Admin Group ID: {ADMIN_GROUP_ID}")

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint for the application"""
    return {
        "app": "MetaBit KYC Verification System",
        "version": "1.0.0",
        "status": "running"
    }

# Global bot application
bot_app = None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command"""
    # تخزين معرف الدردشة
    user_id = update.effective_user.id
    
    # التحقق من حالة طلب المستخدم
    success, status_data = database.get_user_application_status(str(user_id))
    
    if success:
        # المستخدم لديه طلب سابق
        application_id = status_data['application_id']
        status = status_data['status']
        
        if status == 'approved':
            # إذا كان الطلب مقبولاً، توجيه المستخدم إلى صفحة حالة الطلب
            status_url = f"{WEB_APP_URL}/status/{application_id}"
            keyboard = [
                [InlineKeyboardButton("عرض حالة الطلب 📋", web_app=WebAppInfo(url=status_url))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
👋 *مرحباً بك مجدداً في بوت التوثيق!*

لقد تم الموافقة على طلب التوثيق الخاص بك مسبقاً.
🆔 رقم الطلب: `{application_id}`

يمكنك الضغط على الزر أدناه لعرض تفاصيل الطلب.
            """
            
            sent_message = await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        elif status == 'rejected':
            # إذا كان الطلب مرفوضاً، السماح للمستخدم بتقديم طلب جديد
            keyboard = [
                [InlineKeyboardButton("تقديم طلب جديد 🔐", web_app=WebAppInfo(url=WEB_APP_URL))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
👋 *مرحباً بك مجدداً في بوت التوثيق!*

نأسف، لقد تم رفض طلب التوثيق السابق الخاص بك.
🆔 رقم الطلب: `{application_id}`
❓ سبب الرفض: {status_data['rejection_reason'] or "غير محدد"}

يمكنك تقديم طلب جديد بالضغط على الزر أدناه.
            """
            
            sent_message = await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            # إذا كان الطلب قيد المراجعة، توجيه المستخدم إلى صفحة حالة الطلب
            status_url = f"{WEB_APP_URL}/status/{application_id}"
            keyboard = [
                [InlineKeyboardButton("عرض حالة الطلب 📋", web_app=WebAppInfo(url=status_url))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
👋 *مرحباً بك مجدداً في بوت التوثيق!*

طلب التوثيق الخاص بك قيد المراجعة حالياً.
🆔 رقم الطلب: `{application_id}`

يمكنك الضغط على الزر أدناه لعرض تفاصيل الطلب.
            """
            
            sent_message = await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        # المستخدم ليس لديه طلب سابق، عرض رسالة الترحيب العادية
        keyboard = [
            [InlineKeyboardButton("بدء التوثيق 🔐", web_app=WebAppInfo(url=WEB_APP_URL))]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_message = "مرحباً بك في بوت التوثيق! 👋\nيرجى الضغط على الزر أدناه لبدء عملية التوثيق."
        
        sent_message = await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    
    # تخزين معرف رسالة الترحيب
    welcome_message_id = sent_message.message_id
    
    # تحديث معرف رسالة الترحيب في قاعدة البيانات
    database.update_welcome_message_id(str(user_id), welcome_message_id)
    
    logger.info(f"Start command sent to user {user_id}, welcome message ID: {welcome_message_id}")
    
    # تحديث قاعدة البيانات بمعرف المستخدم في تلغرام للطلبات التي قد تكون مرتبطة برقم الهاتف
    try:
        # تلغرام لا يوفر رقم الهاتف مباشرة، لذا سنستخدم فقط اسم المستخدم
        user_name = update.effective_user.full_name
        
        if user_name:
            DATABASE_URL = os.getenv('DATABASE_URL')
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            # تحديث الطلبات المعلقة التي لا تحتوي على معرف دردشة
            update_query = """
                UPDATE kyc_application 
                SET telegram_chat_id = %s
                WHERE telegram_chat_id IS NULL 
                  AND status = 'pending'
                  AND full_name = %s
            """
            
            cur.execute(update_query, (user_id, user_name))
            affected_rows = cur.rowcount
            conn.commit()
            
            if affected_rows > 0:
                logger.info(f"تم تحديث {affected_rows} من الطلبات بمعرف المستخدم {user_id}")
            
            cur.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"خطأ في تحديث معرف المستخدم: {str(e)}")

# Global variables for conversation state
user_states = {}

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline buttons"""
    query = update.callback_query
    data = query.data
    
    await query.answer()
    
    if data.startswith("approve_"):
        request_id = data.split("_")[1]
        
        # Set user state to waiting for registration code
        admin_id = update.effective_user.id
        user_states[admin_id] = {
            "action": "approve",
            "request_id": request_id,
            "awaiting_message": True,
            "original_message_id": query.message.message_id,
            "original_chat_id": query.message.chat_id
        }
        
        # تعديل الرسالة الأصلية لإضافة حقل إدخال رمز التسجيل
        original_text = query.message.text
        
        # إنشاء أزرار للرجوع
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("رجوع 🔙", callback_data=f"back_{request_id}")]
        ])
        
        new_text = (
            f"{original_text}\n\n"
            f"🔐 الرجاء إدخال رمز التسجيل للطلب {request_id}:"
        )
        
        try:
            await query.edit_message_text(
                text=new_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"خطأ في تحديث رسالة الموافقة: {str(e)}")
            # إرسال رسالة جديدة كبديل
            await query.message.reply_text(
                f"🔐 الرجاء إدخال رمز التسجيل للطلب {request_id}:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
    elif data.startswith("reject_"):
        request_id = data.split("_")[1]
        
        # Set user state to waiting for rejection reason
        admin_id = update.effective_user.id
        user_states[admin_id] = {
            "action": "reject",
            "request_id": request_id,
            "awaiting_message": True,
            "original_message_id": query.message.message_id,
            "original_chat_id": query.message.chat_id
        }
        
        # تعديل الرسالة الأصلية لإضافة حقل إدخال سبب الرفض
        original_text = query.message.text
        
        # إنشاء أزرار للرجوع
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("رجوع 🔙", callback_data=f"back_{request_id}")]
        ])
        
        new_text = (
            f"{original_text}\n\n"
            f"❌ الرجاء إدخال سبب رفض الطلب {request_id}:"
        )
        
        try:
            await query.edit_message_text(
                text=new_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"خطأ في تحديث رسالة الرفض: {str(e)}")
            # إرسال رسالة جديدة كبديل
            await query.message.reply_text(
                f"❌ الرجاء إدخال سبب رفض الطلب {request_id}:",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
    elif data.startswith("view_id_") or data.startswith("view_selfie_"):
        # استخراج رقم الطلب
        request_id = data.replace("view_id_", "").replace("view_selfie_", "")
        
        # تحديد نوع الصورة
        is_id_photo = data.startswith("view_id_")
        
        # الحصول على رابط الصورة من قاعدة البيانات
        success, photo_url = database.get_photo_url(request_id, is_id_photo)
        
        if success and photo_url:
            # إرسال الصورة كرسالة جديدة
            photo_type = "صورة الهوية" if is_id_photo else "الصورة الشخصية"
            caption = f"{photo_type} للطلب رقم: {request_id}"
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_url,
                caption=caption,
                parse_mode="Markdown"
            )
        else:
            # إرسال رسالة خطأ
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ تعذر العثور على الصورة للطلب {request_id}",
                parse_mode="Markdown"
            )
        
    elif data.startswith("back_"):
        request_id = data.split("_")[1]
        
        # Reset user state if they were in the middle of approving/rejecting
        admin_id = update.effective_user.id
        if admin_id in user_states:
            user_states.pop(admin_id, None)
        
        # الحصول على معلومات الطلب من قاعدة البيانات
        try:
            DATABASE_URL = os.getenv('DATABASE_URL')
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            query_text = """
                SELECT application_id, full_name, phone_number, telegram_chat_id
                FROM kyc_application 
                WHERE application_id = %s
            """
            cur.execute(query_text, (request_id,))
            result = cur.fetchone()
            
            if result:
                application_id, full_name, phone_number, telegram_chat_id = result
                
                # إنشاء أزرار القبول والرفض من جديد
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("قبول ✅", callback_data=f"approve_{request_id}"),
                        InlineKeyboardButton("رفض ❌", callback_data=f"reject_{request_id}")
                    ],
                    [
                        InlineKeyboardButton("عرض الهوية 🪪", callback_data=f"view_id_{request_id}"),
                        InlineKeyboardButton("عرض الصورة الشخصية 🤳", callback_data=f"view_selfie_{request_id}")
                    ]
                ])
                
                # إعادة إرسال رسالة الطلب
                message = (
                    "🔔 *طلب توثيق جديد*\n\n"
                    f"*رقم الطلب:* `{application_id}`\n"
                    f"*الاسم:* `{full_name}`\n"
                    f"*رقم الهاتف:* `{phone_number}`\n"
                    f"*معرف التلغرام:* `{telegram_chat_id or 'غير متوفر'}`"
                )
                
                try:
                    await query.edit_message_text(
                        text=message,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                except Exception as edit_error:
                    logger.error(f"Error editing message: {str(edit_error)}")
                    # إرسال رسالة جديدة كبديل
                    await query.message.reply_text(
                        text=message,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
            else:
                try:
                    await query.edit_message_text(f"لم يتم العثور على طلب برقم {request_id}", parse_mode="Markdown")
                except Exception as edit_error:
                    logger.error(f"Error editing message: {str(edit_error)}")
                    await query.message.reply_text(f"لم يتم العثور على طلب برقم {request_id}", parse_mode="Markdown")
                
            cur.close()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error retrieving application: {str(e)}")
            try:
                await query.message.reply_text(f"حدث خطأ أثناء استرجاع بيانات الطلب: {str(e)}", parse_mode="Markdown")
            except Exception as inner_e:
                logger.error(f"Error sending error message: {str(inner_e)}")

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin messages for approving/rejecting KYC requests"""
    # تحقق إذا كان المستخدم مشرفًا أو كانت الرسالة من مجموعة المشرفين
    is_admin_user = await is_admin(update, context)
    
    if not is_admin_user:
        # تسجيل المحاولة غير المصرح بها مع معلومات أكثر للتشخيص
        user_id = update.effective_user.id
        username = update.effective_user.username or "بدون اسم مستخدم"
        chat_id = update.effective_chat.id
        logger.info(f"⛔ رسالة من مستخدم غير مصرح له - المعرف: {user_id}, اسم المستخدم: {username}, معرف الدردشة: {chat_id}")
        return
    
    # سجل معلومات المعالجة للتشخيص
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    admin_group_id = os.getenv('ADMIN_GROUP_ID')
    
    if str(chat_id) == str(admin_group_id):
        logger.info(f"✅ معالجة رسالة من مجموعة المشرفين (المستخدم: {user_id})")
    else:
        logger.info(f"✅ معالجة رسالة مباشرة من مشرف معتمد (المستخدم: {user_id})")
    
    # الحصول على معلومات المشرف
    admin_username = update.effective_user.username or "غير معروف"
    admin_first_name = update.effective_user.first_name or ""
    admin_last_name = update.effective_user.last_name or ""
    admin_full_name = f"{admin_first_name} {admin_last_name}".strip() or admin_username
    
    # التحقق مما إذا كان المشرف في حالة انتظار إدخال 
    if user_id in user_states and user_states[user_id]["awaiting_message"]:
        state = user_states[user_id]
        action = state["action"]
        request_id = state["request_id"]
        content = update.message.text  # استخدام النص كما هو بدون أي أوامر
        original_message_id = state.get("original_message_id")
        original_chat_id = state.get("original_chat_id")
        
        logger.info(f"🔄 إكمال إجراء المشرف: {action} للطلب {request_id} بمحتوى: {content}")
        
        # إعادة تعيين حالة المستخدم
        user_states[user_id]["awaiting_message"] = False
        
        # معالجة الإجراء بناءً على نوعه
        if action == "approve":
            success = await process_approval(update, request_id, content, admin_full_name)
            
            # تحديث الرسالة الأصلية لإظهار الإكمال
            if success and original_message_id and original_chat_id:
                try:
                    # الحصول على معلومات الطلب
                    app_info = await database.get_application_info(request_id)
                    if app_info:
                        full_name = app_info.get("full_name", "غير متوفر")
                        phone_number = app_info.get("phone_number", "غير متوفر")
                        
                        # إنشاء رسالة تأكيد
                        confirmation_message = (
                            "✅ *تمت الموافقة على الطلب*\n\n"
                            f"*رقم الطلب:* `{request_id}`\n"
                            f"*الاسم:* `{full_name}`\n"
                            f"*رقم الهاتف:* `{phone_number}`\n"
                            f"*معرف التلغرام:* `{app_info.get('telegram_chat_id', 'غير متوفر')}`\n"
                            f"*رمز التسجيل:* `{content}`\n"
                            f"*بواسطة:* {admin_full_name}\n\n"
                            f"تم إرسال رمز التسجيل للمستخدم."
                        )
                        
                        try:
                            await context.bot.edit_message_text(
                                chat_id=original_chat_id,
                                message_id=original_message_id,
                                text=confirmation_message,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"خطأ في تحديث رسالة الموافقة: {str(e)}")
                            # إرسال رسالة جديدة كبديل
                            await update.message.reply_text(confirmation_message, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"خطأ في الحصول على معلومات الطلب: {str(e)}")
            
        elif action == "reject":
            success = await process_rejection(update, request_id, content, admin_full_name)
            
            # تحديث الرسالة الأصلية لإظهار الإكمال
            if success and original_message_id and original_chat_id:
                try:
                    # الحصول على معلومات الطلب
                    app_info = await database.get_application_info(request_id)
                    if app_info:
                        full_name = app_info.get("full_name", "غير متوفر")
                        phone_number = app_info.get("phone_number", "غير متوفر")
                        
                        # إنشاء رسالة تأكيد
                        confirmation_message = (
                            "❌ *تم رفض الطلب*\n\n"
                            f"*رقم الطلب:* `{request_id}`\n"
                            f"*الاسم:* `{full_name}`\n"
                            f"*رقم الهاتف:* `{phone_number}`\n"
                            f"*معرف التلغرام:* `{app_info.get('telegram_chat_id', 'غير متوفر')}`\n"
                            f"*سبب الرفض:* `{content}`\n"
                            f"*بواسطة:* {admin_full_name}\n\n"
                            f"تم إرسال سبب الرفض للمستخدم."
                        )
                        
                        try:
                            await context.bot.edit_message_text(
                                chat_id=original_chat_id,
                                message_id=original_message_id,
                                text=confirmation_message,
                                parse_mode='Markdown'
                            )
                        except Exception as e:
                            logger.error(f"خطأ في تحديث رسالة الرفض: {str(e)}")
                            # إرسال رسالة جديدة كبديل
                            await update.message.reply_text(confirmation_message, parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"خطأ في الحصول على معلومات الطلب: {str(e)}")
        
        return
    
    # معالجة الرسائل العادية باستخدام الأوامر
    text = update.message.text
    
    # تحقق إذا كان النص يحتوي على أرقام فقط (رقم الطلب)
    if text.isdigit():
        request_id = text
        # عرض معلومات الطلب
        try:
            app_info = await database.get_application_info(request_id)
            if app_info:
                full_name = app_info.get("full_name", "غير متوفر")
                phone_number = app_info.get("phone_number", "غير متوفر")
                status = app_info.get("status", "غير متوفر")
                telegram_chat_id = app_info.get("telegram_chat_id", "غير متوفر")
                
                # إنشاء أزرار القبول والرفض
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("قبول ✅", callback_data=f"approve_{request_id}"),
                        InlineKeyboardButton("رفض ❌", callback_data=f"reject_{request_id}")
                    ],
                    [
                        InlineKeyboardButton("عرض الهوية 🪪", callback_data=f"view_id_{request_id}"),
                        InlineKeyboardButton("عرض الصورة الشخصية 🤳", callback_data=f"view_selfie_{request_id}")
                    ]
                ])
                
                # إرسال معلومات الطلب
                message = (
                    "🔔 *طلب توثيق*\n\n"
                    f"*رقم الطلب:* `{request_id}`\n"
                    f"*الاسم:* `{full_name}`\n"
                    f"*رقم الهاتف:* `{phone_number}`\n"
                    f"*معرف التلغرام:* `{telegram_chat_id}`\n"
                    f"*الحالة:* {status}"
                )
                
                await update.message.reply_text(
                    text=message,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                return
            else:
                await update.message.reply_text(f"⚠️ لم يتم العثور على طلب برقم {request_id}", parse_mode="Markdown")
                return
        except Exception as e:
            logger.error(f"خطأ في استرجاع معلومات الطلب: {str(e)}")
            await update.message.reply_text(f"❌ حدث خطأ أثناء استرجاع معلومات الطلب: {str(e)}", parse_mode="Markdown")
            return
    
    parts = text.split()
    
    # تحقق إذا كان النص يبدأ بـ code أو reject
    if not parts or parts[0].lower() not in ["code", "reject"]:
        # تجاهل الرسائل العادية التي لا تبدأ بـ code أو reject
        return
    
    if len(parts) < 3:
        logger.info(f"⚠️ صيغة الأمر غير صحيحة: {text}")
        await update.message.reply_text(
            "⚠️ صيغة الأمر غير صحيحة. يجب أن تكون الصيغة:\n\n"
            "للقبول: `code رقم_الطلب الكود`\n"
            "للرفض: `reject رقم_الطلب سبب_الرفض`",
            parse_mode="Markdown"
        )
        return
    
    action = parts[0]
    request_id = parts[1]
    content = " ".join(parts[2:])  # استخدام مسافة بدلاً من _
    
    logger.info(f"🔄 إجراء المشرف: {action} للطلب {request_id} بواسطة {admin_full_name}")
    
    # معالجة الإجراء
    if action.lower() == "code":
        await process_approval(update, request_id, content, admin_full_name)
    elif action.lower() == "reject":
        await process_rejection(update, request_id, content, admin_full_name)
    else:
        await update.message.reply_text(
            "⚠️ أمر غير معروف. الأوامر المتاحة هي:\n\n"
            "- `code` لقبول طلب\n"
            "- `reject` لرفض طلب",
            parse_mode="Markdown"
        )

async def process_approval(update, request_id, registration_code, admin_full_name):
    """Process KYC application approval"""
    try:
        # تحديث حالة الطلب في قاعدة البيانات
        success, message = database.approve_application(request_id, admin_full_name, registration_code)
        
        if success:
            # إرسال إشعار للمستخدم
            notification_sent = await send_kyc_notification(request_id, "approved", registration_code)
            
            # إرسال رسالة تأكيد للمشرف
            status_message = ""
            if notification_sent:
                status_message = "✅ تم إرسال إشعار للمستخدم"
            else:
                status_message = "⚠️ تعذر إرسال إشعار للمستخدم (ربما لا يوجد معرف تلغرام)"
                
            # الحصول على معلومات الطلب للحصول على معرف التلغرام
            app_info = await database.get_application_info(request_id)
            telegram_chat_id = app_info.get("telegram_chat_id", "غير متوفر") if app_info else "غير متوفر"
                
            await update.message.reply_text(
                f"✅ تمت الموافقة على الطلب `{request_id}`\n"
                f"🔑 رمز التسجيل: `{registration_code}`\n"
                f"🔗 معرف التلغرام: `{telegram_chat_id}`\n"
                f"👤 بواسطة: {admin_full_name}\n"
                f"{status_message}",
                parse_mode="Markdown"
            )
            return True
        else:
            await update.message.reply_text(f"❌ فشلت عملية الموافقة: {message}", parse_mode="Markdown")
            return False
            
    except Exception as e:
        logger.error(f"خطأ في معالجة الموافقة على الطلب: {str(e)}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الطلب: {str(e)}", parse_mode="Markdown")
        return False

async def process_rejection(update, request_id, reason, admin_full_name):
    """Process KYC application rejection"""
    try:
        # تحديث حالة الطلب في قاعدة البيانات
        success, message = database.reject_application(request_id, admin_full_name, reason)
        
        if success:
            # إرسال إشعار للمستخدم
            notification_sent = await send_kyc_notification(request_id, "rejected", reason)
            
            # إرسال رسالة تأكيد للمشرف
            status_message = ""
            if notification_sent:
                status_message = "✅ تم إرسال إشعار للمستخدم"
            else:
                status_message = "⚠️ تعذر إرسال إشعار للمستخدم (ربما لا يوجد معرف تلغرام)"
                
            # الحصول على معلومات الطلب للحصول على معرف التلغرام
            app_info = await database.get_application_info(request_id)
            telegram_chat_id = app_info.get("telegram_chat_id", "غير متوفر") if app_info else "غير متوفر"
                
            await update.message.reply_text(
                f"❌ تم رفض الطلب `{request_id}`\n"
                f"📝 السبب: `{reason}`\n"
                f"🔗 معرف التلغرام: `{telegram_chat_id}`\n"
                f"👤 بواسطة: {admin_full_name}\n"
                f"{status_message}",
                parse_mode="Markdown"
            )
            return True
        else:
            await update.message.reply_text(f"❌ فشلت عملية الرفض: {message}", parse_mode="Markdown")
            return False
            
    except Exception as e:
        logger.error(f"خطأ في معالجة رفض الطلب: {str(e)}")
        await update.message.reply_text(f"❌ حدث خطأ أثناء معالجة الطلب: {str(e)}", parse_mode="Markdown")
        return False

async def update_telegram_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actualizar manualmente los IDs de Telegram en la base de datos"""
    if not await is_admin(update, context):
        await update.message.reply_text("⛔ هذا الأمر متاح فقط للمشرفين", parse_mode="Markdown")
        return
    
    try:
        # الحصول على معرف المستخدم ورقم الهاتف من الرسالة
        command_parts = update.message.text.split()
        if len(command_parts) < 3:
            await update.message.reply_text("📝 استخدام: /update_id <application_id> <telegram_chat_id>", parse_mode="Markdown")
            return
        
        application_id = command_parts[1]
        telegram_chat_id = int(command_parts[2])
        
        # تحديث قاعدة البيانات
        success = database.update_telegram_chat_id(application_id, telegram_chat_id)
        
        if success:
            await update.message.reply_text(
                f"✅ تم تحديث معرف تلغرام للطلب {application_id}\n"
                f"معرف تلغرام الجديد: {telegram_chat_id}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(f"❌ لم يتم العثور على طلب بالرقم {application_id}", parse_mode="Markdown")
        
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون معرف تلغرام رقمًا صحيحًا", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"خطأ في تحديث معرف تلغرام: {str(e)}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}", parse_mode="Markdown")

async def resend_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إعادة إرسال الإشعارات يدوياً للمستخدم"""
    if not await is_admin(update, context):
        await update.message.reply_text("⛔ هذا الأمر متاح فقط للمشرفين", parse_mode="Markdown")
        return
    
    try:
        # الحصول على معلومات المستخدم والرسالة
        command_parts = update.message.text.split(maxsplit=2)
        if len(command_parts) < 3:
            await update.message.reply_text("📝 استخدام: /resend <telegram_chat_id> <نص الرسالة>", parse_mode="Markdown")
            return
        
        telegram_chat_id = int(command_parts[1])
        message = command_parts[2]
        
        # إعلام المشرف بأن الإرسال قيد التقدم
        await update.message.reply_text(f"⏳ جاري إرسال الإشعار إلى المستخدم {telegram_chat_id}...", parse_mode="Markdown")
        
        # إرسال الإشعار
        max_attempts = 3
        attempt = 0
        success = False
        
        while attempt < max_attempts and not success:
            attempt += 1
            logger.info(f"محاولة {attempt} لإرسال الإشعار إلى المستخدم {telegram_chat_id}")
            success = await send_kyc_notification(telegram_chat_id, message, "Markdown")
            if not success and attempt < max_attempts:
                await asyncio.sleep(2 * attempt)  # زيادة فترة الانتظار مع كل محاولة
        
        if success:
            await update.message.reply_text(f"✅ تم إرسال الإشعار بنجاح إلى المستخدم {telegram_chat_id}", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ فشلت جميع محاولات إرسال الإشعار إلى المستخدم {telegram_chat_id}", parse_mode="Markdown")
        
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون معرف تلغرام رقمًا صحيحًا", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"خطأ في إرسال الإشعار: {str(e)}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}", parse_mode="Markdown")

@app.post("/api/kyc-submission")
async def handle_kyc_submission(request: Request):
    """Handle KYC submission from the web app and notify admins via Telegram"""
    try:
        logger.info("Received a new KYC submission request")
        
        # Get the JSON data from the request
        kyc_data = await request.json()
        logger.info(f"Parsed request data: {kyc_data}")
        
        request_id = kyc_data.get('requestId', 'غير متوفر')
        telegram_chat_id = kyc_data.get('telegramChatId')
        
        # تسجيل وتنظيف معرف الدردشة
        if telegram_chat_id:
            try:
                telegram_chat_id = int(str(telegram_chat_id).strip())
                logger.info(f"معرف الدردشة في تلغرام بعد التنظيف: {telegram_chat_id}")
            except (ValueError, TypeError):
                logger.warning(f"تم استلام معرف دردشة غير صالح: {telegram_chat_id}")
                telegram_chat_id = None
        
        logger.info(f"Received KYC submission with request ID: {request_id}, Telegram chat ID: {telegram_chat_id}")
        
        # Save to database
        try:
            # Create database connection
            DATABASE_URL = os.getenv('DATABASE_URL')
            if not DATABASE_URL:
                logger.error("DATABASE_URL not set in environment variables")
                return {
                    "status": "error",
                    "message": "Database configuration missing"
                }
                
            conn = psycopg2.connect(DATABASE_URL)
            cur = conn.cursor()
            
            # Create KYC application record
            query = """
                INSERT INTO kyc_application 
                (application_id, full_name, phone_number, address, id_photo_url, selfie_photo_url, status, telegram_chat_id) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cur.execute(query, (
                request_id,
                kyc_data.get('fullName', 'غير متوفر'),
                kyc_data.get('phone', 'غير متوفر'),
                kyc_data.get('address', 'غير متوفر'),
                kyc_data.get('idCardFrontImage', ''),
                kyc_data.get('selfieImage', ''),
                'pending',
                telegram_chat_id
            ))
            
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"Successfully saved KYC application to database")
        except Exception as db_error:
            logger.error(f"Error saving to database: {str(db_error)}")
        
        # Format message
        message = (
            f"🔔 *طلب توثيق جديد*\n\n"
            f"*رقم الطلب:* {request_id}\n"
            f"*الاسم:* {kyc_data.get('fullName', 'غير متوفر')}\n"
            f"*رقم الهاتف:* {kyc_data.get('phone', 'غير متوفر')}\n"
            f"*البريد الإلكتروني:* {kyc_data.get('email', 'غير متوفر')}\n"
            f"*رقم الهوية:* {kyc_data.get('idNumber', 'غير متوفر')}\n"
        )
        
        # Send text message
        logger.info(f"Attempting to send notification to admin group: {ADMIN_GROUP_ID}")
        if TELEGRAM_BOT_TOKEN == "missing_token":
            logger.error("TELEGRAM_BOT_TOKEN is missing, cannot send notification")
            return {
                "status": "error",
                "message": "Telegram Bot Token is missing"
            }
        
        text_result = send_notification_to_user(ADMIN_GROUP_ID, message, "Markdown")
        logger.info(f"Notification result: {text_result}")
        
        if not text_result.get("ok"):
            logger.error(f"Failed to send text message: {text_result}")
            return {
                "status": "error",
                "message": f"Error sending to Telegram: {text_result.get('description')}"
            }
        
        # Send images if available
        if 'idCardFrontImage' in kyc_data and kyc_data['idCardFrontImage']:
            send_notification_to_user(
                ADMIN_GROUP_ID,
                "صورة الهوية (الأمام) 🪪",
                "Markdown",
                photo=kyc_data['idCardFrontImage']
            )
        
        if 'idCardBackImage' in kyc_data and kyc_data['idCardBackImage']:
            send_notification_to_user(
                ADMIN_GROUP_ID,
                "صورة الهوية (الخلف) 🪪",
                "Markdown",
                photo=kyc_data['idCardBackImage']
            )
        
        if 'selfieImage' in kyc_data and kyc_data['selfieImage']:
            send_notification_to_user(
                ADMIN_GROUP_ID,
                "الصورة الشخصية 🤳",
                "Markdown",
                photo=kyc_data['selfieImage']
            )
        
        # Create keyboard for admin approval/rejection
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "قبول ✅", "callback_data": f"approve_{request_id}"},
                    {"text": "رفض ❌", "callback_data": f"reject_{request_id}"}
                ]
            ]
        }
        
        # Send a message with the approval buttons
        approve_message = f"الرجاء اتخاذ قرار بشأن طلب التوثيق (رقم: {request_id})"
        
        approve_result = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": ADMIN_GROUP_ID,
                "text": approve_message,
                "reply_markup": keyboard
            }
        ).json()
        
        logger.info(f"Admin approval message sent: {approve_result.get('ok')}")
        
        return {
            "status": "success",
            "message": "KYC submission received and admins notified"
        }
        
    except Exception as e:
        logger.error(f"Error in handle_kyc_submission: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/kyc-status/{application_id}")
async def check_kyc_status(application_id: str):
    """Check the status of a KYC application"""
    try:
        DATABASE_URL = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Get the application status
        query = sql.SQL("""
            SELECT status, registration_code, rejection_reason 
            FROM kyc_application 
            WHERE application_id = %s
        """)
        cur.execute(query, (application_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not result:
            return {
                "status": "error",
                "message": "Application not found"
            }
        
        status, registration_code, rejection_reason = result
        
        response = {
            "status": "success",
            "application_status": status,
        }
        
        if status == "approved" and registration_code:
            response["registration_code"] = registration_code
        
        if status == "rejected" and rejection_reason:
            response["rejection_reason"] = rejection_reason
        
        return response
        
    except Exception as e:
        logger.error(f"Error checking KYC status: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/health")
async def health_check():
    """Health check endpoint that also tests database connection"""
    try:
        # Get Database URL from environment
        DATABASE_URL = os.getenv('DATABASE_URL')
        if not DATABASE_URL:
            return {
                "status": "warning",
                "database": "DATABASE_URL not set",
                "bot": "active" if TELEGRAM_BOT_TOKEN != "missing_token" else "not configured"
            }
            
        # Test database connection
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        
        return {
            "status": "healthy",
            "database": "connected",
            "bot": "active" if TELEGRAM_BOT_TOKEN != "missing_token" else "not configured"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "database": "error",
            "bot": "active" if TELEGRAM_BOT_TOKEN != "missing_token" else "not configured"
        }

async def run_bot():
    """Run the Telegram bot"""
    global bot_app
    
    # Skip bot initialization if no valid token
    if TELEGRAM_BOT_TOKEN == "missing_token":
        logger.warning("Skipping Telegram bot initialization - no valid token")
        return
    
    # Create the application
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register handlers
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Add message handler for processing admin responses (approvals/rejections)
    admin_group_id = os.getenv('ADMIN_GROUP_ID')
    admin_telegram_id = os.getenv('ADMIN_TELEGRAM_ID')
    
    # إنشاء فلتر مخصص للتحقق من أن الرسالة من مجموعة المشرفين
    admin_filter = filters.Chat(chat_id=int(admin_group_id) if admin_group_id and admin_group_id.isdigit() else None)
    
    # إضافة معالج الرسائل مع الفلتر المخصص
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & admin_filter, handle_admin_message))
    bot_app.add_handler(CommandHandler("update_id", update_telegram_ids))
    bot_app.add_handler(CommandHandler("resend", resend_notification))
    bot_app.add_handler(CommandHandler("list_requests", list_pending_requests))
    
    # Start the bot in a non-blocking way
    try:
        await bot_app.initialize()
        await bot_app.start()
        
        # Start polling for messages
        await bot_app.updater.start_polling()
        
        logger.info("Telegram Bot started successfully.")
    except Exception as e:
        logger.error(f"Error starting Telegram bot: {str(e)}")
        bot_app = None

async def run_fastapi():
    """Run the FastAPI server"""
    config = uvicorn.Config(app, host="0.0.0.0", port=8888)
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    """Run both the bot and FastAPI server"""
    await asyncio.gather(
        run_bot(),
        run_fastapi()
    )

async def list_pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض قائمة طلبات KYC المعلقة"""
    if not await is_admin(update, context):
        await update.message.reply_text("⛔ هذا الأمر متاح فقط للمشرفين", parse_mode="Markdown")
        return
    
    try:
        DATABASE_URL = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # استعلام عن الطلبات المعلقة
        query = """
            SELECT application_id, full_name, status, telegram_chat_id, created_at
            FROM kyc_application
            WHERE status = 'pending' OR status = 'in_review'
            ORDER BY created_at DESC
            LIMIT 10
        """
        
        cur.execute(query)
        results = cur.fetchall()
        
        if not results:
            await update.message.reply_text("🔍 لا توجد طلبات معلقة حالياً", parse_mode="Markdown")
            return
            
        # بناء الرسالة
        message = "📋 *قائمة الطلبات المعلقة:*\n\n"
        
        for result in results:
            application_id, full_name, status, telegram_chat_id, created_at = result
            status_emoji = "⏳" if status == "pending" else "🔍"
            telegram_status = "✅" if telegram_chat_id else "❌"
            
            message += f"{status_emoji} *{application_id}*\n"
            message += f"👤 الاسم: `{full_name}`\n"
            message += f"📱 حالة تلغرام: {telegram_status}\n"
            message += f"📅 التاريخ: {created_at.strftime('%Y-%m-%d %H:%M')}\n\n"
        
        message += "\nلإرسال إشعار، استخدم:\n`/resend <telegram_chat_id> <نص الرسالة>`"
        
        await update.message.reply_text(message, parse_mode="Markdown")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"خطأ في عرض الطلبات المعلقة: {str(e)}")
        await update.message.reply_text(f"❌ حدث خطأ: {str(e)}", parse_mode="Markdown")

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if the user is an admin"""
    user_id = update.effective_user.id
    
    try:
        # التحقق أولاً إذا كان المستخدم هو المشرف الرئيسي
        admin_telegram_id = os.getenv('ADMIN_TELEGRAM_ID')
        if admin_telegram_id and str(user_id) == str(admin_telegram_id):
            logger.info(f"المستخدم {user_id} هو المشرف الرئيسي")
            return True
            
        # التحقق إذا كان المستخدم عضوًا في مجموعة المشرفين
        admin_group_id = os.getenv('ADMIN_GROUP_ID')
        if not admin_group_id:
            logger.warning("لم يتم تعيين معرف مجموعة المشرفين")
            return False
            
        # اعتبار الرسائل من المجموعة نفسها مسموح بها دائمًا
        if str(update.effective_chat.id) == str(admin_group_id):
            return True
            
        # التحقق من عضوية المستخدم في المجموعة
        try:
            chat_member = await context.bot.get_chat_member(chat_id=admin_group_id, user_id=user_id)
            if chat_member.status in ['member', 'administrator', 'creator']:
                logger.info(f"المستخدم {user_id} هو عضو في مجموعة المشرفين")
                return True
        except Exception as e:
            logger.error(f"خطأ في التحقق من عضوية المجموعة: {str(e)}")
        
        return False
        
    except Exception as e:
        logger.error(f"خطأ في التحقق من صلاحيات المشرف: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        print("Starting MetaBit KYC Verification System...")
        print(f"Telegram Bot Token: {TELEGRAM_BOT_TOKEN[:5] if TELEGRAM_BOT_TOKEN else 'Not Set'}...")
        print(f"Admin Group ID: {ADMIN_GROUP_ID}")
        print("Starting bot and FastAPI server...")
        
        # Test database connection
        db_status = asyncio.run(health_check())
        if db_status.get("database_status") == "connected":
            print("Database connection successful!")
        else:
            print("Warning: Database connection failed. Check your database settings.")
        
        # Run both the bot and FastAPI server
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication stopped by user.")
    except Exception as e:
        logger.error(f"Critical error: {str(e)}")
        print(f"Critical error: {str(e)}")
    finally:
        print("Application shutdown complete.")
