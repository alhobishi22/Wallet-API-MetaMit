from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ConversationHandler,
    CallbackContext,
    MessageHandler,
    CallbackQueryHandler,
    filters
    
)
from telegram.error import BadRequest
import datetime
import asyncio
from telegram.constants import ParseMode
import logging
from config.settings import ADMIN_USER_IDS, ADMIN_GROUP_ID
from services.database_service import get_withdrawal, update_withdrawal_status, get_user_registration_code
from services.binance_service import binance_service

# قاموس لتخزين حالة المعالجة لكل طلب
processing_requests = {}

logger = logging.getLogger(__name__)

# حالات المحادثة
(
    AWAITING_REJECTION_REASON,  # انتظار سبب الرفض
) = range(1)

async def handle_admin_button(update: Update, context: CallbackContext) -> int:
   """معالجة أزرار المشرفين"""
   query = update.callback_query
   await query.answer()

   try:
       data = query.data
       withdrawal_id = data.split('_')[-1]

       withdrawal_data = await get_withdrawal(withdrawal_id)
       if not withdrawal_data:
           await query.edit_message_text(
               "❌ لم يتم العثور على بيانات الطلب",
               parse_mode=ParseMode.MARKDOWN
           )
           return ConversationHandler.END

       user_id = update.effective_user.id
       registration_code = await get_user_registration_code(withdrawal_data['user_id'])

       if "admin_confirm" in data:
           confirmation_message = (
               "*⚠️ تأكيد نهائي لقبول الحوالة*\n\n"
               f"*👤 معرف المستخدم:* `{withdrawal_data['user_id']}`\n"
               f"*🎫 اسم العميل بالنظام:* `{registration_code}`\n"
               f"*💵 المبلغ المدفوع:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
               f"*🔢 رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
               f"*🏦 جهة الإصدار:* {withdrawal_data['transfer_issuer']}\n\n"
               "*هل أنت متأكد من قبول الحوالة؟*"
           )

           keyboard = [
               [
                   InlineKeyboardButton("✅ نعم، تنفيذ التحويل", callback_data=f"execute_{withdrawal_id}"),
                   InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{withdrawal_id}")
               ]
           ]

           try:
               await query.edit_message_text(
                   confirmation_message,
                   reply_markup=InlineKeyboardMarkup(keyboard),
                   parse_mode=ParseMode.MARKDOWN
               )
           except BadRequest as e:
               if "Message is not modified" not in str(e):
                   raise

       elif "admin_reject" in data:
           context.user_data['pending_rejection_id'] = withdrawal_id
           context.user_data['original_message_id'] = query.message.message_id

           await query.edit_message_text(
               "📝 *الرجاء كتابة سبب الرفض:*\n\n"
               "اكتب سبب رفض الطلب في رسالة جديدة.",
               parse_mode=ParseMode.MARKDOWN,
               reply_markup=InlineKeyboardMarkup([[
                   InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{withdrawal_id}")
               ]])
           )
           return AWAITING_REJECTION_REASON

       elif "admin_back" in data:
           admin_message = (
               f"👤 *طلب سحب جديد من المستخدم:* `{withdrawal_data['user_id']}`\n\n"
               f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
               f"💵 *المبلغ المدفوع:* {withdrawal_data['local_amount']:,.2f} {withdrawal_data['local_currency_name']}\n"
               f"🔢 *رقم الحوالة:* {withdrawal_data['transfer_number']}\n"
               f"🏦 *جهة الإصدار:* {withdrawal_data['transfer_issuer']}\n"
               f"📅 *وقت الطلب:* {withdrawal_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')}"


           )

           admin_keyboard = [
               [
                   InlineKeyboardButton("✅ تأكيد", callback_data=f"admin_confirm_{withdrawal_id}"),
                   InlineKeyboardButton("❌ رفض", callback_data=f"admin_reject_{withdrawal_id}")
               ]
           ]

           try:
               await query.edit_message_text(
                   admin_message,
                   reply_markup=InlineKeyboardMarkup(admin_keyboard),
                   parse_mode=ParseMode.MARKDOWN
               )
           except BadRequest as e:
               if "Message is not modified" not in str(e):
                   raise

   except Exception as e:
       logger.error(f"Error processing admin button: {e}")
       await query.edit_message_text(
           "❌ حدث خطأ أثناء معالجة الطلب. الرجاء المحاولة مرة أخرى",
           parse_mode=ParseMode.MARKDOWN
       )
       return ConversationHandler.END

   return ConversationHandler.END

async def handle_rejection_reason(update: Update, context: CallbackContext) -> int:
    """معالجة سبب الرفض المدخل من قبل المشرف"""
    try:
        if 'pending_rejection_id' not in context.user_data:
            await update.message.reply_text(
                "❌ عذراً، لا يوجد طلب رفض معلق",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        withdrawal_id = context.user_data['pending_rejection_id']
        chat_id = update.effective_chat.id
        rejection_reason = update.message.text.strip()

        # التحقق من حالة المعالجة
        if withdrawal_id in processing_requests:
            await update.message.reply_text(
                "⚠️ تم استلام سبب الرفض بالفعل",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # تعيين حالة المعالجة
        processing_requests[withdrawal_id] = True

        try:
            # محاولة اكتساب قفل للطلب
            admin_id = update.effective_user.id
            admin_user = await context.bot.get_chat(admin_id)
            admin_name = admin_user.full_name or admin_user.username or str(admin_id)
            
            # التحقق من الحالة مرة أخرى قبل محاولة القفل
            withdrawal = await get_withdrawal(withdrawal_id)
            if withdrawal.get('status') in ['completed', 'rejected']:
                logger.warning(f"⚠️ محاولة رفض طلب في حالة غير مناسبة: {withdrawal.get('status')}")
                await update.message.reply_text(
                    f"⚠️ لا يمكن رفض الطلب في الحالة: {withdrawal.get('status')}",
                    parse_mode=ParseMode.MARKDOWN
                )
                del processing_requests[withdrawal_id]
                return ConversationHandler.END
                
            # محاولة اكتساب قفل للطلب
            from services.withdrawal_manager import withdrawal_manager
            lock_acquired = await withdrawal_manager.acquire_lock(withdrawal_id, admin_id, admin_name)
            
            if not lock_acquired:
                logger.warning(f"⚠️ فشل في اكتساب قفل الطلب {withdrawal_id} للرفض")
                await update.message.reply_text(
                    "⚠️ لا يمكن معالجة الطلب حالياً، قد يكون تحت المعالجة من قبل مشرف آخر",
                    parse_mode=ParseMode.MARKDOWN
                )
                del processing_requests[withdrawal_id]
                return ConversationHandler.END
            
            # تحديث حالة الطلب إلى مرفوض
            await update_withdrawal_status(withdrawal_id, 'rejected', rejection_reason)

            # إرسال إشعار للمستخدم
            user_message = (
                "❌ *تم رفض طلب السحب*\n\n"
                f"💵 *المبلغ:* {withdrawal['local_amount']:,.2f} {withdrawal['local_currency_name']}\n"
                f"🔢 *رقم الحوالة:* {withdrawal['transfer_number']}\n"
                f"🏦 *جهة الإصدار:* {withdrawal['transfer_issuer']}\n\n"
                f"📝 *سبب الرفض:* {rejection_reason}\n\n"
                "يمكنك تقديم طلب جديد مع مراعاة سبب الرفض"
            )

            keyboard = [[InlineKeyboardButton("🔄 تقديم طلب جديد", callback_data="start_new")]]
            
            try:
                await context.bot.send_message(
                    chat_id=withdrawal['user_id'],
                    text=user_message,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Error sending rejection notification to user {withdrawal['user_id']}: {e}")

            # تحديث الرسالة في مجموعة المشرفين
            admin_user = await context.bot.get_chat(update.effective_user.id)
            admin_name = admin_user.full_name or admin_user.username or str(update.effective_user.id)
            registration_code = await get_user_registration_code(withdrawal['user_id'])

            admin_message = (
              "❌ *تم رفض الطلب وإبلاغ العميل* ❌\n\n"
    f"👤 *معرف المستخدم:* `{withdrawal['user_id']}`\n"
    f"🎫 *اسم العميل بالنظام:* `{registration_code}`\n"
    f"💵 *المبلغ المدفوع:* {withdrawal['local_amount']:,.2f} {withdrawal['local_currency_name']}\n"
    f"🔢 *رقم الحوالة:* {withdrawal['transfer_number']}\n"
    f"🏦 *جهة الإصدار:* {withdrawal['transfer_issuer']}\n"
    f"📝 *سبب الرفض:* {rejection_reason}\n"
    "➖➖➖➖➖➖➖➖➖➖➖➖\n"
    f"⌚️ *وقت التنفيذ:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    f"👮‍♂️ *تم التنفيذ بواسطة:* {admin_name}"
)


            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=context.user_data.get('original_message_id'),
                text=admin_message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # تحرير القفل بعد الانتهاء من المعالجة
            logger.info(f"إطلاق القفل للطلب {withdrawal_id} بعد الرفض")
            await withdrawal_manager.release_lock(withdrawal_id)
            del processing_requests[withdrawal_id]

            return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error processing rejection: {e}")
            # تحرير القفل في حالة حدوث خطأ
            logger.info(f"إطلاق القفل للطلب {withdrawal_id} بسبب فشل المعالجة")
            await withdrawal_manager.release_lock(withdrawal_id)
            del processing_requests[withdrawal_id]
            
            await update.message.reply_text(
                "❌ حدث خطأ أثناء معالجة سبب الرفض. الرجاء المحاولة مرة أخرى",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        finally:
            # تنظيف بيانات المحادثة
            if 'pending_rejection_id' in context.user_data:
                del context.user_data['pending_rejection_id']
            if 'original_message_id' in context.user_data:
                del context.user_data['original_message_id']
            if withdrawal_id in processing_requests:
                del processing_requests[withdrawal_id]

    except Exception as e:
        logger.error(f"Error in rejection handler: {e}")
        await update.message.reply_text(
            "❌ حدث خطأ أثناء معالجة سبب الرفض. الرجاء المحاولة مرة أخرى",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

def get_admin_conversation_handler():
    """إرجاع معالج محادثة المشرفين"""
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_admin_button, pattern='^admin_confirm_'),
            CallbackQueryHandler(handle_admin_button, pattern='^admin_reject_'),
            CallbackQueryHandler(handle_admin_button, pattern='^admin_back_')
        ],
        states={
            AWAITING_REJECTION_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_rejection_reason),
                CallbackQueryHandler(handle_admin_button, pattern='^admin_back_')
            ]
        },
        fallbacks=[
            CallbackQueryHandler(handle_admin_button, pattern='^admin_back_'),
            CallbackQueryHandler(handle_admin_button, pattern='^execute_')
        ],
        name="admin_conversation",
        persistent=False,
        allow_reentry=True
    )
