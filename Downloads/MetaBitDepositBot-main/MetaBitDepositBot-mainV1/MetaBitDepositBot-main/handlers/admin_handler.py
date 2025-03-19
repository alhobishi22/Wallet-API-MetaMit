# handlers/admin_handler.py
import shlex
import os
import time
from typing import Tuple
from datetime import datetime, timezone
from telegram.constants import ParseMode
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    CallbackContext,ConversationHandler,
    filters,
    MessageHandler
)
from typing import Set
from services.withdrawal_manager import withdrawal_manager, LockStatus  # تم تصحيح اسم الفئة

from telegram.error import BadRequest
from telegram.error import TelegramError

from config.settings import (
    ADMIN_GROUP_ID,
    ADMIN_USER_IDS,
    REJECTION_REASONS,
    CANCELLATION_REASONS
)

from services.database_service import (
    set_setting,
    get_withdrawal,
    update_withdrawal_status,
    add_registration_code,
    update_min_withdrawal,
    update_max_withdrawal,
    delete_registration_code,
    get_all_users_with_codes,
    release_connection,
    get_connection,
    get_user_registration_code,
    update_exchange_rate,
    get_exchange_rates,
    get_setting,
    store_admin_action

)
(
    REGISTRATION,
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
) = range(11)

from services.telegram_service import telegram_service
from services.binance_service import binance_service
from services.external_wallet_service import external_wallet_service
from utils.rate_limiter import rate_limiter
import asyncio
import json
import math
import re
from datetime import datetime, timedelta, timezone
import time

logger = logging.getLogger(__name__)

BACK = 'back'
CANCEL = 'cancel'
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

# دالة لتعيين الحد الأدنى للسحب
async def set_min_withdrawal(update: Update, context: CallbackContext):
    """تعيين الحد الأدنى للسحب بالدولار الأمريكي."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to set minimum withdrawal.")

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        logger.warning(f"User {user_id} does not have permission to set minimum withdrawal.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ الرجاء تحديد المبلغ الجديد بالدولار. الاستخدام: /setmin <المبلغ>")
        return

    try:
        new_min = float(context.args[0])
        if new_min <= 0:
            raise ValueError
        await update_min_withdrawal(new_min)
        context.bot_data['MIN_WITHDRAWAL_USD'] = new_min
        await update.message.reply_text(f"✅ تم تحديث الحد الأدنى للسحب إلى {new_min:,.2f} USD.")
        logger.info(f"Admin {user_id} set MIN_WITHDRAWAL_USD to {new_min}.")
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال مبلغ صحيح وأكبر من الصفر.")
    except Exception as e:
        logger.error(f"Error setting min withdrawal: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث الحد الأدنى للسحب.")

# دالة لتعيين الحد الأقصى للسحب بالدولار الأمريكي
async def set_max_withdrawal(update: Update, context: CallbackContext):
    """تعيين الحد الأقصى للسحب بالدولار الأمريكي."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to set maximum withdrawal.")

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        logger.warning(f"User {user_id} does not have permission to set maximum withdrawal.")
        return

    if len(context.args) != 1:
        await update.message.reply_text("❌ الرجاء تحديد المبلغ الجديد بالدولار. الاستخدام: /setmax <المبلغ>")
        return

    try:
        new_max = float(context.args[0])
        if new_max <= 0:
            raise ValueError
        await update_max_withdrawal(new_max)
        context.bot_data['MAX_WITHDRAWAL_USD'] = new_max
        await update.message.reply_text(f"✅ تم تحديث الحد الأقصى للسحب إلى {new_max:,.2f} USD.")
        logger.info(f"Admin {user_id} set MAX_WITHDRAWAL_USD to {new_max}.")
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال مبلغ صحيح وأكبر من الصفر.")
    except Exception as e:
        logger.error(f"Error setting max withdrawal: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث الحد الأقصى للسحب.")

# دالة لعرض أسعار الصرف الحالية
async def show_exchange_rates(update: Update, context: CallbackContext):
    """عرض جميع أسعار الصرف الحالية."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        return

    try:
        rates = await get_exchange_rates()
        if not rates:
            await update.message.reply_text(
                "❌ لا توجد أسعار صرف محددة.\n"
                "استخدم الأمر /setrate لإضافة سعر صرف جديد."
            )
            return

        message = "💱 *أسعار الصرف الحالية:*\n\n"
        for currency, rate in rates.items():
            message += f"• *{currency}:* {rate:,.2f} USD\n"
        
        message += "\nللتعديل استخدم:\n"
        message += "`/setrate USD 1`\n"
        message += "`/setrate YER 250`"

        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"خطأ في عرض أسعار الصرف: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء عرض أسعار الصرف.")

# دالة لتحديث سعر الصرف
async def set_exchange_rate(update: Update, context: CallbackContext):
    """تحديث سعر صرف عملة معينة."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ الصيغة غير صحيحة.\n"
            "الاستخدام: /setrate <رمز_العملة> <السعر>\n"
            "مثال: /setrate YER 250"
        )
        return

    try:
        currency = context.args[0].upper()
        rate = float(context.args[1])
        
        if rate <= 0:
            raise ValueError("يجب أن يكون السعر أكبر من صفر")

        if await update_exchange_rate(currency, rate):
            # تحديث EXCHANGE_RATES في الذاكرة
            rates = await get_exchange_rates()
            context.bot_data['EXCHANGE_RATES'] = rates
            
            await update.message.reply_text(
                f"✅ تم تحديث سعر صرف {currency} إلى {rate:,.2f} USD"
            )
        else:
            await update.message.reply_text("❌ حدث خطأ أثناء تحديث سعر الصرف.")

    except ValueError as e:
        await update.message.reply_text(
            "❌ الرجاء إدخال سعر صحيح وأكبر من الصفر."
        )
    except Exception as e:
        logger.error(f"خطأ في تحديث سعر الصرف: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث سعر الصرف.")

# دالة لحذف عملة
async def delete_exchange_rate(update: Update, context: CallbackContext):
    """حذف عملة من قائمة أسعار الصرف."""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ الصيغة غير صحيحة.\n"
            "الاستخدام: /deleterate <رمز_العملة>\n"
            "مثال: /deleterate YER"
        )
        return

    try:
        currency = context.args[0].upper()
        if await delete_exchange_rate(currency):
            # تحديث EXCHANGE_RATES في الذاكرة
            rates = await get_exchange_rates()
            context.bot_data['EXCHANGE_RATES'] = rates
            
            await update.message.reply_text(
                f"✅ تم حذف العملة {currency} من قائمة أسعار الصرف"
            )
        else:
            await update.message.reply_text("❌ حدث خطأ أثناء حذف العملة.")

    except Exception as e:
        logger.error(f"خطأ في حذف العملة: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء حذف العملة.")

# دالة لتعيين الحد الفاصل للعمولة
async def set_commission_threshold(update: Update, context: CallbackContext):
    """تعيين الحد الفاصل للعمولة بالدولار الأمريكي."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to set commission threshold.")

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ الرجاء تحديد الحد الفاصل الجديد بالدولار.\n"
            "الاستخدام: /setcommissionthreshold <المبلغ>\n"
            "مثال: /setcommissionthreshold 30"
        )
        return

    try:
        threshold = float(context.args[0])
        if threshold <= 0:
            raise ValueError
        await set_setting('COMMISSION_THRESHOLD_USD', str(threshold))
        context.bot_data['COMMISSION_THRESHOLD_USD'] = threshold
        await update.message.reply_text(
            f"✅ تم تحديث الحد الفاصل للعمولة إلى {threshold:,.2f} USD\n"
            f"• المبالغ الأقل من أو تساوي {threshold:,.2f} USD ستخضع للعمولة الثابتة\n"
            f"• المبالغ الأكبر من {threshold:,.2f} USD ستخضع للعمولة النسبية"
        )
        logger.info(f"Admin {user_id} set COMMISSION_THRESHOLD_USD to {threshold}")
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال مبلغ صحيح وأكبر من الصفر.")
    except Exception as e:
        logger.error(f"Error setting commission threshold: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث الحد الفاصل للعمولة.")

# دالة لتعيين العمولة الثابتة
async def set_fixed_commission(update: Update, context: CallbackContext):
    """تعيين قيمة العمولة الثابتة بالدولار الأمريكي."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to set fixed commission.")

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ الرجاء تحديد قيمة العمولة الثابتة بالدولار.\n"
            "الاستخدام: /setfixedcommission <المبلغ>\n"
            "مثال: /setfixedcommission 2"
        )
        return

    try:
        fixed_commission = float(context.args[0])
        if fixed_commission <= 0:
            raise ValueError
        await set_setting('FIXED_COMMISSION_USD', str(fixed_commission))
        context.bot_data['FIXED_COMMISSION_USD'] = fixed_commission
        await update.message.reply_text(
            f"✅ تم تحديث العمولة الثابتة إلى {fixed_commission:,.2f} USD\n"
            "سيتم تطبيق هذه العمولة على المبالغ الصغيرة"
        )
        logger.info(f"Admin {user_id} set FIXED_COMMISSION_USD to {fixed_commission}")
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال مبلغ صحيح وأكبر من الصفر.")
    except Exception as e:
        logger.error(f"Error setting fixed commission: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث العمولة الثابتة.")

# دالة لتعيين نسبة العمولة
# استيراد المعالجات من الملف الجديد
from handlers.admin_conversation import handle_rejection_reason, handle_admin_button
async def handle_rejection_reason(update: Update, context: CallbackContext) -> int:
    """معالجة سبب الرفض المدخل من قبل المشرف"""
    try:
        # التحقق من وجود معرف الطلب في بيانات المستخدم
        withdrawal_id = context.user_data.get('pending_rejection_id')

        # إذا لم يكن موجوداً، نحاول استرجاعه من قاعدة البيانات
        if not withdrawal_id:
            # البحث عن آخر إجراء رفض للمشرف الحالي
            admin_id = update.effective_user.id
            action = await get_last_admin_action(admin_id, "rejection")
            if action:
                withdrawal_id = action['withdrawal_id']
                context.user_data['pending_rejection_id'] = withdrawal_id
                context.user_data['original_message_id'] = action['message_id']
            else:
                await update.message.reply_text(
                    "❌ عذراً، لا يوجد طلب رفض معلق",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END

        # استرجاع بيانات الطلب
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await update.message.reply_text(
                "❌ لم يتم العثور على بيانات الطلب",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # الحصول على سبب الرفض
        reason = update.message.text.strip()

        # التحقق من حالة الطلب
        withdrawal = await get_withdrawal(withdrawal_id)
        if not withdrawal:
            await update.message.reply_text("❌ لم يتم العثور على الطلب.")
            return
            
        # التحقق من أن الطلب ليس مكتملاً
        if withdrawal.get('status') == 'completed':
            logger.warning(f"⚠️ محاولة رفض طلب مكتمل: {withdrawal_id}")
            await update.message.reply_text("⚠️ لا يمكن رفض طلب تم إكماله بالفعل.")
            return
            
        # محاولة اكتساب قفل للطلب
        admin_id = update.effective_user.id
        admin_user = await context.bot.get_chat(admin_id)
        admin_name = admin_user.full_name or admin_user.username or str(admin_id)
        
        from services.withdrawal_manager import withdrawal_manager
        lock_acquired = await withdrawal_manager.acquire_lock(withdrawal_id, admin_id, admin_name)
        
        if not lock_acquired:
            logger.warning(f"⚠️ فشل في اكتساب قفل الطلب {withdrawal_id} للرفض")
            await update.message.reply_text(
                "⚠️ لا يمكن معالجة الطلب حالياً، قد يكون تحت المعالجة من قبل مشرف آخر",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # تحديث حالة الطلب
        await update_withdrawal_status(withdrawal_id, 'rejected', reason)

        # إشعار المستخدم
        user_id = withdrawal_data['user_id']

        # إنشاء زر البدء
        start_keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]

        # إشعار المستخدم
        user_message = (
            "❌ *تم رفض طلب التحويل*\n\n"
            f"📝 *السبب:* {reason}\n"
            "يمكنك بدء العمليه جديد "
        )

        await telegram_service.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=InlineKeyboardMarkup(start_keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # تحديث رسالة المشرف
        await update.message.reply_text(
            f"✅ *تم رفض الطلب بنجاح*\n\n"
            f"👤 *المستخدم:* `{user_id}`\n"
            f"📝 *السبب:* {reason}",
            parse_mode=ParseMode.MARKDOWN
        )

        # إشعار للمشرفين
        admin_message = (
            "ℹ️ *تم رفض طلب*\n\n"
            f"👤 *معرف المستخدم:* `{user_id}`\n"
            f"📝 *السبب:* {reason}\n"
            f"👮‍♂️ *تم الرفض بواسطة:* `{update.effective_user.id}`"
        )

        if ADMIN_USER_IDS:
            for admin_id in ADMIN_USER_IDS:
                await telegram_service.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode=ParseMode.MARKDOWN
                )

        # تنظيف بيانات المستخدم
        if 'pending_rejection_id' in context.user_data:
            del context.user_data['pending_rejection_id']
        if 'original_message_id' in context.user_data:
            del context.user_data['original_message_id']

        # تحرير القفل بعد الانتهاء من معالجة الطلب
        await withdrawal_manager.release_lock(withdrawal_id)
        logger.info(f"✅ تم تحرير قفل الطلب {withdrawal_id} بعد رفضه بنجاح")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة سبب الرفض: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء معالجة الرفض",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
async def handle_admin_button(update: Update, context: CallbackContext) -> int:
    """معالجة أزرار المشرفين"""
    query = update.callback_query
    await query.answer()

    try:
        data = query.data
        # استخراج معرف الطلب من البيانات
        if "admin_reject_" in data:
            withdrawal_id = data.split('_')[-1]
            admin_id = update.effective_user.id
            chat_id = update.effective_chat.id
            message_id = query.message.message_id

            # تخزين معلومات الإجراء في قاعدة البيانات
            await store_admin_action(
                withdrawal_id=withdrawal_id,
                admin_id=admin_id,
                action_type="rejection",
                message_id=message_id,
                chat_id=chat_id
            )

            # تحديث بيانات المستخدم مع تخزين المعرف في قاعدة البيانات
            context.user_data['pending_rejection_id'] = withdrawal_id
            context.user_data['original_message_id'] = message_id

            # إنشاء أزرار لأسباب الرفض
            keyboard = []
            for i, reason in enumerate(REJECTION_REASONS):
                keyboard.append([InlineKeyboardButton(reason, callback_data=f"admin_reject_reason_{withdrawal_id}_{i}")])

            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{withdrawal_id}")])

            await query.edit_message_text(
                "❓ *الرجاء اختيار سبب الرفض:*",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return AWAITING_REJECTION_REASON

        elif "admin_confirm_" in data:
            withdrawal_id = data.split('_')[-1]
            return await handle_admin_confirmation(update, context)

        elif "admin_back_" in data:
            withdrawal_id = data.split('_')[-1]

            # استرجاع بيانات الطلب
            withdrawal_data = await get_withdrawal(withdrawal_id)
            if not withdrawal_data:
                await query.edit_message_text(
                    "❌ لم يتم العثور على بيانات الطلب",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END

            # إعادة إنشاء أزرار التأكيد والرفض
            keyboard = [
                [
                    InlineKeyboardButton("✅ تأكيد", callback_data=f"admin_confirm_{withdrawal_id}"),
                    InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_{withdrawal_id}")
                ]
            ]

            # استرجاع رمز التسجيل
            registration_code = await get_user_registration_code(withdrawal_data['user_id'])

            # إعادة إنشاء رسالة الطلب
            admin_message = (
                f"👤 *طلب سحب من المستخدم:* `{withdrawal_data['user_id']}`\n\n"
                f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
                f"💰 *العملة المشفرة:* {withdrawal_data['crypto_currency']}\n"
                f"💵 *المبلغ المدفوع:* `{withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}`\n"
                f"🌐 *الشبكة:* {withdrawal_data['network_name']}\n"
                f"🔢 *رقم الحوالة:* `{withdrawal_data['transfer_number']}`\n"
                f"🏦 *جهة الإصدار:* {withdrawal_data['transfer_issuer']}\n"
                f"⌚️ *وقت الطلب:* {format_time_yemen(withdrawal_data['created_at'])}\n"
            )

            await query.edit_message_text(
                admin_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة زر المشرف: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء معالجة الطلب",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

def get_admin_handlers():
    """إرجاع قائمة معالجات المشرفين"""
    # معالج محادثة الرفض
    rejection_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_admin_button, pattern='^admin_reject_')],
        states={
            AWAITING_REJECTION_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rejection_reason)]
        },
        fallbacks=[
            CallbackQueryHandler(handle_admin_button, pattern='^admin_back_'),
            CommandHandler('cancel', cancel)
        ],
        name="admin_rejection_conversation",
        persistent=True  # تغيير هذه القيمة من False إلى True
    )

    return [
        CommandHandler('setmin', set_min_withdrawal),
        CommandHandler('setmax', set_max_withdrawal),
        CommandHandler('setrate', set_exchange_rate),
        CommandHandler('showrates', show_exchange_rates),
        CommandHandler('deleterate', delete_exchange_rate),
        CommandHandler('setcommissionthreshold', set_commission_threshold),
        CommandHandler('setfixedcommission', set_fixed_commission),
        CommandHandler('setcommissionrate', set_commission_rate),
        CommandHandler('bep20limits', bep20_limits),
        CommandHandler('setbep20min', set_bep20_min),
        CommandHandler('setbep20max', set_bep20_max),
        # إضافة معالج محادثة الرفض
        rejection_handler,
        # إضافة معالجات الأزرار الأخرى
        CallbackQueryHandler(handle_admin_button, pattern='^admin_confirm_'),
        CallbackQueryHandler(handle_admin_button, pattern='^admin_back_'),
        CallbackQueryHandler(execute_withdrawal, pattern='^execute_'),
    ]
async def cancel(update: Update, context: CallbackContext) -> int:
    """إلغاء العملية الحالية"""
    # تنظيف بيانات المحادثة
    if 'pending_rejection_id' in context.user_data:
        del context.user_data['pending_rejection_id']

    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ConversationHandler.END

async def set_commission_rate(update: Update, context: CallbackContext):
    """تعيين نسبة العمولة للمبالغ الكبيرة."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to set commission rate.")

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        return

    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ الرجاء تحديد نسبة العمولة الجديدة.\n"
            "الاستخدام: /setcommissionrate <النسبة>\n"
            "مثال: /setcommissionrate 0.05 (يعني 5%)"
        )
        return

    try:
        new_rate = float(context.args[0])
        if not (0 < new_rate < 1):
            raise ValueError
        await set_setting('PERCENTAGE_COMMISSION_RATE', str(new_rate))
        context.bot_data['PERCENTAGE_COMMISSION_RATE'] = new_rate
        await update.message.reply_text(
            f"✅ تم تحديث نسبة العمولة إلى {new_rate*100}%\n"
            "سيتم تطبيق هذه النسبة على المبالغ الكبيرة"
        )
        logger.info(f"Admin {user_id} set PERCENTAGE_COMMISSION_RATE to {new_rate}")
    except ValueError:
        await update.message.reply_text(
            "❌ الرجاء إدخال نسبة صحيحة بين 0 و 1\n"
            "مثال: 0.05 تعني 5%"
        )
    except Exception as e:
        logger.error(f"Error setting commission rate: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث نسبة العمولة.")

# دالة لتنفيذ عملية السحب
processing_withdrawals: Set[str] = set()

async def execute_withdrawal(update: Update, context: CallbackContext):
    """تنفيذ عملية السحب مع منع التكرار وإدارة الحالات المختلفة"""
    query = update.callback_query
    await query.answer()

    # استخراج معرف الطلب من البيانات
    data = query.data.split('_')
    if len(data) < 2:
        await query.edit_message_text("❌ بيانات الطلب غير صحيحة.")
        return

    withdrawal_id = data[1]
    admin_id = update.effective_user.id

    # تخزين معلومات الإجراء في قاعدة البيانات
    await store_admin_action(
        withdrawal_id=withdrawal_id,
        admin_id=admin_id,
        action_type="execution",
        message_id=query.message.message_id,
        chat_id=update.effective_chat.id
    )


    withdrawal_id = query.data.split('_')[1]
    admin_id = update.effective_user.id
    admin_name = update.effective_user.full_name or update.effective_user.username or str(admin_id)

    withdrawal_data = None
    is_bep20 = False
    lock_acquired = False

    try:
    # التحقق من حالة الطلب
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            raise Exception("لم يتم العثور على بيانات الطلب")

    # التحقق من الحالة الحالية
        current_status = withdrawal_data.get('status', '').lower()
        if current_status == 'completed':
        # تعريف المتغيرات مع قيم افتراضية
            registration_code = "غير متوفر"

            try:
            # جلب رمز التسجيل للمستخدم
                if withdrawal_data.get('user_id'):
                   registration_code = await get_user_registration_code(withdrawal_data.get('user_id'))
            except Exception as e:
                logger.error(f"خطأ في جلب رمز التسجيل: {e}")

        # تنسيق الوقت بشكل صحيح
            try:
                completion_time = format_time_yemen(withdrawal_data.get('completion_time')) if withdrawal_data.get('completion_time') else 'غير معروف'
            except Exception as e:
                logger.error(f"خطأ في تنسيق الوقت: {e}")
                completion_time = 'غير معروف'

            await query.edit_message_text(
            "⚠️ *تم تنفيذ هذا الطلب مسبقاً*\n\n"
            f"👤 *معرف المستخدم:* `{withdrawal_data.get('user_id', 'غير معروف')}`\n"
            f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
            f"💵 *المبلغ:* {withdrawal_data.get('local_amount', 0):,.2f} {withdrawal_data.get('local_currency_name', 'غير معروف')}\n"
            f"🔢 *رقم الحوالة:* `{withdrawal_data.get('transfer_number', 'غير معروف')}`\n"
            f"🏦 *جهة الإصدار:* `{withdrawal_data.get('transfer_issuer', 'غير معروف')}`\n"
            f"🌐 *الشبكة:* `{withdrawal_data.get('network', 'غير معروف')}`\n"
            f"👮‍♂️ *تم التنفيذ بواسطة:* `{withdrawal_data.get('executed_by', 'غير معروف')}`\n"
            f"⏱️ *وقت التنفيذ:* {completion_time}",
                parse_mode=ParseMode.MARKDOWN
        )
            return
        elif current_status in ['failed', 'rejected']:
            await query.edit_message_text(
            f"❌ *هذا الطلب {current_status}*\n"
            f"📝 *السبب:* {withdrawal_data.get('cancellation_reason', 'غير معروف')}",
            parse_mode=ParseMode.MARKDOWN
        )
            return

        # محاولة الحصول على قفل للمعاملة
        lock_acquired = await withdrawal_manager.acquire_lock(withdrawal_id, admin_id, admin_name)
        if not lock_acquired:
            # تجنب الردود المتكررة على نفس المشرف
            if rate_limiter.can_respond_to_user(admin_id):
                lock_info = await withdrawal_manager.get_lock_info(withdrawal_id)
                if lock_info:
                    time_diff = datetime.now(timezone.utc).timestamp() - lock_info.start_time
                    await rate_limiter.acquire('edit_message')
                    await query.edit_message_text(
                        "⚠️ *جاري معالجة الطلب من قبل مشرف آخر*\n\n"
                        f"👮‍♂️ *يتم التنفيذ بواسطة:* {lock_info.admin_name}\n"
                        f"⏱ *منذ:* {format_duration(time_diff)}",
                        parse_mode=ParseMode.MARKDOWN
                    )
            return

        # إعادة التحقق من حالة الطلب بعد الحصول على القفل (للتأكد من عدم تغييره)
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if withdrawal_data.get('status', '').lower() != current_status:
            await query.edit_message_text(
                "⚠️ *تم تغيير حالة الطلب بواسطة مشرف آخر*\n"
                f"الحالة الحالية: *{withdrawal_data.get('status', 'غير معروفة')}*",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        try:
            # تحديث حالة الطلب إلى processing
            current_time = datetime.now(timezone.utc)
            
            # التحقق من الحالة قبل التحديث
            withdrawal = await get_withdrawal(withdrawal_id)
            if withdrawal.get('status') not in ['pending']:
                logger.warning(f"⚠️ محاولة تحديث طلب في حالة غير مناسبة: {withdrawal.get('status')}")
                await query.edit_message_text(f"⚠️ لا يمكن معالجة الطلب في الحالة: {withdrawal.get('status')}")
                await withdrawal_manager.release_lock(withdrawal_id)
                return
            
            # استخدام المعاملة الواحدة للتحديث
            update_result = await update_withdrawal_status(
                withdrawal_id=withdrawal_id,
                status='processing',
                executed_by=admin_id,
                processing_start=current_time
            )
            
            # التحقق من نجاح تحديث الحالة
            if not update_result:
                logger.warning(f"فشل تحديث حالة الطلب {withdrawal_id} إلى processing")
                raise Exception("فشل تحديث حالة الطلب")

            # تحديث رسالة المشرف
            await rate_limiter.acquire('edit_message')
            await query.edit_message_text(
                "⏳ *جاري تنفيذ التحويل...*\n\n"
                f"👤 *معرف المستخدم:* `{withdrawal_data['user_id']}`\n"
                f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"👮‍♂️ *يتم التنفيذ بواسطة:* {admin_name}",
                parse_mode=ParseMode.MARKDOWN
            )

            # التحقق من نوع الشبكة
            network_code = withdrawal_data.get('network_code', '').lower()
            is_bep20 = any(x in network_code for x in ['bep20', 'bsc', 'bnb'])

            # حساب المبالغ والعمولات
            local_amount = float(withdrawal_data['local_amount'])
            local_currency = withdrawal_data['local_currency']
            exchange_rates = await get_exchange_rates()
            
            if local_currency not in exchange_rates:
                raise Exception(f"سعر الصرف غير متوفر للعملة {local_currency}")
                
            usd_amount = local_amount / exchange_rates.get(local_currency, 1)

            # التحقق من الحدود
            if is_bep20:
                min_limit = float(await get_setting('BEP20_MIN_WITHDRAWAL_USD') or 20.0)
                max_limit = float(await get_setting('BEP20_MAX_WITHDRAWAL_USD') or 5000.0)
                if usd_amount < min_limit:
                    raise Exception(f"المبلغ أقل من الحد الأدنى المسموح به لشبكة BEP20 ({min_limit:,.2f} USD)")
                if usd_amount > max_limit:
                    raise Exception(f"المبلغ أكبر من الحد الأقصى المسموح به لشبكة BEP20 ({max_limit:,.2f} USD)")
            else:
                min_limit = float(await get_setting('MIN_WITHDRAWAL_USD') or 12.0)
                max_limit = float(await get_setting('MAX_WITHDRAWAL_USD') or 1000.0)
                if usd_amount < min_limit:
                    raise Exception(f"المبلغ أقل من الحد الأدنى المسموح به ({min_limit:,.2f} USD)")
                if usd_amount > max_limit:
                    raise Exception(f"المبلغ أكبر من الحد الأقصى المسموح به ({max_limit:,.2f} USD)")

            # حساب العمولة
            commission_threshold = float(await get_setting('COMMISSION_THRESHOLD_USD') or 30.0)
            fixed_commission = float(await get_setting('FIXED_COMMISSION_USD') or 1.0)
            percentage_rate = float(await get_setting('PERCENTAGE_COMMISSION_RATE') or 0.03)

            if usd_amount <= commission_threshold:
                fee_amount = fixed_commission
                net_amount = usd_amount - fixed_commission
            else:
                commission_multiplier = 1 + percentage_rate
                net_amount = usd_amount / commission_multiplier
                fee_amount = usd_amount - net_amount

            # تنفيذ التحويل
            result = None
            if is_bep20:
                logger.info("Using External Wallet Service for BEP20/BSC network")
                if not hasattr(external_wallet_service, 'account'):
                    raise Exception("المحفظة الخارجية غير مهيأة")
                
                if not await external_wallet_service.check_balance(net_amount):
                    raise Exception("رصيد المحفظة الخارجية غير كافٍ لتنفيذ العملية")
                
                result = await external_wallet_service.withdraw(
                    address=withdrawal_data['wallet_address'],
                    amount=float(net_amount)
                )
            # إضافة معالجة خاصة لشبكة APTOS
            elif network_code == 'APTOS':
                logger.info("Using Test Mode for APTOS network (not supported by Binance API)")
                # إنشاء نتيجة وهمية لشبكة APTOS (وضع اختبار دائم)
                # ملاحظة: واجهة برمجة التطبيقات (API) لـ Binance لا تدعم حاليًا سحب USDT على شبكة APTOS
                # لذلك نستخدم وضع اختبار دائم للتعامل مع هذا النوع من المعاملات
                result = {
                    'id': f"APTOS_WD_{int(time.time())}",
                    'txId': f"APTOS_TX_{int(time.time())}",
                    'status': 'completed',
                    'amount': net_amount,
                    'address': withdrawal_data['wallet_address'],
                    'coin': withdrawal_data['crypto_currency'],
                    'network': network_code,
                    'test_mode': True
                }
                logger.warning(f"وضع الاختبار لشبكة APTOS: تم إنشاء معاملة وهمية {result['txId']}")
            else:
                logger.info(f"Using Binance Service for {network_code} network")
                result = await binance_service.withdraw(
                    coin=withdrawal_data['crypto_currency'],
                    address=withdrawal_data['wallet_address'],
                    amount=net_amount,
                    network=withdrawal_data['network_code']
                )

            if not result or 'txId' not in result:
                raise Exception("لم يتم الحصول على رقم المعاملة")

            # تحديث حالة الطلب إلى مكتمل
            completion_time = datetime.now(timezone.utc)
            
            # التحقق من الحالة قبل التحديث
            current_withdrawal = await get_withdrawal(withdrawal_id)
            if current_withdrawal.get('status') != 'processing':
                logger.warning(f"⚠️ محاولة إكمال طلب في حالة: {current_withdrawal.get('status')}")
                raise Exception(f"حالة الطلب غير مناسبة للإكمال: {current_withdrawal.get('status')}")

            await update_withdrawal_status(
                withdrawal_id,
                'completed',
                executed_by=admin_id,
                completion_time=completion_time.replace(tzinfo=timezone.utc),
                tx_hash=result['txId']
            )

            # إرسال رسالة النجاح للمستخدم
            success_message = (
                "✅ *تم تنفيذ طلبك بنجاح!*\n\n"
                f"💰 *المبلغ:* {local_amount:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n\n"
                "*تفاصيل التحويل:*\n"
                f"🔍 *معرف العملية:* `{result['txId']}`\n"
                f"💱 *العملة المشفرة:* {withdrawal_data['crypto_currency']}\n"
                f"🌐 *الشبكة:* {withdrawal_data['network_name']}\n"
                f"👛 *عنوان المحفظة:* `{withdrawal_data['wallet_address']}`\n"
                f"💸 *العمولة:* {fee_amount:,.2f} USD\n"
                f"📤 *المبلغ المرسل:* {net_amount:,.6f} {withdrawal_data['crypto_currency']}\n\n"
                "⚠️ **تحذير:** العملات الرقمية المحوَّلة *غير قابلة للاسترجاع.*\n"
                "أنت تتحمل كامل المسؤولية عن **عنوان المحفظه المرسل لها** ومعلومات التحويل.\n"
                "لا نتحمّل أي مسؤولية عن أي **خسارة** أو **فقدان للأموال**.\n"
                "كما أننا نخلي مسؤوليتنا بالكامل من أي تعاملات أو التزامات بين المرسل والمستلم."
            )

            keyboard = [[InlineKeyboardButton("🚀 طلب جديد", callback_data="start_new")]]
            
            await context.bot.send_message(
                chat_id=withdrawal_data['user_id'],
                text=success_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )

            registration_code = await get_user_registration_code(withdrawal_data['user_id'])
            # تحديث رسالة المشرف
            admin_message = (
                "✅ *تم تنفيذ العملية بنجاح*\n\n"
                f"👤 *معرف المستخدم:* `{withdrawal_data['user_id']}`\n"
                f"*🎫 اسم العميل بالنظام:* `{registration_code}`\n"
                f"💰 *المبلغ:* {local_amount:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
                f"*🏦 جهة الإصدار:* {withdrawal_data['transfer_issuer']}\n"
                f"🌐 *الشبكة:* {withdrawal_data['network_name']}\n"
                f"👮‍♂️ *تم التنفيذ بواسطة:* {admin_name}\n"
                f"⌚️ *وقت التنفيذ:* {format_time_yemen(datetime.now(timezone.utc))}\n"
            )

            await query.edit_message_text(
                admin_message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # تسجيل نجاح العملية
            logger.info(f"✅ تم تنفيذ التحويل بنجاح للطلب {withdrawal_id} بواسطة {admin_name}")

        except Exception as e:
            logger.error(f"خطأ في تنفيذ التحويل: {e}")
            error_message = f"❌ *فشل تنفيذ التحويل*\n\nالسبب: {str(e)}"
            
            # تحديث حالة الطلب إلى فاشل مع ضمان وجود معلومات المنطقة الزمنية
            failure_time = datetime.now(timezone.utc)
            await update_withdrawal_status(
                withdrawal_id,
                'failed',
                reason=str(e),
                failed_by=admin_id,
                failure_time=failure_time.replace(tzinfo=timezone.utc)
            )

            # إرسال رسالة الخطأ للمشرف
            await query.edit_message_text(
                error_message,
                parse_mode=ParseMode.MARKDOWN
            )

            # إرسال إشعار للمستخدم
            if withdrawal_data:
                await context.bot.send_message(
                    chat_id=withdrawal_data['user_id'],
                    text="❌ عذراً، حدث خطأ أثناء تنفيذ طلبك. سيتواصل معك المشرفون قريباً.",
                    parse_mode=ParseMode.MARKDOWN
                )

    except Exception as e:
        logger.error(f"خطأ غير متوقع: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى.",
            parse_mode=ParseMode.MARKDOWN
        )

    finally:
        # تحرير القفل في حالة الحصول عليه سابقاً
        if lock_acquired:
            logger.info(f"إطلاق القفل للطلب {withdrawal_id}")
            await withdrawal_manager.release_lock(withdrawal_id)

# دالة لمعالجة سبب الرفض
async def handle_reject_reason(update: Update, context: CallbackContext):
    """معالجة اختيار سبب الرفض."""
    query = update.callback_query
    await query.answer()

    try:
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

        # التحقق من حالة الطلب
        withdrawal = await get_withdrawal(withdrawal_id)
        if not withdrawal:
            await query.edit_message_text("❌ لم يتم العثور على الطلب.")
            return
            
        # التحقق من أن الطلب ليس مكتملاً
        if withdrawal.get('status') == 'completed':
            logger.warning(f"⚠️ محاولة رفض طلب مكتمل: {withdrawal_id}")
            await query.edit_message_text("⚠️ لا يمكن رفض طلب تم إكماله بالفعل.")
            return
            
        # محاولة اكتساب قفل للطلب
        admin_id = update.effective_user.id
        admin_user = await context.bot.get_chat(admin_id)
        admin_name = admin_user.full_name or admin_user.username or str(admin_id)
        
        from services.withdrawal_manager import withdrawal_manager
        lock_acquired = await withdrawal_manager.acquire_lock(withdrawal_id, admin_id, admin_name)
        
        if not lock_acquired:
            logger.warning(f"⚠️ فشل في اكتساب قفل الطلب {withdrawal_id} للرفض")
            await query.edit_message_text(
                "⚠️ لا يمكن معالجة الطلب حالياً، قد يكون تحت المعالجة من قبل مشرف آخر",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # تحديث حالة الطلب
        await update_withdrawal_status(withdrawal_id, 'rejected', reason)

        # استرجاع بيانات السحب
        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await query.edit_message_text(
                "❌ لم يتم العثور على بيانات الطلب",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        user_id = withdrawal_data['user_id']

        # إنشاء زر البدء
        start_keyboard = [[InlineKeyboardButton("🚀 ابدأ عملية جديدة", callback_data="start_new")]]

        # إشعار المستخدم
        user_message = (
            "❌ *تم رفض طلب التحويل*\n\n"
            f"📝 *السبب:* {reason}\n"
            "يمكنك بدء طلب جديد عن طريق الضغط على الزر أدناه."
        )

        await telegram_service.send_message(
            chat_id=user_id,
            text=user_message,
            reply_markup=InlineKeyboardMarkup(start_keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

        # تحديث رسالة المشرف
        await query.edit_message_text(
            f"✅ *تم رفض الطلب بنجاح*\n\n"
            f"👤 *المستخدم:* `{user_id}`\n"
            f"📝 *السبب:* {reason}",
            parse_mode=ParseMode.MARKDOWN
        )

        # إشعار للمشرفين
        admin_message = (
            "ℹ️ *تم رفض طلب*\n\n"
            f"👤 *معرف المستخدم:* `{user_id}`\n"
            f"📝 *السبب:* {reason}\n"
            f"👮‍♂️ *تم الرفض بواسطة:* `{update.effective_user.id}`"
        )

        if ADMIN_USER_IDS:
            for admin_id in ADMIN_USER_IDS:
                await telegram_service.send_message(
                    chat_id=admin_id,
                    text=admin_message,
                    parse_mode=ParseMode.MARKDOWN
                )

    except Exception as e:
        logger.error(f"خطأ في معالجة سبب الرفض: {e}")
        if "Chat not found" in str(e):
            await query.edit_message_text(
                "✅ *تم رفض الطلب*\n\n"
                f"📝 *السبب:* {reason}\n"
                f"👮‍♂️ *تم الرفض بواسطة:* `{update.effective_user.id}`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
           await query.edit_message_text(
               "❌ حدث خطأ أثناء معالجة الرفض",
               parse_mode=ParseMode.MARKDOWN
        )
    finally:
        # تحرير القفل في جميع الحالات
        if 'withdrawal_id' in locals() and lock_acquired:
            await withdrawal_manager.release_lock(withdrawal_id)
            logger.info(f"✅ تم تحرير قفل الطلب {withdrawal_id} بعد محاولة الرفض")

# دالة لإلغاء العملية
async def cancel_admin_action(update: Update, context: CallbackContext):
    """إلغاء عملية المشرف مع سبب الإلغاء."""
    query = update.callback_query
    await query.answer()

    data = query.data.split('_')
    if len(data) < 3:
        await query.edit_message_text("❌ بيانات الطلب غير صحيحة.")
        return

    withdrawal_id = data[2]

    # إنشاء أزرار لأسباب الإلغاء
    keyboard = [
        [InlineKeyboardButton(reason, callback_data=f"admin_cancel_reason_{withdrawal_id}_{key}")]
        for key, reason in CANCELLATION_REASONS.items()
    ]

    await query.edit_message_text(
        "❌ *الرجاء اختيار سبب الإلغاء:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

# دالة لمعالجة سبب إلغاء المشرف
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

        # التحقق من صحة معرف المشرف
        if update.effective_user.id not in ADMIN_USER_IDS:
            await query.edit_message_text(
                "❌ ليس لديك صلاحية لتنفيذ هذا الإجراء.",
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
        await query.edit_message_text(
            f"✅ *تم إلغاء الطلب بنجاح*\n\n"
            f"👤 *معرف المستخدم:* `{user_id}`\n"
            f"💰 *المبلغ:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
            f"🏦 *العملة المشفرة:* {withdrawal_data['crypto_currency']}\n"
            f"📝 *سبب الإلغاء:* {reason}\n"
            f"⏱ *وقت الإلغاء:* {format_time_yemen(datetime.now(timezone.utc))}"
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
# دالة لإضافة رمز أو عدة رموز تسجيل
async def add_code(update: Update, context: CallbackContext):
    """إضافة رمز تسجيل جديد إلى قاعدة البيانات."""
    user_id = update.effective_user.id
    logger.info(f"User {user_id} attempted to add registration code(s).")

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ لا تمتلك الصلاحيات اللازمة لتنفيذ هذا الأمر.")
        logger.warning(f"User {user_id} does not have permission to add registration codes.")
        return

    # الحصول على النص الكامل بعد الأمر
    text = update.message.text
    try:
        # استخدام shlex.split لتحليل النص مع احترام علامات الاقتباس
        args = shlex.split(text)
        # إزالة الأمر نفسه من القائمة
        args = args[1:]
    except ValueError as e:
        await update.message.reply_text("❌ هناك خطأ في صيغة الرموز. تأكد من استخدام علامات الاقتباس بشكل صحيح.")
        logger.error(f"Error parsing arguments: {e}")
        return

    if len(args) < 1:
        await update.message.reply_text("❌ الرجاء تحديد رمز أو عدة رموز التسجيل. الاستخدام: /addcode \"رمز1\" \"رمز2\" ...")
        return

    added_codes = []
    failed_codes = []

    for code in args:
        try:
            await add_registration_code(code)
            added_codes.append(code)
        except ValueError as ve:
            failed_codes.append(str(ve))
        except Exception as e:
            failed_codes.append(f"رمز '{code}': {str(e)}")

    response_message = ""

    if added_codes:
        response_message += f"✅ تم إضافة الرموز التالية بنجاح:\n" + "\n".join(added_codes) + "\n"

    if failed_codes:
        response_message += f"❌ لم يتم إضافة الرموز التالية:\n" + "\n".join(failed_codes)

    await update.message.reply_text(response_message, parse_mode=ParseMode.MARKDOWN)

    logger.info(f"Added codes: {added_codes}")
    if failed_codes:
        logger.warning(f"Failed to add codes: {failed_codes}")
async def delete_code(update: Update, context: CallbackContext):
    """أمر حذف كود التسجيل"""
    try:
        user_id = update.effective_user.id

        # التحقق من صلاحيات المشرف
        if user_id not in ADMIN_USER_IDS:
            await update.message.reply_text(
                "❌ ليس لديك صلاحية لتنفيذ هذا الأمر.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # التحقق من وجود الكود في الرسالة
        if not context.args:
            await update.message.reply_text(
                "❌ *خطأ في الأمر*\n\n"
                "الاستخدام الصحيح: /deletecode <الكود>\n"
                "مثال: /deletecode ABC123 أو /deletecode \"محمد احمد\"",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # جمع جميع الوسائط ككود واحد للسماح بالكود متعدد الكلمات
        code = ' '.join(context.args).strip()

        # التعامل مع علامات الاقتباس إذا كانت موجودة
        quotes = ['"', "'", '«', '»']
        if code and code[0] in quotes and code[-1] in quotes:
            code = code[1:-1].strip()

        # التحقق من أن الكود غير فارغ بعد التنظيف
        if not code:
            await update.message.reply_text(
                "❌ الكود المقدم فارغ بعد إزالة علامات الاقتباس.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        logger.info(f"المشرف {user_id} يحاول حذف الكود: '{code}'")

        # محاولة حذف الكود من قاعدة البيانات
        success, message = await delete_registration_code(code)

        # إرسال رد بناءً على نتيجة الحذف
        if success:
            await update.message.reply_text(
                f"✅ {message}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"❌ {message}",
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"❌ خطأ أثناء تنفيذ أمر delete_code: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء تنفيذ الأمر. الرجاء المحاولة مرة أخرى لاحقاً.",
            parse_mode=ParseMode.MARKDOWN
        )
async def handle_admin_confirmation(update: Update, context: CallbackContext) -> int:
    """معالجة تأكيد المشرف"""
    query = update.callback_query
    await query.answer()

    try:
        # التحقق من أن المستخدم مشرف
        user_id = update.effective_user.id
        if str(user_id) not in ADMIN_USER_IDS:
            await query.edit_message_text("❌ ليس لديك صلاحية للقيام بهذا الإجراء.")
            return ConversationHandler.END
      
        data = query.data.split('_')
        if len(data) < 3:
            await query.edit_message_text("❌ بيانات الطلب غير صحيحة.")
            return ConversationHandler.END

        action = data[1]
        withdrawal_id = data[2]

        withdrawal_data = await get_withdrawal(withdrawal_id)
        if not withdrawal_data:
            await query.edit_message_text(
                "❌ لم يتم العثور على بيانات الطلب",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # جلب رمز التسجيل للمستخدم
        registration_code = await get_user_registration_code(withdrawal_data['user_id'])

        if action == "confirm":
            # عرض تأكيد نهائي
            # تنظيف وتقصير النصوص الطويلة
            transfer_number = withdrawal_data['transfer_number'][:20] + "..." if len(withdrawal_data['transfer_number']) > 20 else withdrawal_data['transfer_number']
            transfer_issuer = withdrawal_data['transfer_issuer'][:20] + "..." if len(withdrawal_data['transfer_issuer']) > 20 else withdrawal_data['transfer_issuer']
            
            confirmation_message = (
                "⚠️ *تأكيد نهائي لقبول الحوالة*\n\n"
                f"👤 *معرف المستخدم:* `{withdrawal_data['user_id']}`\n"
                f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
                f"💵 *المبلغ المدفوع:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* `{transfer_number}`\n"
                f"🏦 *جهة الإصدار:* `{transfer_issuer}`\n\n"
                "هل أنت متأكد من قبول الحوالة؟"
            )

            keyboard = [
    [
        InlineKeyboardButton(
            "✅ نعم، تنفيذ التحويل",
            callback_data=f"execute_{withdrawal_id}"  # تصحيح الإملاء
        ),
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=f"admin_back_{withdrawal_id}"
        )
    ]
]

            await query.edit_message_text(
                confirmation_message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
            return CONFIRMATION

        elif action == "back":
            # العودة إلى القائمة الرئيسية
            admin_message = (
                f"👤 *طلب سحب جديد من المستخدم:* `{withdrawal_data['user_id']}`\n\n"
                f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
                f"💰 *المبلغ المدفوع:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
                f"🏦 *جهة الإصدار:* {withdrawal_data['transfer_issuer']}\n"
                f"📅 *وقت الطلب:* {format_time_yemen(withdrawal_data['created_at'])}"

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
            return ConversationHandler.END

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

        return CONFIRMATION

    except Exception as e:
        logger.error(f"خطأ في معالجة تأكيد المشرف: {e}")
        await query.edit_message_text(
            "❌ حدث خطأ أثناء معالجة الطلب.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
# تعريف معالجات المشرفين
def get_admin_handlers():
    """إرجاع معالجات المشرف."""
    return [
        CommandHandler('listusers', list_users),  # إضافة الأمر الجديد
        CommandHandler('deletecode', delete_code),  # أمر حذف الكود
        CallbackQueryHandler(execute_withdrawal, pattern=r"^execute_"),
        CallbackQueryHandler(handle_reject_reason, pattern=r"^reject_reason_"),
        CallbackQueryHandler(cancel_admin_action, pattern=r"^cancel_admin_"),
        CallbackQueryHandler(handle_admin_cancel_reason, pattern=r"^admin_cancel_reason_"),
        CommandHandler('setmin', set_min_withdrawal),
        CommandHandler('setmax', set_max_withdrawal),
        CommandHandler('setcommissionthreshold', set_commission_threshold),
        CommandHandler('setfixedcommission', set_fixed_commission),
        CommandHandler('setcommissionrate', set_commission_rate),
        CommandHandler('rates', show_exchange_rates),  # عرض أسعار الصرف
        CommandHandler('setrate', set_exchange_rate),  # تحديث سعر صرف
        CommandHandler('deleterate', delete_exchange_rate),  # حذف عملة
        CommandHandler('bep20limits', bep20_limits),
        CommandHandler('setbep20min', set_bep20_min),
        CommandHandler('setbep20max', set_bep20_max),
        CommandHandler('addcode', add_code)

    ]

# تصدير الدوال
__all__ = [
    'get_admin_handlers'
]
async def get_all_users_with_codes():
    """
    استرجاع جميع المستخدمين مع أكواد التسجيل الخاصة بهم
    
    Returns:
        list: قائمة بمعلومات المستخدمين وأكوادهم
    """
    conn = None
    try:
        conn = await get_connection()
        rows = await conn.fetch("""
            SELECT 
                u.user_id,
                u.registration_date,
                u.is_registered,
                rc.code
            FROM users u
            LEFT JOIN registration_codes rc 
                ON u.user_id = rc.user_id 
                AND rc.is_used = TRUE
            ORDER BY u.registration_date DESC
        """)
        
        return [dict(row) for row in rows]
        
    except Exception as e:
        logger.error(f"Error fetching users with codes: {e}")
        return []
    finally:
        if conn:
            await release_connection(conn)
async def list_users(update: Update, context: CallbackContext):
    try:
        if update.effective_user.id not in ADMIN_USER_IDS:
            await update.message.reply_text("❌ ليس لديك صلاحية لتنفيذ هذا الأمر.")
            return

        users = await get_all_users_with_codes()
        if not users:
            await update.message.reply_text("لا يوجد مستخدمين مسجلين حالياً.")
            return

        current_message = "قائمة المستخدمين:\n\n"
        
        for user in users:
            try:
                user_id = user['user_id']
                code = user['code'] or 'لا يوجد كود'
                status = "✅" if user['is_registered'] else "❌"
                date = user['registration_date'].strftime('%Y-%m-%d') if user['registration_date'] else 'غير محدد'
                
                user_line = f"المستخدم: {user_id} | {status} | الكود: {code} | التاريخ: {date}\n"
                
                if len(current_message + user_line) > 3000:
                    await update.message.reply_text(current_message)
                    current_message = user_line
                else:
                    current_message += user_line

            except Exception as e:
                logger.error(f"خطأ في معالجة بيانات المستخدم {user['user_id']}: {e}")
                continue

        if current_message:
            await update.message.reply_text(current_message)

        # إرسال الإحصائيات
        active_users = sum(1 for user in users if user['is_registered'])
        stats = (
            f"إحصائيات المستخدمين:\n"
            f"إجمالي المستخدمين: {len(users)}\n"
            f"المستخدمين النشطين: {active_users}\n"
            f"المستخدمين غير النشطين: {len(users) - active_users}"
        )
        
        await update.message.reply_text(stats)

    except Exception as e:
        logger.error(f"خطأ في تنفيذ أمر list_users: {e}")
        await update.message.reply_text("حدث خطأ أثناء جلب قائمة المستخدمين. الرجاء المحاولة مرة أخرى لاحقاً.")
async def bep20_limits(update: Update, context: CallbackContext):
    """عرض حدود شبكة BEP20 الحالية"""
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر متاح للمشرفين فقط.")
        return

    try:
        min_limit = float(await get_setting('BEP20_MIN_WITHDRAWAL_USD') or 20.0)
        max_limit = float(await get_setting('BEP20_MAX_WITHDRAWAL_USD') or 5000.0)
        
        message = (
            "*🔄 حدود السحب الحالية لشبكة BEP20:*\n\n"
            f"📉 *الحد الأدنى:* `{min_limit:,.2f}` USD\n"
            f"📈 *الحد الأقصى:* `{max_limit:,.2f}` USD\n\n"
            "📝 *لتغيير الحدود استخدم:*\n"
            "`/setbep20min <المبلغ>` - تعيين الحد الأدنى\n"
            "`/setbep20max <المبلغ>` - تعيين الحد الأقصى\n\n"
            "مثال:\n"
            "`/setbep20min 50`\n"
            "`/setbep20max 2000`"
        )
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"خطأ في عرض حدود BEP20: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء جلب الحدود.")

async def set_bep20_min(update: Update, context: CallbackContext):
    """تعيين الحد الأدنى للسحب لشبكة BEP20"""
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر متاح للمشرفين فقط.")
        return

    try:
        if not context.args:
            await update.message.reply_text(
                "❌ *يجب تحديد المبلغ*\n\n"
                "*الاستخدام:* `/setbep20min <المبلغ>`\n"
                "*مثال:* `/setbep20min 50`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        min_amount = float(context.args[0])
        if min_amount <= 0:
            await update.message.reply_text("❌ يجب أن يكون المبلغ أكبر من 0")
            return

        await set_setting('BEP20_MIN_WITHDRAWAL_USD', str(min_amount))
        
        message = (
            "✅ *تم تحديث الحد الأدنى لشبكة BEP20 بنجاح*\n\n"
            f"💰 *الحد الأدنى الجديد:* `{min_amount:,.2f}` USD"
        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح")
    except Exception as e:
        logger.error(f"خطأ في تعيين الحد الأدنى لـ BEP20: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث الحد الأدنى.")

async def set_bep20_max(update: Update, context: CallbackContext):
    """تعيين الحد الأقصى للسحب لشبكة BEP20"""
    if update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ عذراً، هذا الأمر متاح للمشرفين فقط.")
        return

    try:
        if not context.args:
            await update.message.reply_text(
                "❌ *يجب تحديد المبلغ*\n\n"
                "*الاستخدام:* `/setbep20max <المبلغ>`\n"
                "*مثال:* `/setbep20max 2000`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        max_amount = float(context.args[0])
        if max_amount <= 0:
            await update.message.reply_text("❌ يجب أن يكون المبلغ أكبر من 0")
            return

        await set_setting('BEP20_MAX_WITHDRAWAL_USD', str(max_amount))
        
        message = (
            "✅ *تم تحديث الحد الأقصى لشبكة BEP20 بنجاح*\n\n"
            f"💰 *الحد الأقصى الجديد:* `{max_amount:,.2f}` USD"
        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        await update.message.reply_text("❌ يرجى إدخال رقم صحيح")
    except Exception as e:
        logger.error(f"خطأ في تعيين الحد الأقصى لـ BEP20: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء تحديث الحد الأقصى.")

from datetime import datetime, timezone
import pytz

# تعريف المنطقة الزمنية لليمن
YEMEN_TZ = pytz.timezone('Asia/Aden')

def format_duration(seconds: int) -> str:
    """
    تنسيق المدة الزمنية من الثواني إلى نص مقروء
    """
    if seconds < 60:
        return f"{seconds} ثانية"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} دقيقة"
    else:
        hours = seconds // 3600
        return f"{hours} ساعة"

def format_time_yemen(dt):
    """تنسيق الوقت بتوقيت اليمن ونظام 12 ساعة"""
    yemen_time = dt.astimezone(YEMEN_TZ)
    return yemen_time.strftime('%Y-%m-%d %I:%M:%S %p')
async def periodic_cleanup(context: CallbackContext):
    """تنفيذ التنظيف الدوري للبيانات القديمة"""
    try:
        # تنظيف الإجراءات القديمة
        await cleanup_admin_actions()
        logger.info("تم تنفيذ التنظيف الدوري بنجاح")
    except Exception as e:
        logger.error(f"خطأ في التنظيف الدوري: {e}")