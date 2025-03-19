# handlers/confirmation_handler.py
from services.wallet_validator import wallet_validator
from services.settings_service import get_setting
from typing import Tuple
import uuid
import logging
import os
from datetime import datetime, timedelta, timezone
import pytz  # إضافة مكتبة pytz للتعامل مع المناطق الزمنية

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
    error
)
from telegram.ext import (
    ConversationHandler,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    CallbackContext
)
from config.settings import (
    ADMIN_USER_IDS,
    ADMIN_GROUP_ID, 
    SUPPORTED_CRYPTOCURRENCIES,
    SUPPORTED_NETWORKS,
    # EXCHANGE_RATES,  # تم إزالة الاعتماد على القيم الثابتة
    LOCAL_CURRENCIES,  
    WITHDRAWAL_LIMITS
)
from services.telegram_service import telegram_service
from services.database_service import (
    save_withdrawal, 
    get_withdrawal, 
    update_withdrawal_status,
    is_user_registered,
    add_user,
    verify_registration_code,
    get_user_registration_code,
    get_connection,
    release_connection,
    has_pending_request,
    get_exchange_rates
)
from services.binance_service import binance_service
from typing import Dict
from asyncio import Lock
from typing import Dict

logger = logging.getLogger(__name__)

# تعريف معرفات قروبات المشرفين
ADMIN_GROUP_ID = "-1002410603066"  # قروب المشرفين للتحويل عبر الاسم
ADMIN_GROUP_ID_2 = "-4764569911"  # قروب المشرفين للإيداع البنكي

# تعريف مراحل المحادثة
(
    REGISTRATION,
    SELECT_TRANSFER_TYPE,  # اختيار نوع التحويل
    SELECT_BANK,          # اختيار البنك
    REQUEST_CURRENCY,
    REQUEST_NETWORK,
    REQUEST_LOCAL_CURRENCY,
    REQUEST_AMOUNT,
    REQUEST_TRANSFER_NUMBER,
    REQUEST_TRANSFER_ISSUER,
    REQUEST_WALLET_ADDRESS,
    CONFIRMATION,
    CANCEL_REASON,
    AWAITING_REJECTION_REASON 
) = range(13)

# تعريف أنواع التحويل
TRANSFER_TYPES = {

    'name_transfer': "🪪التحويل عبر الاسم",
     'bank_deposit': '🏦الإيداع عبر المحفظة المالية ',
    'kuraimi_transfer': "💳التحويل عبر الكريمي",
}

# تعريف قائمة البنوك
BANKS = {
    '📱محفظة جيب',
    '📱محفظة كاش',
    '📱محفظة ون كاش',
    '📱محفظة جوالي'
}

# أسباب الرفض
REJECTION_REASONS = [
    "اسم المرسل غير مطابق لاسمه بالنظام ",
    "اسم المستلم غير مطابق ",
    "رقم الحوالة غير صحيح",
    "هذه الحواله مسحوبه من قبل",
    "المبلغ غير مطابق",
    "حاول مره اخرى"
]
CANCELLATION_REASONS = {
    'amount_mismatch': 'عدم تطابق المبلغ المدفوع',
    'wrong_info': 'معلومات غير صحيحة',
    'duplicate': 'طلب مكرر',
    'user_request': 'بناءً على طلب المستخدم',
    'other': 'سبب آخر'
}

# تعريف خيارات التنقل
BACK = 'back'
CANCEL = 'cancel'
from telegram.constants import ParseMode  # أضف هذا الاستيراد

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ConversationHandler, CommandHandler, MessageHandler, filters
active_users: Dict[int, datetime] = {}
_confirmation_locks: Dict[int, Lock] = {}

async def handle_text_message(update: Update, context: CallbackContext) -> None:
   """معالجة الرسائل النصية"""
   chat_id = str(update.effective_chat.id)
   text = (update.message.text or "").strip()
   user_id = update.effective_user.id
   
   # تجاهل رسائل المستخدمين في مجموعات المشرفين
   if chat_id in [ADMIN_GROUP_ID, ADMIN_GROUP_ID_2]:
       logger.info(f"تجاهل رسالة في مجموعة المشرفين: {chat_id}")
       return ConversationHandler.END
       
   logger.info("=== معالجة رسالة نصية ===")
   logger.info(f"النص: {text}")
   logger.info(f"معرّف المستخدم: {user_id}")

   try:
       current_state = context.user_data.get('current_state')
       logger.info(f"الحالة الحالية: {current_state}")

       # التأكد من إضافة المستخدم إلى قاعدة البيانات
       try:
           await add_user(user_id)
       except Exception as e:
           logger.error(f"خطأ في إضافة المستخدم: {e}")

       # التحقق من حالة التسجيل للمستخدم
       is_registered = await is_user_registered(user_id)
       logger.info(f"حالة التسجيل: {is_registered}")

       if text == "/start":
           if not is_registered:
               await update.message.reply_text(
                   "🔒 *مرحباً بك!*\n\n"
                   "عذراً، لا يمكنك استخدام البوت حتى يتم تفعيل حسابك.\n"
                   "🔑 يرجى إدخال رمز التسجيل للمتابعة.\n"
                   "لتفعيل حسابك، يرجى التواصل معنا عبر واتساب:\n"
                   "https://wa.me/+967774506423",
                   
                   parse_mode=ParseMode.MARKDOWN
               )
               context.user_data['current_state'] = REGISTRATION
               return REGISTRATION
           else:
               keyboard = [
                   [KeyboardButton("💰 إيداع"), KeyboardButton("💳 سحب")]
               ]
               reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
               await update.message.reply_text(
                   "👋 *مرحباً بك مرة أخرى!*\n\n"
                   "يمكنك استخدام الأزرار أدناه للإيداع أو السحب.",
                   reply_markup=reply_markup,
                   parse_mode=ParseMode.MARKDOWN
               )
               return ConversationHandler.END

       # معالجة رمز التسجيل
       if not is_registered:
           # إذا كان في حالة التسجيل أو أدخل الرمز مباشرة
           if current_state == REGISTRATION or (not current_state and text != "/start"):
               registration_code = text
               is_valid = await verify_registration_code(user_id, registration_code)
               logger.info(f"نتيجة التحقق من الكود: {is_valid}")

               if is_valid:
                   # الكود صحيح
                   keyboard = [
                       [KeyboardButton("💰 إيداع"), KeyboardButton("💳 سحب")]
                   ]
                   reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
                   
                   await update.message.reply_text(
                       "✅ *تم التحقق من الكود بنجاح!*\n\n"
                       "يمكنك الآن استخدام البوت للإيداع والسحب.\n"
                       "استخدم الأزرار أدناه للبدء.",
                       reply_markup=reply_markup,
                       parse_mode=ParseMode.MARKDOWN
                   )
                   context.user_data['current_state'] = None
                   return ConversationHandler.END
               else:
                   # الكود خاطئ
                   await update.message.reply_text(
                       "❌ *رمز التسجيل غير صحيح!*\n\n"
                       "🔑 يرجى إدخال رمز تسجيل صحيح.\n\n"
                       "📞 للتواصل مع الدعم:\n"
                       "`+967 774506423`",
                       parse_mode=ParseMode.MARKDOWN
                   )
                   context.user_data['current_state'] = REGISTRATION
                   return REGISTRATION
           else:
               # إذا لم يكن في حالة التسجيل وغير مسجل
               await update.message.reply_text(
                   "🔒 *تنبيه!*\n\n"
                   "يجب التسجيل أولاً قبل استخدام البوت.\n"
                   "🔑 يرجى إدخال رمز التسجيل للمتابعة.",
                   parse_mode=ParseMode.MARKDOWN
               )
               context.user_data['current_state'] = REGISTRATION
               return REGISTRATION

       # المستخدم مسجل - معالجة العمليات الأخرى
       if text == "💰 إيداع":
           try:
               # التحقق من وجود طلب نشط
               has_active = await has_pending_request(user_id)
               if has_active:
                   await update.message.reply_text(
                       "⚠️ *لديك طلب قيد المعالجة*\n\n"
                       "يرجى انتظار اكتمال معالجة الطلب الحالي.",
                       parse_mode=ParseMode.MARKDOWN
                   )
                   return ConversationHandler.END

               keyboard = [
                   [InlineKeyboardButton("التحويل عبر الاسم 🪪", callback_data="transfer_type_name_transfer")],
                   [InlineKeyboardButton("الإيداع عبر المحفظة المالية 🏦", callback_data="transfer_type_bank_deposit")],
                   [InlineKeyboardButton("التحويل عبر الكريمي 💳", callback_data="transfer_type_kuraimi_transfer")],
                   [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
               ]
               
               await update.message.reply_text(
                   "🌟 *الرجاء اختيار طريقة التحويل:*",
                   reply_markup=InlineKeyboardMarkup(keyboard),
                   parse_mode=ParseMode.MARKDOWN
               )
               context.user_data['current_state'] = SELECT_TRANSFER_TYPE
               return SELECT_TRANSFER_TYPE

           except Exception as e:
               logger.error(f"خطأ في معالجة طلب الإيداع: {e}")
               await update.message.reply_text(
                   "❌ حدث خطأ. الرجاء المحاولة مرة أخرى.",
                   parse_mode=ParseMode.MARKDOWN
               )
               return ConversationHandler.END

       elif text == "💳 سحب":
           keyboard = [[InlineKeyboardButton("↗️ انتقال إلى بوت السحب", url="https://t.me/metabittradebot")]]
           await update.message.reply_text(
               "اضغط على الزر أدناه للانتقال إلى بوت السحب",
               reply_markup=InlineKeyboardMarkup(keyboard),
               parse_mode=ParseMode.MARKDOWN
           )
           return ConversationHandler.END

       # معالجة المراحل المختلفة
       if current_state == REQUEST_AMOUNT:
           return await handle_amount(update, context)
       elif current_state == REQUEST_TRANSFER_NUMBER:
           return await handle_transfer_number(update, context)
       elif current_state == REQUEST_TRANSFER_ISSUER:
           return await handle_transfer_issuer(update, context)
       elif current_state == REQUEST_WALLET_ADDRESS:
           return await handle_wallet_address(update, context)

   except Exception as e:
       logger.error(f"خطأ في معالجة الرسالة النصية: {e}")
       await update.message.reply_text(
           "❌ عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى.",
           parse_mode=ParseMode.MARKDOWN
       )
       return ConversationHandler.END

   return current_state if current_state else ConversationHandler.END

async def show_start_button(update: Update, context: CallbackContext) -> None:
    """عرض زر البدء مع التحقق من التسجيل والطلبات المعلقة"""
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    
    # تجاهل أمر البدء في مجموعات المشرفين
    if chat_id in [ADMIN_GROUP_ID, ADMIN_GROUP_ID_2]:
        logger.info(f"تجاهل أمر البدء في مجموعة المشرفين: {chat_id}")
        return ConversationHandler.END

    try:
        # التحقق من وجود المستخدم وإضافته إذا لم يكن موجوداً
        conn = await get_connection()
        user_exists = await conn.fetchval("""
            SELECT EXISTS(SELECT 1 FROM users WHERE user_id = $1)
        """, user_id)
       
        if not user_exists:
            await add_user(user_id)
            await release_connection(conn)
            
            # إضافة أزرار التوثيق والواتساب
            kyc_keyboard = [
                [InlineKeyboardButton("🔐 توثيق الحساب", url="https://t.me/MetaKYCBot")],
                [InlineKeyboardButton("📱 تواصل معنا عبر واتساب", url="https://wa.me/+967774506423")]
            ]
            
            await update.message.reply_text(
                "🔒 *مرحباً بك!*\n\n"
                "عذراً، لا يمكنك استخدام البوت حتى يتم تفعيل حسابك.\n"
                "🔑 يرجى إدخال رمز التسجيل للمتابعة.\n\n"
                "للحصول على رمز التفعيل:\n"
                "1️⃣ اضغط على زر توثيق الحساب\n"
                "2️⃣ أو تواصل معنا عبر واتساب",
                reply_markup=InlineKeyboardMarkup(kyc_keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTRATION
       
        await release_connection(conn)

        # التحقق من حالة التسجيل للمستخدم الموجود
        if not await is_user_registered(user_id):
            # إضافة أزرار التوثيق والواتساب
            kyc_keyboard = [
                [InlineKeyboardButton("🔐 توثيق الحساب", url="https://t.me/MetaKYCBot")],
                [InlineKeyboardButton("📱 تواصل معنا عبر واتساب", url="https://wa.me/+967774506423")]
            ]
            
            await update.message.reply_text(
                "🔒 *مرحباً بك!*\n\n"
                "عذراً، لا يمكنك استخدام البوت حتى يتم تفعيل حسابك.\n"
                "🔑 يرجى إدخال رمز التسجيل للمتابعة.\n\n"
                "للحصول على رمز التفعيل:\n"
                "1️⃣ اضغط على زر توثيق الحساب\n"
                "2️⃣ أو تواصل معنا عبر واتساب",
                reply_markup=InlineKeyboardMarkup(kyc_keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTRATION

        # التحقق من صلاحية الكود
        registration_code = await get_user_registration_code(user_id)
        if not registration_code:
            kyc_keyboard = [
                [InlineKeyboardButton("🔐 توثيق الحساب", url="https://t.me/MetaKYCBot")],
                [InlineKeyboardButton("📱 تواصل معنا عبر واتساب", url="https://wa.me/+967774506423")]
            ]
            
            await update.message.reply_text(
                "⚠️ *تنبيه!*\n\n"
                "تم إلغاء تفعيل حسابك.\n"
                "🔑 يرجى إدخال رمز تسجيل جديد للمتابعة.\n\n"
                "للحصول على رمز جديد:\n"
                "1️⃣ اضغط على زر توثيق الحساب\n"
                "2️⃣ أو تواصل معنا عبر واتساب",
                reply_markup=InlineKeyboardMarkup(kyc_keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTRATION
           
        # التحقق من وجود طلب نشط للمستخدم
        conn = await get_connection()
        pending_request = await conn.fetchrow("""
            SELECT withdrawal_id, status
            FROM withdrawal_requests 
            WHERE user_id = $1 
            AND status IN ('pending', 'processing')
            AND created_at > NOW() - INTERVAL '15 minutes'
            ORDER BY created_at DESC 
            LIMIT 1
        """, user_id)
        await release_connection(conn)

        # إعداد أزرار الإيداع والسحب الرئيسية
        keyboard = [
            [KeyboardButton("💰 إيداع"), KeyboardButton("💳 سحب")]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            is_persistent=True
        )

        if pending_request:
            if pending_request['status'] == 'pending':
                cancel_keyboard = [[
                    InlineKeyboardButton(
                        "❌ إلغاء الطلب السابق", 
                        callback_data=f"cancel_pending_{pending_request['withdrawal_id']}"
                    )
                ]]
                await update.message.reply_text(
                    "⚠️ *لديك طلب قيد المعالجة*\n\n"
                    "يمكنك إلغاء الطلب السابق والبدء من جديد.",
                    reply_markup=InlineKeyboardMarkup(cancel_keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "⚠️ *لديك طلب قيد المعالجة*\n\n"
                    "يرجى انتظار اكتمال معالجة الطلب الحالي.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            await update.message.reply_text(
                "👋 *مرحباً بك في خدمة الإيداع والسحب!*",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # المستخدم مسجل وليس لديه طلبات نشطة
        await update.message.reply_text(
            "👋 *مرحباً بك في خدمة الإيداع والسحب!*\n\n"
            "• اضغط على زر الإيداع للبدء بعملية إيداع جديدة\n"
            "• اضغط على زر السحب للانتقال إلى بوت السحب",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة بدء المحادثة: {e}")
        await update.message.reply_text(
            "❌ عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى لاحقاً.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
async def handle_cancel_pending(update: Update, context: CallbackContext) -> int:
    """معالجة إلغاء الطلب المعلق"""
    query = update.callback_query
    await query.answer()
    
    try:
        withdrawal_id = query.data.split('_')[2]
        user_id = update.effective_user.id
        
        # تحديث حالة الطلب في قاعدة البيانات
        conn = await get_connection()
        # التحقق من أن الطلب موجود وينتمي للمستخدم نفسه
        request = await conn.fetchrow("""
            SELECT status 
            FROM withdrawal_requests 
            WHERE withdrawal_id = $1 AND user_id = $2
            AND status = 'pending'
        """, withdrawal_id, user_id)

        if not request:
            await release_connection(conn)
            await query.edit_message_text(
                "❌ *لا يمكن إلغاء الطلب*\n"
                "قد يكون الطلب غير موجود أو تم معالجته بالفعل.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # إلغاء الطلب
        await conn.execute("""
            UPDATE withdrawal_requests 
            SET status = 'cancelled',
                cancellation_reason = 'تم الإلغاء من قبل المستخدم'
            WHERE withdrawal_id = $1 
            AND user_id = $2
            AND status = 'pending'
        """, withdrawal_id, user_id)
        await release_connection(conn)

        # عرض زر بدء عملية جديدة
        keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
        await query.edit_message_text(
            "✅ *تم إلغاء الطلب السابق بنجاح*\n\n"
            "يمكنك الآن بدء عملية جديدة.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        
        # تسجيل عملية الإلغاء
        logger.info(f"تم إلغاء الطلب {withdrawal_id} بواسطة المستخدم {user_id}")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في إلغاء الطلب المعلق: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء إلغاء الطلب. الرجاء المحاولة مرة أخرى.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
async def has_pending_request(user_id: int) -> bool:
    """التحقق من وجود طلبات معلقة للمستخدم"""
    try:
        conn = await get_connection()
        async with conn.transaction():
            # إلغاء الطلبات القديمة أولاً
            await conn.execute("""
                UPDATE withdrawal_requests 
                SET status = 'cancelled',
                    cancellation_reason = 'تم الإلغاء تلقائياً لانتهاء المهلة'
                WHERE user_id = $1 
                AND status IN ('pending', 'processing')
                AND created_at < NOW() - INTERVAL '15 minutes'
            """, user_id)

            # ثم التحقق من وجود طلبات حالية
            result = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 
                    FROM withdrawal_requests 
                    WHERE user_id = $1 
                    AND status IN ('pending', 'processing')
                    AND created_at > NOW() - INTERVAL '15 minutes'
                    AND withdrawal_id NOT IN (
                        SELECT withdrawal_id 
                        FROM withdrawal_requests 
                        WHERE status IN ('completed', 'cancelled', 'rejected')
                    )
                )
            """, user_id)

            # في حالة وجود طلب نشط جديد
            if result:
                # جلب معلومات الطلب لإضافتها للسجل
                active_request = await conn.fetchrow("""
                    SELECT withdrawal_id, created_at, status
                    FROM withdrawal_requests 
                    WHERE user_id = $1 
                    AND status IN ('pending', 'processing')
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, user_id)
                if active_request:
                    logger.info(
                        f"طلب نشط للمستخدم {user_id}: "
                        f"withdrawal_id={active_request['withdrawal_id']}, "
                        f"status={active_request['status']}, "
                        f"created_at={active_request['created_at']}"
                    )

        await release_connection(conn)
        return result

    except Exception as e:
        logger.error(f"خطأ في التحقق من الطلبات المعلقة للمستخدم {user_id}: {e}")
        if 'conn' in locals():
            await release_connection(conn)
        return False
        
async def handle_start(update: Update, context: CallbackContext) -> int:
    """معالجة أمر البدء"""
    user_id = update.effective_user.id
    
    try:
        # التحقق من وجود طلبات معلقة
        has_pending = await has_pending_request(user_id)
        if has_pending:
            pending_message = (
                "⚠️ *لديك طلب قيد المعالجة*\n\n"
                "يرجى الانتظار حتى اكتمال معالجة الطلب الحالي.\n"
                "ستتم إعادة تعيين الطلب تلقائياً بعد 15 دقيقة من عدم النشاط."
            )
            await update.message.reply_text(
                pending_message,
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # في حالة عدم وجود طلبات معلقة
        keyboard = [
            [KeyboardButton("💰 إيداع"), KeyboardButton("💳 سحب")]
        ]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            is_persistent=True  # يجعل لوحة المفاتيح دائمة
        )
        
        await update.message.reply_text(
            "👋 *مرحباً بك في خدمة الإيداع والسحب!*\n\n"
            "• اضغط على زر الإيداع للبدء بعملية إيداع جديدة\n"
            "• اضغط على زر السحب للانتقال إلى بوت السحب",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة أمر البدء: {e}")
        await update.message.reply_text(
            "❌ عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى لاحقاً.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END     
async def start_new_process(update: Update, context: CallbackContext) -> int:
    """معالجة ضغطة زر بدء عملية جديدة"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    try:
        # التحقق من التسجيل أولاً
        if not await is_user_registered(user_id):
            # إرسال رسالة جديدة بدلاً من تعديل الرسالة الحالية
            await context.bot.send_message(
                chat_id=user_id,
                text="🔒 *عذراً!*\n\n"
                "لا يمكنك استخدام البوت حتى يتم تفعيل حسابك.\n"
                "🔑 يرجى إدخال رمز التسجيل للمتابعة.",
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTRATION

        # التحقق من وجود طلب نشط
        if await has_pending_request(user_id):
            # إرسال رسالة جديدة بدلاً من تعديل الرسالة الحالية
            await context.bot.send_message(
                chat_id=user_id,
                text="⚠️ *لديك طلب قيد المعالجة*\n\n"
                "يرجى إكمال أو إلغاء الطلب الحالي أولاً.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # إنشاء صف واحد يحتوي على جميع الأزرار
        keyboard = [
            [InlineKeyboardButton(text, callback_data=f"transfer_type_{key}")] for key, text in TRANSFER_TYPES.items()
        ]
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])

        # إرسال رسالة جديدة
        try:
            message = await context.bot.send_message(
                chat_id=user_id,
                text="🌟 *الرجاء اختيار طريقة التحويل:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            
            # تخزين معرف الرسالة في قائمة الرسائل
            if 'messages' not in context.user_data:
                context.user_data['messages'] = []
            context.user_data['messages'].append(message.message_id)
            
        except Exception as e:
            logger.error(f"خطأ في إرسال رسالة جديدة: {e}")
            raise

        return SELECT_TRANSFER_TYPE

    except Exception as e:
        logger.error(f"خطأ في بدء عملية جديدة: {e}")
        # إرسال رسالة جديدة بدلاً من تعديل الرسالة الحالية
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ *حدث خطأ*\n"
            "يرجى المحاولة مرة أخرى لاحقاً.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
        # إنشاء أزرار العملات
       
    except Exception as e:
        logger.error(f"خطأ في بدء عملية جديدة: {e}")
        await query.edit_message_text(
            "❌ *حدث خطأ*\n"
            "يرجى المحاولة مرة أخرى لاحقاً",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

async def cancel(update: Update, context: CallbackContext) -> int:
    """إلغاء العملية وإزالة المستخدم من القائمة النشطة وحذف الرسائل السابقة"""
    user_id = update.effective_user.id
    
    # إزالة المستخدم من القائمة النشطة
    if user_id in active_users:
        del active_users[user_id]

    keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        # حذف الرسالة الحالية التي تحتوي على زر الإلغاء
        if update.callback_query:
            current_message = update.callback_query.message
            if current_message and "✅ تم تنفيذ طلبك بنجاح!" not in (current_message.text or ""):
                try:
                    await current_message.delete()
                except Exception as e:
                    logger.error(f"خطأ في حذف رسالة زر الإلغاء: {e}")

        # حذف الرسائل المخزنة في السياق، باستثناء رسائل النجاح
        if 'messages' in context.user_data:
            for msg_id in context.user_data['messages']:
                try:
                    # نتحقق من محتوى الرسالة قبل حذفها
                    try:
                        msg = await context.bot.get_message(chat_id=user_id, message_id=msg_id)
                        if msg and "✅ تم تنفيذ طلبك بنجاح!" not in (msg.text or ""):
                            await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
                            logger.info(f"تم حذف الرسالة {msg_id}")
                    except Exception as e:
                        # إذا لم نستطع الحصول على الرسالة، نفترض أنها ليست رسالة نجاح ونحاول حذفها
                        await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
                        logger.info(f"تم حذف الرسالة {msg_id}")
                except Exception as e:
                    if "Message to delete not found" in str(e):
                        logger.info(f"الرسالة {msg_id} غير موجودة أو تم حذفها مسبقاً")
                    else:
                        logger.error(f"خطأ في حذف الرسالة {msg_id}: {e}")
            
            # إعادة تعيين قائمة الرسائل
            context.user_data['messages'] = []

        # إرسال رسالة الإلغاء الجديدة
        new_message = await context.bot.send_message(
            chat_id=user_id,
            text="❌ *تم إلغاء العملية*\n\n"
            "يمكنك البدء من جديد بالضغط على الزر أدناه.",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['messages'] = [new_message.message_id]

    except Exception as e:
        logger.error(f"خطأ في عملية الإلغاء: {e}")
        if update.callback_query:
            try:
                await update.callback_query.message.edit_text(
                    "❌ *تم إلغاء العملية*\n\n"
                    "يمكنك البدء من جديد بالضغط على الزر أدناه.",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as edit_error:
                logger.error(f"خطأ في تعديل رسالة الإلغاء: {edit_error}")
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="❌ *تم إلغاء العملية*\n\n"
                        "يمكنك البدء من جديد بالضغط على الزر أدناه.",
                        reply_markup=reply_markup,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as send_error:
                    logger.error(f"خطأ في إرسال رسالة الإلغاء: {send_error}")

    return ConversationHandler.END

async def handle_transfer_type(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار نوع التحويل"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data.replace("transfer_type_", "")
    
    try:
        # تخزين نوع التحويل في السياق
        context.user_data['transfer_type'] = data
        
        if data == 'bank_deposit':
            # عرض قائمة البنوك
            keyboard = [
                [InlineKeyboardButton(bank, callback_data=f"bank_{bank}")]
                for bank in BANKS
            ]
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
            
            await query.edit_message_text(
                "🏦 *الرجاء اختيار المحفظة:*\n"
                "*الى حساب/777891151*\n"
                "*بأسم /محمد احمد محمد الحبيشي*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return SELECT_BANK
            
        elif data == 'name_transfer':
            # الانتقال مباشرة إلى اختيار العملة
            keyboard = [
                [InlineKeyboardButton(currency, callback_data=f"curr_{currency}")]
                for currency in SUPPORTED_CRYPTOCURRENCIES
            ]
            keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
            
            await query.edit_message_text(
                "💰 *الرجاء اختيار العملة الرقمية:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return REQUEST_CURRENCY
            
        elif data == 'kuraimi_transfer':
            # عرض أرقام حسابات الكريمي
            await query.edit_message_text(
                "💳 *حسابات الكريمي:*\n\n"
                "`3086326287`   YER\n"
                "`3086334878`   USD\n"
                "`3086438697`   SAR\n\n"
                "🔹 *الأرقام قابلة للنسخ*\n"
                "🔹 *بأسم /محمود قيس القرشي*\n\n"
                "الرجاء اختيار العملة الرقمية بعد إتمام التحويل:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(currency, callback_data=f"curr_{currency}")]
                    for currency in SUPPORTED_CRYPTOCURRENCIES
                ] + [[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]),
                parse_mode=ParseMode.MARKDOWN
            )
            return REQUEST_CURRENCY
            
    except Exception as e:
        logger.error(f"خطأ في معالجة اختيار نوع التحويل: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ. الرجاء المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 المحاولة مرة أخرى", callback_data="start_new")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

async def handle_bank_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار البنك"""
    query = update.callback_query
    await query.answer()
    
    try:
        # تخزين البنك المختار في السياق
        bank = query.data.replace("bank_", "")
        context.user_data['selected_bank'] = bank
        
        # الانتقال إلى اختيار العملة
        keyboard = [
            [InlineKeyboardButton(currency, callback_data=f"curr_{currency}")]
            for currency in SUPPORTED_CRYPTOCURRENCIES
        ]
        keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
        
        await query.edit_message_text(
            "💰 *الرجاء اختيار العملة الرقمية:*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return REQUEST_CURRENCY
        
    except Exception as e:
        logger.error(f"خطأ في معالجة اختيار البنك: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ. الرجاء المحاولة مرة أخرى.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 المحاولة مرة أخرى", callback_data="start_new")
            ]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

async def send_to_admins(context: CallbackContext, withdrawal_id: str) -> None:
    """إرسال الطلب إلى المشرفين حسب نوع التحويل"""
    try:
        # استرجاع معلومات الطلب من قاعدة البيانات
        withdrawal = await get_withdrawal(withdrawal_id)
        if not withdrawal:
            logger.error(f"لم يتم العثور على الطلب: {withdrawal_id}")
            return

        # تحديد قروب المشرفين حسب نوع التحويل
        transfer_type = context.user_data.get('transfer_type', 'name_transfer')
        logger.info(f"نوع التحويل: {transfer_type}")
        
        # تحديد المجموعة المناسبة
        if transfer_type == 'bank_deposit':
            admin_group = ADMIN_GROUP_ID_2
            logger.info(f"سيتم إرسال الطلب إلى مجموعة الإيداع البنكي: {ADMIN_GROUP_ID_2}")
        elif transfer_type == 'kuraimi_transfer':
            admin_group = ADMIN_GROUP_ID_2
            logger.info(f"سيتم إرسال الطلب إلى مجموعة الإيداع البنكي: {ADMIN_GROUP_ID_2}")
        else:
            admin_group = ADMIN_GROUP_ID
            logger.info(f"سيتم إرسال الطلب إلى مجموعة التحويل عبر الاسم: {ADMIN_GROUP_ID}")

        # إعداد نص الرسالة
        message_text = (
            "🔔 *طلب جديد*\n\n"
            f"💰 *العملة المشفرة:* {withdrawal['crypto_currency']}\n"
            f"💵 *المبلغ المدفوع:* {withdrawal['local_amount']:,.2f} {withdrawal['local_currency_name']}\n"
            f"💱 *المبلغ بالعملة المشفرة:* {withdrawal['crypto_amount']:,.6f} {withdrawal['crypto_currency']}\n"
            f"🌐 *الشبكة:* {withdrawal['network_name']}\n"
            f"🔢 *رقم الحوالة:* {withdrawal['transfer_number']}\n"
        )

        # إضافة معلومات نوع التحويل
        if transfer_type == 'bank_deposit':
            message_text += f"🏦 *نوع التحويل:* {withdrawal['transfer_issuer']}\n"
        elif transfer_type == 'kuraimi_transfer':
            message_text += f"🏦 *نوع التحويل:* {withdrawal['transfer_issuer']}\n"
        else:
            message_text += f"🏦 *نوع التحويل:* تحويل عبر الاسم\n"
            message_text += f"👤 *اسم المرسل:* {withdrawal['sender_name']}\n"
            message_text += f"📱 *رقم الهاتف:* {withdrawal['phone']}\n"

        message_text += (
            f"👛 *عنوان المحفظة:* `{withdrawal['wallet_address']}`\n\n"
            f"💎 *المبلغ النهائي:* {withdrawal['net_amount']:,.6f} {withdrawal['crypto_currency']}\n\n"
            f"🆔 *معرف الطلب:* `{withdrawal_id}`"
        )

        # إنشاء أزرار التأكيد والرفض
        keyboard = [
            [
                InlineKeyboardButton("✅ تأكيد", callback_data=f"admin_confirm_{withdrawal_id}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_{withdrawal_id}")
            ]
        ]

        # إرسال الطلب إلى قروب المشرفين
        await context.bot.send_message(
            chat_id=admin_group,
            text=message_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        logger.info(f"تم إرسال الطلب {withdrawal_id} إلى قروب المشرفين {admin_group}")

    except Exception as e:
        logger.error(f"خطأ في إرسال الطلب للمشرفين: {e}")
        raise

# إضافة دالة لتنظيف المستخدمين غير النشطين
async def cleanup_inactive_users():
    """تنظيف المستخدمين غير النشطين من القائمة"""
    current_time = datetime.now()
    timeout = timedelta(minutes=30)  # تعيين مهلة 30 دقيقة
    
    to_remove = []
    for user_id, start_time in active_users.items():
        if current_time - start_time > timeout:
            to_remove.append(user_id)
    
    for user_id in to_remove:
        del active_users[user_id]

# تعريف المنطقة الزمنية لليمن
YEMEN_TZ = pytz.timezone('Asia/Aden')

def format_time_yemen(dt):
    """تنسيق الوقت بتوقيت اليمن ونظام 12 ساعة"""
    yemen_time = dt.astimezone(YEMEN_TZ)
    return yemen_time.strftime('%Y-%m-%d %I:%M:%S %p')

async def handle_registration(update: Update, context: CallbackContext) -> int:
    """معالجة التحقق من رمز التسجيل"""
    user_id = update.effective_user.id
    registration_code = update.message.text.strip()
    
    try:
        if await verify_registration_code(user_id, registration_code):
            # التسجيل ناجح
            keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "✅ *تم التسجيل بنجاح!*\n\n"
                "يمكنك الآن بدء عملية جديدة بالضغط على الزر أدناه.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END
        else:
            # كود غير صحيح
            await update.message.reply_text(
                "❌ *رمز التسجيل غير صحيح أو مستخدم!*\n\n"
                "🔑 يرجى إدخال رمز تسجيل صحيح للمتابعة\n\n"
                "📞 أو التواصل مع الدعم عبر الواتساب:\n"
                "`+967 774506423`",
                parse_mode=ParseMode.MARKDOWN
            )
            return REGISTRATION

    except Exception as e:
        logger.error(f"خطأ في التحقق من كود التسجيل: {e}")
        await update.message.reply_text(
            "❌ *عذراً، حدث خطأ*\n"
            "الرجاء المحاولة مرة أخرى لاحقاً.",
            parse_mode=ParseMode.MARKDOWN
        )
        return REGISTRATION

async def handle_currency_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار العملة المشفرة"""
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    if data[0] == CANCEL:
        return await cancel(update, context)
    elif data[0] == BACK:
        # لا يوجد مرحلة سابقة للعودة إليها من المرحلة الأولى
        await query.answer()
        await query.edit_message_text(
        "👋  خدمة الايداع التلقائي من  ميتابت *مرحباً بك في!*\n\n"
            "💰 الرجاء اختيار العملة الرقميه:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(currency, callback_data=f"curr_{currency}")]
                for currency in SUPPORTED_CRYPTOCURRENCIES
            ] + [[InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")]]),
            parse_mode='Markdown'
        )
        return REQUEST_CURRENCY

    crypto_currency = data[1]
    context.user_data['crypto_currency'] = crypto_currency

    # نتابع بالطريقة العادية
    networks = SUPPORTED_NETWORKS.get(crypto_currency, {})
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"net_{code}")]
        for code, name in networks.items()
    ]
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")])

    await query.edit_message_text(
        f"✅ تم اختيار عملة *{crypto_currency}*\n\n"
        "🌐 الرجاء اختيار شبكة التحويل:\n"
        "💡 في حال كان الايداع لمنصة بينانس Binance يفضل اختيار شبكة Bep20 لتجنب رسوم الشبكه ",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    return REQUEST_NETWORK

async def handle_network_selection(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار الشبكة"""
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    if data[0] == CANCEL:
        return await cancel(update, context)
    elif data[0] == BACK:
        # العودة إلى اختيار العملة المشفرة
        return await handle_currency_selection(update, context)

    network_code = data[1]
    crypto_currency = context.user_data.get('crypto_currency')
    network_name = SUPPORTED_NETWORKS.get(crypto_currency, {}).get(network_code, "غير معروف")

    context.user_data['network_code'] = network_code
    context.user_data['network_name'] = network_name

    # عرض اختيار العملة المحلية
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"local_{code}")]
        for code, name in LOCAL_CURRENCIES.items()
    ]
    # إضافة أزرار "رجوع" و"إلغاء"
    keyboard.append([
        InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
    ])

    await query.edit_message_text(
        f"✅ تم اختيار شبكة *{network_name}*\n\n"
        "💱 الرجاء اختيار عملة التحويل:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return REQUEST_LOCAL_CURRENCY

async def handle_local_currency_selection(update: Update, context: CallbackContext) -> int:
    logger.info("=== بداية اختيار العملة المحلية ===")
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    local_currency = data[1].upper()
    local_currency_name = LOCAL_CURRENCIES.get(local_currency)
    
    context.user_data['local_currency'] = local_currency
    context.user_data['local_currency_name'] = local_currency_name
    context.user_data['current_state'] = REQUEST_AMOUNT
    
    logger.info(f"العملة المحلية المختارة: {local_currency}")
    logger.info(f"اسم العملة المحلية: {local_currency_name}")
    logger.info(f"الحالة الحالية: {context.user_data.get('current_state')}")
    logger.info(f"بيانات المستخدم: {context.user_data}")

    # Get exchange rates with explicit USDT handling
    exchange_rates = await get_exchange_rates()
    if 'USDT' not in exchange_rates:
        exchange_rates['USDT'] = 1.0
        logger.info("تم تعيين سعر صرف USDT إلى 1.0")
    
    current_rate = exchange_rates.get(local_currency)
    if not current_rate:
        logger.error(f"سعر الصرف غير متوفر للعملة {local_currency}")
        await query.edit_message_text(
            "⚠️ عذراً، سعر الصرف غير متوفر حالياً. الرجاء المحاولة لاحقاً.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
    
    message = (
        f"✅ تم اختيار *{local_currency_name}*\n\n"
        f"📊 *سعر الصرف الحالي:*\n"
        f"1 USD = {current_rate:,.2f} {local_currency_name}\n\n"
        f"💵* الرجاء إدخال المبلغ بــال{local_currency_name}:*\n"
    )

    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )
    
    logger.info("=== نهاية اختيار العملة المحلية ===")
    logger.info("انتظار إدخال المبلغ...")
    return REQUEST_AMOUNT

async def validate_withdrawal_amount(context: CallbackContext) -> Tuple[bool, str]:
    """التحقق مما إذا كان المبلغ يقع ضمن الحدود المحددة."""
    local_amount = context.user_data.get('local_amount')
    crypto_currency = context.user_data.get('crypto_currency')
    local_currency = context.user_data.get('local_currency')

    # الحصول على الحدود بالدولار الأمريكي من قاعدة البيانات
    min_withdrawal_usd_str = await get_setting('MIN_WITHDRAWAL_USD')
    max_withdrawal_usd_str = await get_setting('MAX_WITHDRAWAL_USD')

    try:
        min_withdrawal_usd = float(min_withdrawal_usd_str) if min_withdrawal_usd_str else 1.0
        max_withdrawal_usd = float(max_withdrawal_usd_str) if max_withdrawal_usd_str else 10000.0
    except ValueError:
        min_withdrawal_usd = 1.0
        max_withdrawal_usd = 10000.0
        logger.warning("حدود السحب غير صحيحة في قاعدة البيانات. استخدام القيم الافتراضية.")

    logger.info(f"التحقق من السحب: min_withdrawal_usd={min_withdrawal_usd}, max_withdrawal_usd={max_withdrawal_usd}")

    # الحصول على سعر الصرف للعملة المحلية إلى الدولار الأمريكي
    exchange_rate = context.bot_data.get('EXCHANGE_RATES', {}).get(local_currency, 1)

    # تحويل الحدود من USD إلى العملة المحلية
    min_withdrawal_local = min_withdrawal_usd * exchange_rate
    max_withdrawal_local = max_withdrawal_usd * exchange_rate

    logger.info(f"الحدود المحولة: min_withdrawal_local={min_withdrawal_local}, max_withdrawal_local={max_withdrawal_local}")

    # التحقق من الحدود العامة
    if local_amount < min_withdrawal_local:
        return False, f"❌ المبلغ أدنى من الحد الأدنى للسحب وهو {min_withdrawal_local:,.2f} {context.user_data['local_currency_name']} ({min_withdrawal_usd} USD)."
    if local_amount > max_withdrawal_local:
        return False, f"❌ المبلغ أعلى من الحد الأقصى للسحب وهو {max_withdrawal_local:,.2f} {context.user_data['local_currency_name']} ({max_withdrawal_usd} USD)."

    # التحقق من الحدود الخاصة بالعملة المشفرة إذا كانت محددة
    currency_limits = WITHDRAWAL_LIMITS.get(crypto_currency)
    if currency_limits:
        crypto_amount = context.user_data.get('crypto_amount')
        if crypto_amount < currency_limits['min']:
            return False, f"❌ المبلغ بالـ {crypto_currency} أدنى من الحد الأدنى المسموح به وهو {currency_limits['min']}."
        if crypto_amount > currency_limits['max']:
            return False, f"❌ المبلغ بالـ {crypto_currency} أعلى من الحد الأقصى المسموح به وهو {currency_limits['max']}."

    return True, ""
async def handle_amount_wrapper(update: Update, context: CallbackContext) -> int:
    """دالة غلاف لتتبع معالجة المبلغ"""
    logger.info("=== بداية معالجة المبلغ ===")
    logger.info(f"الحالة الحالية: {context.user_data.get('current_state')}")
    logger.info(f"نوع التحديث: {type(update)}")
    if hasattr(update, 'message'):
        logger.info(f"نص الرسالة: {update.message.text if update.message else 'لا يوجد نص'}")
    logger.info(f"بيانات المستخدم: {context.user_data}")
    
    try:
        result = await handle_amount(update, context)
        logger.info(f"=== نتيجة المعالجة: {result} ===")
        return result
    except Exception as e:
        logger.error(f"=== خطأ في معالجة المبلغ: {e} ===")
        raise

async def handle_amount(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال المبلغ من قبل المستخدم"""
    logger.info("=== بدء معالجة المبلغ المدخل ===")
    logger.info(f"نوع التحديث: {type(update)}")
    logger.info(f"بيانات المستخدم الحالية: {context.user_data}")
    
    # التحقق من أن الحالة الحالية هي REQUEST_AMOUNT
    current_state = context.user_data.get('current_state')
    logger.info(f"الحالة الحالية: {current_state}")

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        logger.info(f"تم استلام callback query: {data}")
        if data == CANCEL:
            return await cancel(update, context)
        elif data == BACK:
            return await handle_local_currency_selection(update, context)

    if not update.message or not update.message.text:
        logger.error("لا يوجد نص في الرسالة")
        return REQUEST_AMOUNT

    logger.info(f"النص المستلم: {update.message.text}")
    # تحديث الحالة الحالية
    context.user_data['current_state'] = REQUEST_AMOUNT
    logger.info("تم تحديث الحالة إلى REQUEST_AMOUNT")
    
    # سجلات إضافية للتتبع
    logger.info(f"نوع التحديث: {type(update)}")
    logger.info(f"محتوى التحديث: {update.to_dict() if hasattr(update, 'to_dict') else update}")
    if hasattr(update, 'message'):
        logger.info(f"نص الرسالة: {update.message.text if update.message else 'لا يوجد نص'}")
    logger.info(f"بيانات المستخدم: {context.user_data}")
    
    # أخذ أول قيمة في حال وجود عدة قيم
    input_text = update.message.text.strip()
    first_value = input_text.split()[0] if input_text else ""
    local_amount_text = first_value.replace(',', '').replace(' ', '')
    logger.info(f"النص المدخل: {input_text}")
    logger.info(f"القيمة المستخدمة: {local_amount_text}")
    
    if not local_amount_text:
        raise ValueError("المبلغ لا يمكن أن يكون فارغاً")
            
    if not all(c.isdigit() or c == '.' for c in local_amount_text):
        raise ValueError("المبلغ يجب أن يحتوي على أرقام ونقطة عشرية فقط")
            
    if local_amount_text.count('.') > 1:
        raise ValueError("المبلغ يحتوي على أكثر من نقطة عشرية")
            
    local_amount = float(local_amount_text)
    if local_amount <= 0:
        raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    try:
        local_amount = float(local_amount_text)
        logger.info(f"تم تحويل المبلغ إلى: {local_amount}")
        if local_amount <= 0:
            raise ValueError("المبلغ يجب أن يكون أكبر من الصفر")
    except ValueError as e:
        logger.error(f"خطأ في تحويل المبلغ: {e}")
        raise

    # حفظ المبلغ بالعملة المحلية والحالة الحالية
    context.user_data['local_amount'] = local_amount
    context.user_data['current_state'] = REQUEST_AMOUNT

    # الحصول على العملات من بيانات المستخدم
    local_currency = context.user_data.get('local_currency')
    crypto_currency = context.user_data.get('crypto_currency')
    exchange_rates = await get_exchange_rates()
    usd_rate = exchange_rates.get(local_currency)
    if not usd_rate:
        raise Exception(f"سعر الصرف للعملة المحلية {local_currency} غير متوفر.")
    usd_amount = local_amount / usd_rate

    # التحقق من الحد الأقصى للسحب بالدولار الأمريكي
    network_code = context.user_data.get('network_code', '').lower()
    is_bep20 = any(x in network_code for x in ['bep20', 'bsc', 'bnb'])
    logger.info(f"Network code: {network_code}, Is BEP20: {is_bep20}")

    if is_bep20:
        logger.info("استخدام حدود BEP20")
        min_withdrawal = float(await get_setting('BEP20_MIN_WITHDRAWAL_USD') or 20.0)
        max_withdrawal = float(await get_setting('BEP20_MAX_WITHDRAWAL_USD') or 5000.0)
    else:
        logger.info("استخدام الحدود العامة")
        min_withdrawal = float(await get_setting('MIN_WITHDRAWAL_USD') or 11.0)
        max_withdrawal = float(await get_setting('MAX_WITHDRAWAL_USD') or 1000.0)

    logger.info(f"الحدود المطبقة - الأدنى: {min_withdrawal}, الأقصى: {max_withdrawal}, المبلغ: {usd_amount}")

    # التحقق من الحدود
    if usd_amount < min_withdrawal:
        error_message = (
            f"❌ *المبلغ أقل من الحد الأدنى للسحب*\n\n"
            f"الحد الأدنى هو {min_withdrawal:.2f} دولار\n"
            f"ما يعادل {min_withdrawal * exchange_rates.get(local_currency, 1):,.2f} "
            f"{context.user_data.get('local_currency_name', local_currency)}"
        )
        keyboard = [[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
        await update.message.reply_text(
            error_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REQUEST_AMOUNT

    if usd_amount > max_withdrawal:
        error_message = (
            f"❌ *المبلغ أكبر من الحد الأقصى للسحب*\n\n"
            f"الحد الأقصى هو {max_withdrawal:.2f} دولار\n"
            f"ما يعادل {max_withdrawal * exchange_rates.get(local_currency, 1):,.2f} "
            f"{context.user_data.get('local_currency_name', local_currency)}"
        )
        keyboard = [[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]]
        await update.message.reply_text(
            error_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REQUEST_AMOUNT

    # تحويل المبلغ إلى العملة المشفرة
    if crypto_currency == 'USDT':
        crypto_amount = usd_amount
    else:
        crypto_rate = exchange_rates.get(crypto_currency)
        if not crypto_rate:
            if crypto_currency.upper() == 'USDT':
                crypto_rate = 1.0
                logger.info("تم تعيين سعر صرف USDT إلى 1.0 تلقائيًا.")
            else:
                raise Exception(f"سعر الصرف للعملة المشفرة {crypto_currency} غير متوفر.")
        crypto_amount = usd_amount / crypto_rate

    # حفظ المبلغ بالعملة المشفرة
    context.user_data['crypto_amount'] = round(crypto_amount, 6)

    # الحصول على إعدادات العمولة
    commission_threshold = float(await get_setting('COMMISSION_THRESHOLD_USD') or 30.0)
    fixed_commission = float(await get_setting('FIXED_COMMISSION_USD') or 1.0)
    percentage_rate = float(await get_setting('PERCENTAGE_COMMISSION_RATE') or 0.03)

    # حساب العمولة بناءً على المبلغ
    if usd_amount <= commission_threshold:
        # عمولة ثابتة للمبالغ الصغيرة
        commission_amount = fixed_commission
        net_amount = usd_amount - fixed_commission
        commission_type = "ثابتة"
        commission_display = f"{fixed_commission:,.2f} USD"
    else:
        # عمولة نسبية للمبالغ الكبيرة
        commission_multiplier = 1 + percentage_rate  # مثلاً: 1.03 للعمولة 3%
        net_amount = usd_amount / commission_multiplier  # المبلغ النهائي المستلم
        commission_amount = usd_amount - net_amount  # قيمة العمولة
        commission_type = "نسبية"
        commission_display = f"{percentage_rate*100}%"

    # حفظ القيم في context
    context.user_data['commission_amount'] = round(commission_amount, 6)
    context.user_data['net_amount'] = round(net_amount, 6)

    # التحقق من الحدود الخاصة بالعملة المشفرة إذا كانت محددة
    currency_limits = WITHDRAWAL_LIMITS.get(crypto_currency)
    if currency_limits:
        if crypto_amount < currency_limits['min']:
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")]
            ]
            error_message = f"❌ المبلغ بالـ {crypto_currency} أدنى من الحد الأدنى المسموح به وهو {currency_limits['min']}."
            await update.message.reply_text(
                error_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return REQUEST_AMOUNT
        if crypto_amount > currency_limits['max']:
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")]
            ]
            error_message = f"❌ المبلغ بالـ {crypto_currency} أعلى من الحد الأقصى المسموح به وهو {currency_limits['max']}."
            await update.message.reply_text(
                error_message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return REQUEST_AMOUNT

    # إعداد رسالة التأكيد للمستخدم لطلب رقم الحوالة
    transfer_type = context.user_data.get('transfer_type')
    if transfer_type == 'bank_deposit':
        success_message = (
            f"💰 *تفاصيل التحويل:*\n\n"
            f"• المبلغ بالـ {context.user_data.get('local_currency_name', local_currency)}: {local_amount:,.2f}\n"
            f"• بالـ دولار: {usd_amount:,.6f}$\n"
            f"• العموله{commission_display}\n"
            f"• بالعملة المشفرة: {net_amount:,.6f} {crypto_currency}\n\n"
            f" {context.user_data.get('selected_bank', '')}\n"
            "🔢 *الرجاء إدخال رقم الحوالة او رمز العمليه :*\n\n"
        )
    elif transfer_type == 'kuraimi_transfer':
        success_message = (
            f"💰 *تفاصيل التحويل:*\n\n"
            f"• المبلغ بالـ {context.user_data.get('local_currency_name', local_currency)}: {local_amount:,.2f}\n"
            f"• بالـ دولار: {usd_amount:,.6f}$\n"
            f"• العموله{commission_display}\n"
            f"• بالعملة المشفرة: {net_amount:,.6f} {crypto_currency}\n\n"
            "🔢 *الرجاء إدخال رقم المرجع الذي يبدا بFT :*"
        )
    else:
        success_message = (
            f"💰 *تفاصيل التحويل:*\n\n"
            f"• المبلغ بالـ {context.user_data.get('local_currency_name', local_currency)}: {local_amount:,.2f}\n"
            f"• بالـ دولار: {usd_amount:,.6f}$\n"
            f"• العموله{commission_display}\n"
            f"• بالعملة المشفرة: {net_amount:,.6f} {crypto_currency}\n\n"
            "🔢 *الرجاء إدخال رقم الحوالة او رمز العمليه :*"
        )

    keyboard = [
        [InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")]
    ]

    # تحديث الحالة الحالية قبل الانتقال
    context.user_data['current_state'] = REQUEST_TRANSFER_NUMBER
    logger.info("تم الانتقال إلى طلب رقم الحوالة")
    
    await update.message.reply_text(
        success_message,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    return REQUEST_TRANSFER_NUMBER

async def handle_transfer_number(update: Update, context: CallbackContext) -> int:
    crypto_currency = context.user_data.get('crypto_currency')
    network_name = context.user_data.get('network_name')
    """معالجة إدخال رقم الحوالة"""
    logger.info("=== بدء معالجة رقم الحوالة ===")
    logger.info(f"نوع التحديث: {type(update)}")
    logger.info(f"بيانات المستخدم: {context.user_data}")
    
    # التحقق من أن الحالة الحالية هي REQUEST_TRANSFER_NUMBER
    current_state = context.user_data.get('current_state')
    logger.info(f"الحالة الحالية: {current_state}")
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        logger.info(f"تم استلام callback query: {data}")
        if data == CANCEL:
            return await cancel(update, context)
        elif data == BACK:
            return await handle_amount(update, context)

    if not update.message or not update.message.text:
        logger.error("لا يوجد نص في الرسالة")
        return REQUEST_TRANSFER_NUMBER

    transfer_number = update.message.text.strip()
    logger.info(f"رقم الحوالة المدخل: {transfer_number}")
    context.user_data['transfer_number'] = transfer_number
    
    # التحقق من نوع التحويل
    transfer_type = context.user_data.get('transfer_type')
    selected_bank = context.user_data.get('selected_bank')
    
    if transfer_type == 'bank_deposit' and selected_bank:
        # في حالة الإيداع عبر المحفظة المالية، نضع اسم المحفظة كجهة إصدار
        context.user_data['transfer_issuer'] = selected_bank
        # طلب عنوان المحفظة
        keyboard = [
            [
                InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
            ]
        ]
        
        await update.message.reply_text(
        f"👛 الرجاء إدخال عنوان محفظة {crypto_currency}:\n\n"
        f"🌐 *الشبكة المختارة:* {network_name}\n\n"
        "⚠️ *تنبيه:* تأكد من أن عنوان المحفظة متوافق مع الشبكة المختارة\n"
        "لتجنب فقدان الأموال.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['current_state'] = REQUEST_WALLET_ADDRESS
        return REQUEST_WALLET_ADDRESS
    elif transfer_type == 'kuraimi_transfer':
        # في حالة التحويل عبر الكريمي، نضع الكريمي كجهة إصدار
        context.user_data['transfer_issuer'] = "الكريمي"
        # إضافة القيم الافتراضية للحقول المحذوفة
        context.user_data['sender_name'] = "غير متاح"
        context.user_data['phone'] = "غير متاح"
        
        # طلب عنوان المحفظة
        keyboard = [
            [
                InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
            ]
        ]
        
        await update.message.reply_text(
        f"👛 الرجاء إدخال عنوان محفظة {crypto_currency}:\n\n"
        f"🌐 *الشبكة المختارة:* {network_name}\n\n"
        "⚠️ *تنبيه:* تأكد من أن عنوان المحفظة متوافق مع الشبكة المختارة\n"
        "لتجنب فقدان الأموال.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['current_state'] = REQUEST_WALLET_ADDRESS
        return REQUEST_WALLET_ADDRESS
    else:
        # في حالة التحويل عبر الاسم، نطلب جهة الإصدار
        context.user_data['current_state'] = REQUEST_TRANSFER_ISSUER
        keyboard = [
            [
                InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
            ]
        ]
        await update.message.reply_text(
            "🏦 *الرجاء تحديد الجهه الصادرة منها الحوالة المالية* (.....النجم-امتياز- كريمي)",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return REQUEST_TRANSFER_ISSUER

# إضافة معالج جديد لجهة إصدار الحوالة
async def handle_transfer_issuer(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال جهة إصدار الحوالة"""
    logger.info("=== بدء معالجة جهة إصدار الحوالة ===")
    logger.info(f"نوع التحديث: {type(update)}")
    logger.info(f"بيانات المستخدم: {context.user_data}")
    
    # التحقق من أن الحالة الحالية هي REQUEST_TRANSFER_ISSUER
    current_state = context.user_data.get('current_state')
    logger.info(f"الحالة الحالية: {current_state}")
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        logger.info(f"تم استلام callback query: {data}")
        if data == CANCEL:
            return await cancel(update, context)
        elif data == BACK:
            return await handle_transfer_number(update, context)

    if not update.message or not update.message.text:
        logger.error("لا يوجد نص في الرسالة")
        return REQUEST_TRANSFER_ISSUER

    # تخزين الرسالة الحالية للحذف لاحقاً
    if 'messages' not in context.user_data:
        context.user_data['messages'] = []
    context.user_data['messages'].append(update.message.message_id)

    transfer_issuer = update.message.text.strip()
    logger.info(f"جهة الإصدار المدخلة: {transfer_issuer}")
    
    # التحقق من صحة المدخلات
    if len(transfer_issuer) < 2:
        # إرسال رسالة الخطأ وتخزين معرفها
        error_message = await update.message.reply_text(
            "❌ جهة الإصدار غير صحيح . الرجاء إدخال جهة إصدار صحيحة:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
            ]])
        )
        context.user_data['messages'].append(error_message.message_id)
        return REQUEST_TRANSFER_ISSUER

    context.user_data['transfer_issuer'] = transfer_issuer
    context.user_data['current_state'] = REQUEST_WALLET_ADDRESS
    logger.info(f"تم حفظ جهة الإصدار: {transfer_issuer}")
    logger.info("تحديث الحالة إلى REQUEST_WALLET_ADDRESS")
    
    # إضافة القيم الافتراضية للحقول المحذوفة
    context.user_data['sender_name'] = "غير متاح"
    context.user_data['phone'] = "غير متاح"

    # الحصول على العملة والشبكة
    crypto_currency = context.user_data.get('crypto_currency')
    network_name = context.user_data.get('network_name')
    logger.info(f"العملة المشفرة: {crypto_currency}")
    logger.info(f"الشبكة: {network_name}")
    # طلب عنوان المحفظة
    keyboard = [
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
        ]
    ]
    wallet_message = (
        f"👛 الرجاء إدخال عنوان محفظة {crypto_currency}:\n\n"
        f"🌐 *الشبكة المختارة:* {network_name}\n\n"
        "⚠️ *تنبيه:* تأكد من أن عنوان المحفظة متوافق مع الشبكة المختارة\n"
        "لتجنب فقدان الأموال."
    )
    await update.message.reply_text(
        wallet_message,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REQUEST_WALLET_ADDRESS

async def handle_sender_name(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال اسم المرسل"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        if data == CANCEL:
            return await cancel(update, context)
        elif data == BACK:
            return await handle_transfer_number(update, context)

    sender_name = update.message.text.strip()
    context.user_data['sender_name'] = sender_name

    keyboard = [
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
        ]
    ]

    await update.message.reply_text(
        "📱 الرجاء إدخال رقم هاتفك:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REQUEST_WALLET_ADDRESS

async def handle_phone(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال رقم الهاتف"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        if data == CANCEL:
            return await cancel(update, context)
        elif data == BACK:
            return await handle_sender_name(update, context)

    phone = update.message.text.strip()
    context.user_data['phone'] = phone

    crypto_currency = context.user_data.get('crypto_currency')
    keyboard = [
        [
            InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
        ]
    ]

    await update.message.reply_text(
        f"👛 الرجاء إدخال عنوان محفظة {crypto_currency}:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return REQUEST_WALLET_ADDRESS

async def handle_wallet_address(update: Update, context: CallbackContext) -> int:
    """معالجة إدخال عنوان المحفظة"""
    logger.info("=== بدء معالجة عنوان المحفظة ===")
    logger.info(f"نوع التحديث: {type(update)}")
    logger.info(f"بيانات المستخدم: {context.user_data}")
    
    # التحقق من أن الحالة الحالية هي REQUEST_WALLET_ADDRESS
    current_state = context.user_data.get('current_state')
    logger.info(f"الحالة الحالية: {current_state}")
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        logger.info(f"تم استلام callback query: {data}")
        if data == CANCEL:
            return await cancel(update, context)
        elif data == BACK:
            return await handle_transfer_issuer(update, context)

    if not update.message or not update.message.text:
        logger.error("لا يوجد نص في الرسالة")
        return REQUEST_WALLET_ADDRESS

    # تخزين الرسالة الحالية للحذف لاحقاً
    if 'messages' not in context.user_data:
        context.user_data['messages'] = []
    context.user_data['messages'].append(update.message.message_id)

    wallet_address = update.message.text.strip()
    network_code = context.user_data.get('network_code')
    logger.info(f"عنوان المحفظة المدخل: {wallet_address}")
    logger.info(f"رمز الشبكة: {network_code}")
    
    # التحقق من البادئة 0x للشبكات المتوافقة مع EVM
    if network_code in ['BSC', 'ETH', 'ARBITRUM', 'POLYGON', 'OPTIMISM', 'AVAX']:
        if not wallet_address.startswith('0x'):
            keyboard = [
                [
                    InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
                ]
            ]
            error_message = await update.message.reply_text(
                "❌ يجب أن يبدأ العنوان بـ '0x'\n\n"
                f"👛 الرجاء إدخال عنوان محفظة {context.user_data['crypto_currency']} صحيح:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            context.user_data['messages'].append(error_message.message_id)
            return REQUEST_WALLET_ADDRESS

    context.user_data['current_state'] = CONFIRMATION

    # التحقق من صحة عنوان المحفظة
    is_valid, message = wallet_validator.validate_wallet_address(wallet_address, network_code)
    
    if not is_valid:
        keyboard = [
            [
                InlineKeyboardButton("❌ إلغاء", callback_data=f"{CANCEL}")
            ]
        ]
        
        # إرسال رسالة الخطأ وتخزين معرفها
        error_message = await update.message.reply_text(
            f"{message}\n\n"
            f"👛 الرجاء إدخال عنوان محفظة {context.user_data['crypto_currency']} صحيح:",
            parse_mode='Markdown',
            
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        context.user_data['messages'].append(error_message.message_id)
        return REQUEST_WALLET_ADDRESS

    context.user_data['wallet_address'] = wallet_address
    user_id = update.effective_user.id
    context.user_data['user_id'] = user_id

    # الحصول على المبلغ بالدولار
    local_currency = context.user_data['local_currency']
    exchange_rates = await get_exchange_rates()
    usd_amount = context.user_data['local_amount'] / exchange_rates.get(local_currency, 1)

    # الحصول على إعدادات العمولة
    commission_threshold = float(await get_setting('COMMISSION_THRESHOLD_USD') or 30.0)
    fixed_commission = float(await get_setting('FIXED_COMMISSION_USD') or 1.0)
    percentage_rate = float(await get_setting('PERCENTAGE_COMMISSION_RATE') or 0.03)

    # حساب العمولة بناءً على المبلغ
    if usd_amount <= commission_threshold:
        # عمولة ثابتة للمبالغ الصغيرة
        commission_amount = fixed_commission
        net_amount = usd_amount - fixed_commission
        commission_type = "ثابتة"
        commission_display = f"{fixed_commission:,.2f} USD"
    else:
        # عمولة نسبية للمبالغ الكبيرة
        commission_multiplier = 1 + percentage_rate  # مثلاً: 1.03 للعمولة 3%
        net_amount = usd_amount / commission_multiplier  # المبلغ النهائي المستلم
        commission_amount = usd_amount - net_amount  # قيمة العمولة
        commission_type = "نسبية"
        commission_display = f"{percentage_rate*100}%"

    # حفظ القيم في context
    context.user_data['commission_amount'] = round(commission_amount, 6)
    context.user_data['net_amount'] = round(net_amount, 6)

    confirmation_message = (
    "📋 *مراجعة تفاصيل المعاملة:*\n\n"
    f"💰 *العملة المشفرة:* {context.user_data['crypto_currency']}\n"
    f"💵 *المبلغ المدفوع:* {context.user_data['local_amount']:,.2f} {context.user_data['local_currency_name']}\n"
    f"🌐 *الشبكة:* {context.user_data['network_name']}\n"
    f"🔢 *رقم الحوالة:* {context.user_data['transfer_number']}\n"
    f"👛 *عنوان المحفظة:* `{wallet_address}`\n\n"
    f"💸 *العمولة ({commission_type}):* {commission_display}\n"
    f"• *قيمة العمولة:* {commission_amount:,.6f} USDT\n"
    f"💎 *المبلغ النهائي بعد خصم العمولة:*\n"
    f"• *{net_amount:,.6f} USDT*\n\n"
    "⚠️ **تحذير:** العملات الرقمية المحوَّلة *غير قابلة للاسترجاع.*\n"
    "أنت تتحمل كامل المسؤولية عن **عنوان المحفظه المرسل لها** ومعلومات التحويل.\n"
    "ولا نتحمّل أي مسؤولية عن أي **خسارة** أو **فقدان للأموال**.\n"
    "كما أننا نخلي مسؤوليتنا بالكامل من أي تعاملات أو التزامات بين المرسل والمستلم."
)



    # توليد معرف سحب فريد
    withdrawal_id = str(uuid.uuid4())
    context.user_data['withdrawal_id'] = withdrawal_id

    keyboard = [
        [
            InlineKeyboardButton("✅ تأكيد وإرسال", callback_data=f"confirm_{withdrawal_id}"),
            InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
        ]
    ]

    # تخزين الرسالة الحالية للحذف لاحقاً
    if 'messages' not in context.user_data:
        context.user_data['messages'] = []
    
    # إضافة الرسالة الحالية لقائمة الرسائل
    if update.message:
        context.user_data['messages'].append(update.message.message_id)

    await update.message.reply_text(
        confirmation_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CONFIRMATION
async def handle_user_confirmation(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id

        # Get or create lock for this user
        if user_id not in _confirmation_locks:
            _confirmation_locks[user_id] = Lock()
        
        # Try to acquire the lock
        if _confirmation_locks[user_id].locked():
            await query.edit_message_text(
                "⚠️ يتم معالجة طلبك حالياً، يرجى الانتظار...",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        async with _confirmation_locks[user_id]:
            data = query.data.split('_')
            action = data[0]

            if action == "confirm":
                withdrawal_id = data[1]

                try:
                    # Check if withdrawal already exists
                    existing_withdrawal = await get_withdrawal(withdrawal_id)
                    if existing_withdrawal:
                        await query.edit_message_text(
                            "⚠️ تم معالجة هذا الطلب مسبقاً. يرجى بدء طلب جديد.",
                            parse_mode=ParseMode.MARKDOWN
                        )
                        return ConversationHandler.END

                    # Get registration code
                    registration_code = await get_user_registration_code(user_id)
                    context.user_data['registration_code'] = registration_code
                    
                    # Check data validity
                    if not context.user_data.get('local_amount') or not context.user_data.get('transfer_number'):
                        raise ValueError("بيانات غير مكتملة")

                    # Save withdrawal data with transfer type
                    withdrawal_data = context.user_data.copy()
                    withdrawal_data['transfer_type'] = context.user_data.get('transfer_type', 'name_transfer')
                    await save_withdrawal(withdrawal_id, withdrawal_data)

                    # Determine which admin group to send the notification to
                    admin_group = ADMIN_GROUP_ID  # Default group for name transfers
                    if withdrawal_data['transfer_type'] == 'bank_deposit':
                        admin_group = ADMIN_GROUP_ID_2  # Group for bank deposits
                    elif withdrawal_data['transfer_type'] == 'kuraimi_transfer':
                        admin_group = ADMIN_GROUP_ID_2  # Group for kuraimi transfers

                    # Admin notification message
                    admin_message = (
   f"👤 *طلب سحب جديد من المستخدم:* `{user_id}`\n\n"
   f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
   f"💰 *العملة المشفرة:* {context.user_data['crypto_currency']}\n"
   f"💵 *المبلغ المدفوع:* `{context.user_data['local_amount']:,.2f} {context.user_data['local_currency_name']}`\n"
   f"🌐 *الشبكة:* {context.user_data['network_name']}\n"
   f"🔢 *رقم الحوالة:* `{context.user_data['transfer_number']}`\n"
   f"🏦 *جهة الإصدار:* {context.user_data['transfer_issuer']}\n"
   f"⌚️ *وقت الطلب:* {format_time_yemen(datetime.now(timezone.utc))}\n"



                )

                    # Admin keyboard
                    admin_keyboard = [
                        [
                            InlineKeyboardButton("✅ تأكيد", callback_data=f"admin_confirm_{withdrawal_id}"),
                            InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_{withdrawal_id}")
                        ]
                    ]

                    # Send to appropriate admin group based on transfer type
                    admin_notified = False
                    try:
                        # Send to the determined admin group
                        await context.bot.send_message(
                            chat_id=admin_group,  # Using the determined admin group
                            text=admin_message,
                            reply_markup=InlineKeyboardMarkup(admin_keyboard),
                            parse_mode=ParseMode.MARKDOWN
                        )
                        admin_notified = True
                        
                        # Log which group received the notification
                        logger.info(f"تم إرسال الطلب {withdrawal_id} إلى المجموعة {admin_group} (نوع التحويل: {withdrawal_data['transfer_type']})")
                    except Exception as e:
                        logger.error(f"Failed to send to admin group: {e}")

                    # If group send failed, try individual admins
                    if not admin_notified:
                        for admin_id in ADMIN_USER_IDS:
                            try:
                                await context.bot.send_message(
                                    chat_id=admin_id,
                                    text=admin_message,
                                    reply_markup=InlineKeyboardMarkup(admin_keyboard),
                                    parse_mode=ParseMode.MARKDOWN
                                )
                                admin_notified = True
                            except Exception as admin_error:
                                logger.error(f"Failed to send to admin {admin_id}: {admin_error}")

                    # User confirmation message (text only)
                    user_message = (
                        "✅ *تم إرسال طلبك بنجاح!*\n\n"
                        f"💰 *المبلغ:* {context.user_data['local_amount']:,.2f} {context.user_data['local_currency_name']}\n"
                        f"🔢 *رقم الحوالة:* {context.user_data['transfer_number']}\n"
                        "📝 *حالة الطلب:* قيد المراجعة.....\n\n"
                        "⏱ يرجى الانتظار..."
                    )

                    # Send text-only message to user and store its ID
                    new_message = await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text=user_message,
                        parse_mode=ParseMode.MARKDOWN
                    )
                    # Store both message IDs for later use
                    context.user_data['last_bot_message'] = new_message.message_id
                    context.user_data['initial_message_id'] = new_message.message_id

                    # Delete the previous message
                    await query.delete_message()

                    # Clean up active users
                    if user_id in active_users:
                        del active_users[user_id]

                    return ConversationHandler.END

                except Exception as e:
                    logger.error(f"Error in confirmation handler: {e}")
                    await query.edit_message_text(
                        "❌ حدث خطأ أثناء معالجة طلبك. الرجاء المحاولة مرة أخرى.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return ConversationHandler.END

    except Exception as e:
        logger.error(f"Unexpected error in confirmation: {e}")
        return ConversationHandler.END

# في ملف confirmation_handler.py

async def handle_admin_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد المشرف"""
    query = update.callback_query
    await query.answer()

    # التحقق من أن المستخدم مشرف
     

    # استخراج معرف الطلب بشكل أكثر دقة
    data = query.data
    if "confirm_" in data:
        withdrawal_id = data.split("confirm_")[1]
        action = "confirm"
    elif "reject_" in data:
        withdrawal_id = data.split("reject_")[1]
        action = "reject"
    elif "back_" in data:
        withdrawal_id = data.split("back_")[1]
        action = "back"
    else:
        await query.edit_message_text("❌ بيانات الطلب غير صحيحة.")
        return ConversationHandler.END

    try:
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await query.edit_message_text(
                "❌ لم يتم العثور على بيانات الطلب",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        registration_code = await get_user_registration_code(withdrawal_data['user_id'])

        if action == "confirm":
            # عرض تأكيد نهائي
            confirmation_message = (
                "⚠️ *تأكيد نهائي لقبول الحوالة*\n\n"
                f"👤 *معرف المستخدم:* `{withdrawal_data['user_id']}`\n"
                f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
                f"💵 *المبلغ المدفوع:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
                "📝 *حالة الطلب:* قيد المراجعة.....\n\n"
                "هل أنت متأكد من قبول الحوالة؟"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✅ نعم، تنفيذ التحويل", callback_data=f"execute_{withdrawal_id}"),
                    InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{withdrawal_id}")
                ]
            ]

            await query.edit_message_text(
                confirmation_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

        elif action == "reject":
            # حفظ معرف الطلب في بيانات المحادثة
            context.user_data['pending_rejection_id'] = withdrawal_id

            await query.edit_message_text(
                "📝 *الرجاء كتابة سبب الرفض:*\n\n"
                "اكتب سبب رفض الطلب في رسالة جديدة.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{withdrawal_id}")
                ]])
            )
            return AWAITING_REJECTION_REASON

        elif action == "back":
            admin_message = (
                f"👤 *طلب سحب جديد من المستخدم:* `{withdrawal_data['user_id']}`\n\n"
                f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
                f"💵 *المبلغ المدفوع:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
                f"🏦 *جهة الإصدار:* {withdrawal_data['transfer_issuer']}\n"
                 f"⌚️ *وقت التنفيذ:* {format_time_yemen(datetime.now(timezone.utc))}\n"



            )

            admin_keyboard = [
                [
                    InlineKeyboardButton("✅ تأكيد", callback_data=f"admin_confirm_{withdrawal_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_{withdrawal_id}")
                ]
            ]

            await query.edit_message_text(
                admin_message,
                reply_markup=InlineKeyboardMarkup(admin_keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

        return CONFIRMATION

    except Exception as e:
        logger.error(f"خطأ في معالجة تأكيد المشرف: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء معالجة الطلب.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
async def handle_rejection_reason_text(update: Update, context: CallbackContext) -> int:
    """معالجة سبب الرفض المكتوب"""
    try:
        withdrawal_id = context.user_data.get('pending_rejection_id')
        if not withdrawal_id:
            await update.message.reply_text(
                "❌ عذراً، حدث خطأ في معالجة الطلب.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        reason = update.message.text.strip()
        if len(reason) < 3:
            await update.message.reply_text(
                "❌ الرجاء كتابة سبب أكثر تفصيلاً للرفض.",
                parse_mode=ParseMode.MARKDOWN
            )
            return AWAITING_REJECTION_REASON

        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await update.message.reply_text(
                "❌ لم يتم العثور على بيانات الطلب.",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # تحديث حالة الطلب
        await update_withdrawal_status(withdrawal_id, 'rejected', reason)

        # إشعار للمستخدم
        user_message = (
            "❌ *تم رفض طلب التحويل*\n\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"📝 *سبب الرفض:* {reason}\n\n"
            "يمكنك بدء طلب جديد من خلال الضغط على الزر أدناه."
        )

        keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
        
        await telegram_service.send_message(
            chat_id=withdrawal_data['user_id'],
            text=user_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # تأكيد للمشرف
        admin_message = (
            "✅ *تم رفض الطلب بنجاح*\n\n"
            f"👤 *معرف المستخدم:* `{withdrawal_data['user_id']}`\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"📝 *سبب الرفض:* {reason}"
        )

        await update.message.reply_text(
            admin_message,
            parse_mode=ParseMode.MARKDOWN
        )

        # تنظيف البيانات المؤقتة
        if 'pending_rejection_id' in context.user_data:
            del context.user_data['pending_rejection_id']

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة سبب الرفض: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء معالجة الرفض.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END


async def handle_reject_reason(update: Update, context: CallbackContext):
    """معالجة اختيار سبب الرفض"""
    query = update.callback_query
    await query.answer()

    try:
        # استخراج البيانات من callback_data
        data = query.data.split('_')
        if len(data) < 4:
            await query.edit_message_text("❌ بيانات الطلب غير صحيحة.")
            return

        withdrawal_id = data[2]
        reason_index = int(data[3])

        if not (0 <= reason_index < len(REJECTION_REASONS)):
            await query.edit_message_text("❌ سبب الرفض غير صحيح.")
            return

        reason = REJECTION_REASONS[reason_index]

        # تحديث حالة الطلب
        await update_withdrawal_status(withdrawal_id, 'rejected')

        # استرجاع بيانات السحب
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await query.edit_message_text(
                "❌ لم يتم العثور على بيانات الطلب",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        user_id = withdrawal_data['user_id']

        # إشعار المستخدم
        user_message = (
            "❌ *تم رفض طلب التحويل*\n\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"📝 *السبب:* {reason}\n\n"
            "يمكنك بدء طلب جديد عن طريق الضغط على الزر أدناه."
        )

        keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
        
        await telegram_service.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # تحديث رسالة المشرف
        await query.edit_message_text(
            f"✅ *تم رفض الطلب بنجاح*\n\n"
            f"👤 *المستخدم:* `{user_id}`\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"📝 *السبب:* {reason}\n"
            f"⏱ *وقت الإلغاء:* {format_time_yemen(datetime.now(timezone.utc))}"
        )

        # إشعار لمجموعة المشرفين
        if ADMIN_GROUP_ID:
            admin_message = (
                "ℹ️ *تم رفض طلب*\n\n"
                f"👤 *معرف المستخدم:* `{user_id}`\n"
                f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"👮‍♂️ *تم الرفض بواسطة:* `{update.effective_user.id}`\n"
                f"📝 *السبب:* {reason}"
            )

            await telegram_service.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=admin_message,
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"خطأ في معالجة سبب الرفض: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء معالجة الرفض",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # في حالة الخطأ أيضاً نعرض زر البدء
        error_keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
        await telegram_service.send_message(
            chat_id=user_id,
            text="❌ حدث خطأ في معالجة طلبك. يمكنك البدء من جديد.",
            reply_markup=InlineKeyboardMarkup(error_keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

async def handle_cancellation(update: Update, context: CallbackContext) -> int:
    """معالجة إلغاء العملية"""
    query = update.callback_query
    await query.answer()

    # عرض أسباب الإلغاء للمستخدم
    keyboard = []
    for reason_id, reason_text in CANCELLATION_REASONS.items():
        keyboard.append([InlineKeyboardButton(
            reason_text, 
            callback_data=f"cancel_reason_{reason_id}"
        )])

    await query.edit_message_text(
        "🚫 *الرجاء اختيار سبب الإلغاء:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return CANCELLATION_REASONS

async def handle_cancel_reason(update: Update, context: CallbackContext) -> int:
    """معالجة اختيار سبب الإلغاء"""
    query = update.callback_query
    await query.answer()

    try:
        # استخراج رقم السبب من البيانات
        reason_index = int(query.data.split('_')[-1])
        reason = CANCELLATION_REASONS[reason_index]

        # إعداد رسالة للمستخدم
        user_message = (
            f"❌ *تم إلغاء العملية*\n"
            f"📝 *السبب:* {reason}\n\n"
            "يمكنك بدء طلب جديد عن طريق الأمر /start"
        )

        # إعداد رسالة للمشرفين
        admin_message = (
            "❌ *تم إلغاء طلب سحب*\n\n"
            f"👤 *معرف المستخدم:* `{update.effective_user.id}`\n"
            f"📝 *السبب:* {reason}"
        )

        # إرسال الإشعارات
        await query.edit_message_text(
            text=user_message,
            parse_mode='Markdown'
        )

        await telegram_service.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=admin_message,
            parse_mode='Markdown'
        )

        # تحديث حالة الطلب في قاعدة البيانات إذا كان هناك معرف للسحب
        if 'withdrawal_id' in context.user_data:
            await update_withdrawal_status(
                context.user_data['withdrawal_id'],
                'cancelled',
                reason
            )

        # مسح بيانات المستخدم
        context.user_data.clear()

    except Exception as e:
        logger.error(f"خطأ في معالجة سبب الإلغاء: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء معالجة الإلغاء. يمكنك المحاولة مرة أخرى.",
            parse_mode='Markdown'
        )

    return ConversationHandler.END
async def handle_admin_cancel_reason(update: Update, context: CallbackContext):
    """معالجة سبب إلغاء المشرف"""
    query = update.callback_query
    await query.answer()

    try:
        # استخراج البيانات من callback_data
        data = query.data.split('_')
        if len(data) < 5:
            await query.edit_message_text("❌ بيانات الطلب غير صحيحة.")
            return

        withdrawal_id = data[3]
        reason_key = data[4]
        reason = CANCELLATION_REASONS.get(reason_key, 'سبب غير معروف')

        # التحقق من صلاحية المشرف
        if update.effective_user.id not in ADMIN_USER_IDS:
            await query.edit_message_text(
                "❌ ليس لديك صلاحية تنفيذ هذا الإجراء.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # استرجاع بيانات السحب
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await query.edit_message_text(
                "❌ لم يتم العثور على بيانات الطلب",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        user_id = withdrawal_data['user_id']

        # تحديث حالة الطلب في قاعدة البيانات
        await update_withdrawal_status(
            withdrawal_id,
            'cancelled',
            f"ملغي من قبل المشرف - {reason}"
        )

        # إرسال إشعار للمستخدم مع زر بدء جديد
        keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
        user_message = (
            "❌ *تم إلغاء طلب التحويل من قبل المشرف*\n\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"🏦 *العملة المشفرة:* {withdrawal_data['crypto_currency']}\n"
            f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
            f"📝 *سبب الإلغاء:* {reason}\n\n"
            "يمكنك بدء طلب جديد عن طريق الضغط على الزر أدناه."
        )

        await telegram_service.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # تحديث رسالة المشرف
        admin_message = (
            "✅ *تم إلغاء الطلب بنجاح*\n\n"
            f"👤 *معرف المستخدم:* `{user_id}`\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"🏦 *العملة المشفرة:* {withdrawal_data['crypto_currency']}\n"
            f"📝 *سبب الإلغاء:* {reason}\n"
            f"⏱ *وقت الإلغاء:* {format_time_yemen(datetime.now(timezone.utc))}"
        )

        await query.edit_message_text(
            text=admin_message,
            parse_mode=ParseMode.MARKDOWN
        )

        # إشعار لمجموعة المشرفين
        if ADMIN_GROUP_ID:
            admin_group_message = (
                "ℹ️ *تم إلغاء طلب سحب*\n\n"
                f"👤 *معرف المستخدم:* `{user_id}`\n"
                f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🏦 *العملة المشفرة:* {withdrawal_data['crypto_currency']}\n"
                f"👮‍♂️ *تم الإلغاء بواسطة:* `{update.effective_user.id}`\n"
                f"📝 *السبب:* {reason}"
            )

            await telegram_service.send_message(
                chat_id=ADMIN_GROUP_ID,
                text=admin_group_message,
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Error in admin cancel handler: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء معالجة الإلغاء",
            parse_mode=ParseMode.MARKDOWN
        )

async def notify_withdrawal_status_change(withdrawal_data: dict, status: str, reason: str = None):
    """
    دالة مساعدة لإرسال إشعارات تغيير حالة السحب
    """
    try:
        user_id = withdrawal_data['user_id']
        status_messages = {
            'cancelled': (
                "❌ *تم إلغاء طلب التحويل*\n\n"
                f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"📝 *السبب:* {reason if reason else 'غير محدد'}"
            ),
            'rejected': (
                "❌ *تم رفض طلب التحويل*\n\n"
                f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"📝 *السبب:* {reason if reason else 'غير محدد'}"
            ),
            'completed': (
                "✅ *تم اكتمال التحويل بنجاح*\n\n"
                f"💰 *المبلغ:* {withdrawal_data['net_amount']:,.6f} {withdrawal_data['crypto_currency']}\n"
                f"🌐 *الشبكة:* {withdrawal_data['network_name']}"
            )
        }

        if status in status_messages:
            await telegram_service.send_message(
                chat_id=user_id,
                text=status_messages[status],
                parse_mode='Markdown'
            )

            # إرسال إشعار لمجموعة المشرفين
            if ADMIN_GROUP_ID:
                admin_message = (
                    f"ℹ️ *تحديث حالة السحب*\n\n"
                    f"👤 *معرف المستخدم:* `{user_id}`\n"
                    f"📊 *الحالة الجديدة:* {status}\n"
                    f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                    f"🏦 *العملة المشفرة:* {withdrawal_data['crypto_currency']}"
                )
                if reason:
                    admin_message += f"\n📝 *السبب:* {reason}"

                await telegram_service.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=admin_message,
                    parse_mode='Markdown'
                )

    except Exception as e:
        logger.error(f"Error sending withdrawal status notification: {e}")
        # لا نقوم برفع الاستثناء هنا لأن هذه دالة إشعارات
        # ونريد أن تستمر العملية الرئيسية حتى لو فشل الإشعار
def get_conversation_handler() -> ConversationHandler:
    """إرجاع معالج المحادثة الرئيسي"""
    return ConversationHandler(
        entry_points=[
            CommandHandler('start', show_start_button),
            CallbackQueryHandler(start_new_process, pattern="^start_new$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
        ],
        states={
            REGISTRATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_registration)
            ],
            SELECT_TRANSFER_TYPE: [
                CallbackQueryHandler(handle_transfer_type, pattern="^transfer_type_"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            SELECT_BANK: [
                CallbackQueryHandler(handle_bank_selection, pattern="^bank_"),
                CallbackQueryHandler(cancel, pattern="^cancel$")
            ],
            REQUEST_CURRENCY: [
                CallbackQueryHandler(handle_currency_selection, pattern="^curr_"),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$")
            ],
            REQUEST_NETWORK: [
                CallbackQueryHandler(handle_network_selection, pattern="^net_"),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$")
            ],
            REQUEST_LOCAL_CURRENCY: [
                CallbackQueryHandler(handle_local_currency_selection, pattern="^local_"),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$"),
                CallbackQueryHandler(handle_currency_selection, pattern=f"^{BACK}$")
            ],
            REQUEST_AMOUNT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_amount
                ),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$"),
                CallbackQueryHandler(handle_local_currency_selection, pattern=f"^{BACK}$")
            ],
            REQUEST_TRANSFER_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_transfer_number),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$"),
                CallbackQueryHandler(handle_amount, pattern=f"^{BACK}$")
            ],
            REQUEST_TRANSFER_ISSUER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_transfer_issuer),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$"),
                CallbackQueryHandler(handle_transfer_number, pattern=f"^{BACK}$")
            ],
            REQUEST_WALLET_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_address),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$"),
                CallbackQueryHandler(handle_transfer_issuer, pattern=f"^{BACK}$")
            ],
            CONFIRMATION: [
                CallbackQueryHandler(handle_user_confirmation, pattern='^confirm_'),
                CallbackQueryHandler(handle_admin_confirmation, pattern='^admin_'),  
                CallbackQueryHandler(cancel, pattern='^cancel$')
      ],
            AWAITING_REJECTION_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rejection_reason_text),
                CallbackQueryHandler(handle_admin_confirmation, pattern='^admin_back_')
],
            CANCEL_REASON: [
                CallbackQueryHandler(handle_cancel_reason, pattern="^cancel_reason_"),
                CallbackQueryHandler(cancel, pattern=f"^{CANCEL}$")
            ]
        },
        fallbacks=[
            # معالجات الخروج من المحادثة
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            CallbackQueryHandler(handle_cancel_pending, pattern="^cancel_pending_")
        ],
        allow_reentry=True,
        name="withdrawal_conversation"
    )
async def handle_back(update: Update, context: CallbackContext) -> int:
    """معالج زر الرجوع العام"""
    query = update.callback_query
    await query.answer()

    # الحصول على الحالة الحالية
    current_state = context.user_data.get('current_state')
    
    if current_state == REQUEST_NETWORK:
        # العودة إلى اختيار العملة
        return await handle_currency_selection(update, context)
    elif current_state == REQUEST_LOCAL_CURRENCY:
        # العودة إلى اختيار الشبكة
        return await handle_network_selection(update, context)
    elif current_state == REQUEST_AMOUNT:
        # العودة إلى اختيار العملة المحلية
        return await handle_local_currency_selection(update, context)
    elif current_state == REQUEST_TRANSFER_NUMBER:
        # العودة إلى إدخال المبلغ
        return await handle_amount(update, context)
    elif current_state == REQUEST_TRANSFER_ISSUER:
        # العودة إلى إدخال رقم الحوالة
        return await handle_transfer_number(update, context)
    elif current_state == REQUEST_WALLET_ADDRESS:
        # العودة إلى إدخال جهة الإصدار
        return await handle_transfer_issuer(update, context)
    elif current_state == CONFIRMATION:
        # العودة إلى إدخال عنوان المحفظة
        return await handle_wallet_address(update, context)
    else:
        # في حالة عدم معرفة الحالة، العودة إلى البداية
        keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]
        await query.edit_message_text(
            "عذراً، حدث خطأ. يمكنك البدء من جديد.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

async def create_withdrawal_request(update: Update, context: CallbackContext) -> int:
    """
    إنشاء طلب سحب جديد وحفظه في قاعدة البيانات
    
    Args:
        update (Update): تحديث تيليجرام
        context (CallbackContext): سياق المحادثة
    
    Returns:
        int: الحالة التالية في المحادثة
    """
    user_data = context.user_data
    chat_id = update.effective_chat.id
    
    try:
        # إنشاء معرف فريد للطلب
        withdrawal_id = str(uuid.uuid4())
        
        # إنشاء بيانات طلب السحب
        withdrawal_data = {
            'user_id': update.effective_user.id,
            'username': update.effective_user.username,
            'chat_id': chat_id,
            'crypto_currency': user_data.get('crypto_currency'),
            'network_code': user_data.get('network_code'),
            'network_name': user_data.get('network_name'),
            'amount': user_data.get('crypto_amount'),
            'wallet_address': user_data.get('wallet_address'),
            'local_currency': user_data.get('local_currency'),
            'local_currency_name': user_data.get('local_currency_name'),
            'local_amount': user_data.get('local_amount'),
            'crypto_amount': user_data.get('crypto_amount'),
            'transfer_number': user_data.get('transfer_number'),
            'transfer_issuer': user_data.get('transfer_issuer'),
            'sender_name': user_data.get('sender_name', 'غير متوفر'),
            'phone': user_data.get('phone', 'غير متوفر'),
            'net_amount': user_data.get('net_amount'),
            'transfer_type': user_data.get('transfer_type', 'name_transfer')
        }
        
        # حفظ طلب السحب في قاعدة البيانات
        success = await save_withdrawal(withdrawal_id, withdrawal_data)
        
        if not success:
            await context.bot.send_message(
                chat_id=chat_id,
                text="عذراً، حدث خطأ أثناء حفظ طلبك. الرجاء المحاولة مرة أخرى."
            )
            return ConversationHandler.END
            
        # حفظ معرف طلب السحب في بيانات المستخدم
        user_data['withdrawal_id'] = withdrawal_id

        # إرسال الطلب للمشرفين
        await send_to_admins(context, withdrawal_id)
        
        # إرسال رسالة تأكيد للمستخدم
        await context.bot.send_message(
            chat_id=chat_id,
            text="تم إرسال طلبك بنجاح! سيتم مراجعته من قبل المشرفين في أقرب وقت."
        )
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"خطأ في إنشاء طلب السحب: {str(e)}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END
