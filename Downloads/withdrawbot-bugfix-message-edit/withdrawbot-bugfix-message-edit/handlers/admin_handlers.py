import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes, ConversationHandler
from config.config import States, ADMIN_GROUP_ID
from utils.database import Database
from utils.message_utils import send_message_with_retry, edit_message_with_retry, edit_message_reply_markup_with_retry
import logging
import re
import asyncio
from datetime import datetime
from pytz import timezone

__all__ = [
    'admin_response_handler',
    'handle_transfer_info_message',
    'handle_rejection_reason',
    'start_new_transfer',
    'cancel_admin_action'
]

db = Database()
logger = logging.getLogger(__name__)

async def edit_message_with_retry(context, chat_id, message_id, text, parse_mode=None, reply_markup=None):
    """
    Intenta editar un mensaje y maneja los errores comunes.
    Si no se puede editar, intenta enviar un nuevo mensaje.
    """
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )
    except telegram.error.BadRequest as e:
        if "There is no text in the message to edit" in str(e):
            logger.info("El mensaje no tiene texto para editar, enviando un nuevo mensaje")
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            except Exception as send_err:
                logger.error(f"Error al enviar nuevo mensaje: {send_err}")
        else:
            logger.error(f"خطأ في تعديل رسالة: {e}")
            # Si falla la edición, intentamos eliminar el mensaje y enviar uno nuevo
            try:
                await context.bot.delete_message(
                    chat_id=chat_id,
                    message_id=message_id
                )
            except Exception:
                pass
                
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"خطأ في تعديل رسالة: {e}")

async def send_admin_notification(context: ContextTypes.DEFAULT_TYPE, transfer_data: dict):
    """إرسال إشعار للمشرفين عن طلب تحويل جديد"""
    try:
        # الحصول على بيانات المستخدم
        db = Database()
        user_id = transfer_data.get('user_id')
        user_data = db.get_user(user_id)
        registration_code = user_data.get('registration_code', '-') if user_data else '-'
        transfer_id = str(transfer_data.get('transfer_id', ''))

        # تجهيز نص الرسالة
        admin_message = (
            "🔔 إشعار تحويل جديد\n"
            "────────────────\n\n"
            f"📝 رقم العملية: {transfer_id}\n"
            f"👤 المستخدم: @{transfer_data.get('username', '-')}\n"
            f"📝 اسم العميل بالنظام : {registration_code}\n"
            f"📅 تاريخ التسجيل: {user_data.get('registration_date', '-') if user_data else '-'}\n\n"
            "💫 تفاصيل العملية:\n"
            f"نوع العملية: {'تحويل عبر الاسم' if transfer_data.get('transfer_type') == 'name_transfer' else 'إيداع لرقم حساب'}\n"
            f"💰 المبلغ: {transfer_data.get('amount')} USDT\n"
            f"💵 المبلغ بالدولار: {transfer_data.get('usd_amount')} USD\n\n"
        )

        if transfer_data.get('transfer_type') == 'name_transfer':
            admin_message += (
                "👤 معلومات المستلم:\n"
                f"الاسم: <code>{transfer_data.get('recipient_name', '-')}</code>\n" \
                f"الجوال: <code>{transfer_data.get('recipient_number', '-')}</code>\n" \
                f"💱 المبلغ بالعمله المختاره: <code>{transfer_data.get('local_amount', 0):.2f}</code> {transfer_data.get('local_currency')}\n"
            )
            if agency := transfer_data.get('transfer_agency'):
                admin_message += f"جهة التحويل: {agency}\n"
        else:
            admin_message += (
                "🏦 معلومات الحساب:\n"
                f"المحفظة: <code>{transfer_data.get('wallet_name', '-')}</code>\n" \
                f"رقم الحساب: <code>{transfer_data.get('account_number', '-')}</code>\n" \
                f"💱 المبلغ المحلي: <code>{transfer_data.get('local_amount', 0):.2f}</code> {transfer_data.get('local_currency')}\n"
            )

        admin_message += (
            f"\n🌐 الشبكة: {transfer_data.get('usdt_network', '-')}\n"
            f"⏰ وقت التحقق: {transfer_data.get('verified_at', '-')}"
        )

        # تجهيز أزرار المعالجة
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ معالجة الطلب", callback_data=f"admin_approve_{transfer_id}")],
            [InlineKeyboardButton("❌ رفض الطلب", callback_data=f"admin_reject_{transfer_id}")]
        ])

        # إرسال الإشعار للمشرفين
        await context.bot.send_message(
            chat_id=ADMIN_GROUP_ID,  # استخدام المعرف كما هو بدون تحويله
            text=admin_message,
            reply_markup=keyboard,
            parse_mode='HTML'
        )

        logger.info(f"تم إرسال إشعار للمشرفين عن التحويل: {transfer_id}")

    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار للمشرفين: {e}")
        raise

def format_transfer_details(transfer: dict) -> str:
    """تنسيق تفاصيل التحويل في رسالة"""
    details = (
        "📝 <b>تفاصيل التحويل:</b>\n"
        f"🔹 <b>نوع التحويل:</b> {'تحويل عبر الاسم' if transfer.get('transfer_type') == 'name_transfer' else 'إيداع لرقم حساب'}\n"
    )

    # إضافة معلومات المحفظة ورقم الحساب فقط لتحويلات الحساب
    if transfer.get('transfer_type') != 'name_transfer':
        details += (
            f"🏦 <b>المحفظة:</b> <code>{transfer.get('wallet_name', '-')}</code>\n"
            f"📊 <b>رقم الحساب:</b> <code>{transfer.get('account_number', '-')}</code>\n"
        )

    details += (
        f"💱 <b>العملة المحلية:</b> {transfer.get('local_currency', '-')}\n"
        f"🌐 <b>الشبكة:</b> {transfer.get('usdt_network', '-')}\n"
        f"💎 <b>العملة الرقمية:</b> USDT\n"
        f"💰 <b>المبلغ المحول:</b> <code>{transfer.get('amount', 0)}</code> USDT\n"
        f"💸 <b>المبلغ بالعملة المحلية:</b> <code>{transfer.get('local_amount', 0):.2f}</code> {transfer.get('local_currency', '')}\n"
    )

    # إضافة معلومات المستلم للتحويل عبر الاسم
    if transfer.get('transfer_type') == 'name_transfer':
        details += (
            f"\n👤 <b>معلومات المستلم:</b>\n"
            f"<b>الاسم:</b> <code>{transfer.get('recipient_name', '-')}</code>\n"
            f"📱 <b>رقم الهاتف:</b> <code>{transfer.get('recipient_number', '-')}</code>\n"
        )
        if agency := transfer.get('transfer_agency'):
            details += f"📍 <b>جهة التحويل:</b> {agency}\n"

    return details

def format_yemen_time():
   # جلب الوقت الحالي بتوقيت اليمن
   yemen_tz = timezone('Asia/Aden')
   now = datetime.now(yemen_tz)
   
   # تنسيق بنظام 12 ساعة مع AM/PM
   time_str = now.strftime("%I:%M:%S %p")
   
   # تحويل AM/PM إلى صباحاً/مساءً 
   if "AM" in time_str:
       time_str = time_str.replace("AM", "صباحاً")
   else:
       time_str = time_str.replace("PM", "مساءً")
       
   return time_str

print(f"الوقت الآن في اليمن: {format_yemen_time()}")
async def send_yemen_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = format_yemen_time()
    await update.message.reply_text(f"🕐 الوقت الآن في اليمن: {time_str}")

async def admin_response_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
   """معالجة رد المشرف على طلبات التحويل"""
   try:
       query = update.callback_query
       if not query:
           return ConversationHandler.END
           
       try:
           await query.answer()
       except telegram.error.TimedOut:
           pass

       # استخراج معرف التحويل 
       transfer_id = query.data.split('_')[-1]
       
       if not transfer_id:
           try:
               await query.message.reply_text("❌ خطأ: لم يتم العثور على معرف التحويل")
           except telegram.error.BadRequest:
               pass
           return ConversationHandler.END

       logger.info(f"معالجة طلب للتحويل: {transfer_id}")
       
       # التحقق من التحويل
       transfer = db.get_transfer(transfer_id)
       if not transfer:
           logger.error(f"لم يتم العثور على التحويل: {transfer_id}")
           try:
               await query.message.reply_text("❌ خطأ: لم يتم العثور على بيانات التحويل") 
           except telegram.error.BadRequest:
               pass
           return ConversationHandler.END

       # التحقق من الحالة
       if transfer.get('status') in ['completed', 'rejected']:
           status_text = '✅ تم الإكمال' if transfer.get('status') == 'completed' else '❌ تم الرفض'
           try:
               await query.message.reply_text(
                   f"⚠️ تم معالجة هذا الطلب مسبقاً\n"
                   f"الحالة: {status_text}"
               )
           except telegram.error.BadRequest:
               pass
           return ConversationHandler.END

       # حفظ معلومات المشرف
       context.user_data.update({
           'active_transfer_id': transfer_id,
           'admin_info': {
               'admin_id': query.from_user.id,
               'admin_username': query.from_user.username or query.from_user.first_name or "مشرف",
               'message_id': query.message.message_id,
               'original_message': query.message.text
           }
       })

       # معالجة العمليات
       if 'admin_approve' in query.data:
           keyboard = [
               [InlineKeyboardButton("📤 إرسال معلومات التحويل", callback_data=f"send_transfer_info_{transfer_id}")],
               [InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{transfer_id}")]
           ]
           reply_markup = InlineKeyboardMarkup(keyboard)
           
           # تنسيق الوقت بتوقيت اليمن 12 ساعة
           yemen_tz = timezone('Asia/Aden')
           now = datetime.now(yemen_tz)
           time_str = now.strftime("%I:%M:%S %p")
           time_str = time_str.replace("AM", "صباحاً").replace("PM", "مساءً")
           
           new_message_text = (
               f"{query.message.text}\n\n"
               "✅ الرجاء اختيار طريقة إرسال معلومات التحويل:\n"
               "• صورة الإيصال 📸\n"
               "• تفاصيل التحويل نصياً ✍️\n"
               "• ملف PDF 📄\n\n"
               f"🕐 وقت المعالجة: {time_str}"
           )
           
           try:
               await query.message.edit_text(new_message_text, reply_markup=reply_markup)
           except telegram.error.BadRequest as e:
               if "Message is not modified" not in str(e):
                   try:
                       await query.message.reply_text(new_message_text, reply_markup=reply_markup)
                   except telegram.error.BadRequest:
                       pass
           
           return States.SEND_TRANSFER_INFO

       elif 'admin_reject' in query.data:
           keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_back_{transfer_id}")]]
           reply_markup = InlineKeyboardMarkup(keyboard)
           
           try:
               await query.message.edit_text(
                   f"{query.message.text}\n\n❌ الرجاء كتابة سبب الرفض:",
                   reply_markup=reply_markup
               )
           except telegram.error.BadRequest:
               try:
                   await query.message.reply_text(
                       "❌ الرجاء كتابة سبب الرفض:",
                       reply_markup=reply_markup  
                   )
               except telegram.error.BadRequest:
                   pass
                   
           return States.ENTER_REJECTION_REASON

       elif 'admin_back' in query.data:
           keyboard = [
               [InlineKeyboardButton("✅ معالجة الطلب", callback_data=f"admin_approve_{transfer_id}")],
               [InlineKeyboardButton("❌ رفض الطلب", callback_data=f"admin_reject_{transfer_id}")]
           ]
           reply_markup = InlineKeyboardMarkup(keyboard)
           
           original_message = context.user_data.get('admin_info', {}).get('original_message')
           try:
               if original_message:
                   await query.message.edit_text(text=original_message, reply_markup=reply_markup)
               else:
                   await query.message.edit_reply_markup(reply_markup=reply_markup)
           except telegram.error.BadRequest:
               try:
                   await query.message.reply_text(
                       text=original_message or "الرجاء اختيار الإجراء:", 
                       reply_markup=reply_markup
                   )
               except telegram.error.BadRequest:
                   pass

           return States.ADMIN_INITIAL

       return States.ADMIN_INITIAL

   except Exception as e:
       logger.error(f"خطأ في معالجة رد المشرف: {e}", exc_info=True)
       try:
           await query.message.reply_text("❌ حدث خطأ. الرجاء المحاولة مرة أخرى.")
       except telegram.error.BadRequest:
           pass
       return ConversationHandler.END

def extract_transfer_id(query):
    """استخراج معرف التحويل من الرسالة أو callback_data"""
    transfer_id = None
    
    # البحث في نص الرسالة
    if query.message and query.message.text:
        match = re.search(r'معرف التحويل:[\s]*([a-zA-Z0-9-]+)', query.message.text)
        if match:
            transfer_id = match.group(1)
    
    # البحث في callback_data إذا لم يتم العثور على المعرف في النص
    if not transfer_id and query.data:
        match = re.search(r'(?:admin_approve_|admin_reject_|send_transfer_info_|admin_back_)(\w+)', query.data)
        if match:
            transfer_id = match.group(1)
    
    return transfer_id    

async def handle_rejection_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة سبب رفض التحويل"""
    try:
        reason = update.message.text.strip()
        
        # الحصول على معرف التحويل من context
        transfer_id = context.user_data.get('active_transfer_id')
        logger.info(f"معالجة سبب الرفض للتحويل {transfer_id}: {reason}")

        if not transfer_id:
            await update.message.reply_text("❌ خطأ: لم يتم العثور على معرف التحويل")
            return ConversationHandler.END

        # التحقق من حالة التحويل
        transfer = db.get_transfer(transfer_id)
        if not transfer or transfer.get('status') in ['completed', 'rejected']:
            await update.message.reply_text(
                "⚠️ لا يمكن تحديث هذا الطلب لأنه تم إكماله أو رفضه مسبقاً."
            )
            return ConversationHandler.END

        # تحديث حالة التحويل
        success = db.update_transfer_status(
            transfer_id=transfer_id,
            status="rejected",
            rejection_reason=reason
        )
        logger.info(f"نتيجة تحديث حالة التحويل: {success}")

        if success:
            # الحصول على بيانات التحويل المحدثة
            transfer = db.get_transfer(transfer_id)
            if not transfer:
                await update.message.reply_text("❌ خطأ في قراءة بيانات التحويل")
                return ConversationHandler.END

            # إعداد رسالة الرفض
            rejection_message = (
                "❌ تم رفض طلب التحويل\n\n"
                f"{format_transfer_details(transfer)}\n"
                "❌ سبب الرفض:\n"
                f"{reason}\n"
            )            
            # إضافة زر بدء عملية جديدة
            keyboard = [[InlineKeyboardButton("🔄 بدء عملية جديدة", callback_data="start_new")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # إرسال التأكيد للمستخدم
            if user_id := transfer.get('user_id'):
                try:
                    # إنشاء زر بدء عملية جديدة
                    keyboard = [[InlineKeyboardButton("🔄 بدء عملية جديدة", callback_data="start_new")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    # الحصول على معلومات الملف والنوع من context
                    message_type = context.user_data.get('message_type', 'text')
                    file_id = context.user_data.get('file_id')

                    if message_type == 'photo' and file_id:
                        await context.bot.send_photo(
                            chat_id=user_id,
                            photo=file_id,
                            caption=rejection_message,
                            parse_mode='HTML',
                            reply_markup=reply_markup
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=rejection_message,
                            parse_mode='HTML',
                            reply_markup=reply_markup
                        )
                    logger.info(f"تم إرسال رسالة الرفض للمستخدم {user_id}")
                except Exception as e:
                    logger.error(f"خطأ في إرسال رسالة الرفض للمستخدم {user_id}: {e}")

            # تحديث رسالة المشرف
            admin_info = context.user_data.get('admin_info', {})
            admin_username = admin_info.get('admin_username', 'مشرف')
            admin_display = f"@{admin_username}" if '@' not in admin_username else admin_username
            
            admin_confirmation = (
                f"✅ تم إرسال سبب الرفض للمستخدم\n\n"
                "📝 ملخص الطلب:\n"
                f"🔹 معرف التحويل: {transfer_id}\n"
                f"🔹 نوع التحويل: {transfer.get('transfer_type', 'تحويل عبر الاسم') if transfer.get('transfer_type') == 'name_transfer' else 'إيداع لرقم حساب'}\n"
                f"🔹 المحفظة: {transfer.get('wallet_name', '-')}\n"
                f"🔹 رقم الحساب: {transfer.get('account_number', '-')}\n\n"
                f"👤 تم الرفض بواسطة: {admin_display}\n\n"
                "❌ سبب الرفض:\n"
                f"{reason}\n"
            )

            # تحديث رسالة الطلب في قروب المشرفين
            admin_info = context.user_data.get('admin_info', {})
            if admin_info and 'message_id' in admin_info:
                try:
                    await edit_message_with_retry(
                        context=context,
                        chat_id=update.effective_chat.id,
                        message_id=admin_info['message_id'],
                        text=admin_confirmation,
                        parse_mode='HTML'
                    )
                    logger.info(f"تم تحديث رسالة المشرف في المجموعة")
                except telegram.error.BadRequest as e:
                    if "There is no text in the message to edit" in str(e):
                        logger.info("El mensaje no tiene texto para editar, enviando un nuevo mensaje")
                        try:
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=admin_confirmation,
                                parse_mode='HTML'
                            )
                        except Exception as send_err:
                            logger.error(f"Error al enviar nuevo mensaje: {send_err}")
                    else:
                        logger.error(f"خطأ في تحديث رسالة المشرف: {e}")
                        # إذا فشل التعديل، نحذف الرسالة ونرسل رسالة جديدة
                        try:
                            await context.bot.delete_message(
                                chat_id=ADMIN_GROUP_ID,
                                message_id=admin_info['message_id']
                            )
                        except Exception:
                            pass
                        
                        await context.bot.send_message(
                            chat_id=ADMIN_GROUP_ID,
                            text=admin_confirmation,
                            parse_mode='HTML'
                        )

            return ConversationHandler.END
        else:
            await update.message.reply_text("❌ حدث خطأ في حفظ سبب الرفض. الرجاء المحاولة مرة أخرى.")
            return States.ENTER_REJECTION_REASON

    except Exception as e:
        logger.error(f"خطأ في معالجة سبب الرفض: {e}")
        await update.message.reply_text("❌ حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return States.ENTER_REJECTION_REASON


async def start_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة طلب بدء عملية جديدة"""
    query = update.callback_query
    await query.answer()
    
    # تنظيف البيانات السابقة
    context.user_data.clear()
    
    # عرض خيارات التحويل الرئيسية
    keyboard = [
        [
            InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
            InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.edit_text(
        "👋 مرحباً بكم في خدمة السحب الالي من MetaBit 🔷\n\n"
        "💸 الرجاء اختيار طريقة التحويل:",
        reply_markup=reply_markup
    )
    return States.SELECT_TRANSFER_TYPE


def create_confirmation_message(transfer: dict, transfer_id: str, message_text: str = None) -> str:
    """إنشاء رسالة تأكيد موحدة"""
    confirmation_message = (
        "✅ <b>تم تنفيذ طلبك بنجاح!</b>\n\n"
        "<b>📝 تفاصيل التحويل:</b>\n"
        f"💠 <b>نوع التحويل:</b> {'تحويل عبر الاسم' if transfer.get('transfer_type') == 'name_transfer' else 'إيداع لرقم حساب'}\n"
        f"🏦 <b>المحفظة:</b> <code>{transfer.get('wallet_name', '-')}</code>\n"
        f"📊 <b>رقم الحساب:</b> <code>{transfer.get('account_number', '-')}</code>\n"
        f"💱 <b>العملة المحلية:</b> {transfer.get('local_currency', '-')}\n"
        f"🌐 <b>الشبكة:</b> {transfer.get('usdt_network', '-')}\n"
        f"💎 <b>العملة الرقمية:</b> USDT\n"
        f"💵 <b>المبلغ المحول:</b> <code>{transfer.get('amount', 0)}</code> USDT\n"
        f"💸 <b>المبلغ بالعملة المحلية:</b> <code>{transfer.get('local_amount', 0):.2f}</code> {transfer.get('local_currency', '')}\n"
        f"💠 <b>معرف التحويل:</b> <code>{transfer_id}</code>\n"
        f"🕐 <b>وقت الإكمال:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    
    if message_text:
        confirmation_message += f"\n\n<b>📋 معلومات إضافية:</b>\n{message_text}"
    
    return confirmation_message

def format_user_message(transfer_data: dict) -> str:
    """تنسيق رسالة المستخدم"""
    settings = db.get_settings()
    amount = float(transfer_data.get('amount', 0))
    fixed_fee_threshold = settings.get('fixed_fee_threshold', 20)
    fixed_fee_amount = settings.get('fixed_fee_amount', 1)
    percentage_fee = settings.get('percentage_fee', 0.05)
    
    commission = fixed_fee_amount if amount <= fixed_fee_threshold else amount * percentage_fee
    commission_type = ' (ثابتة)' if amount <= fixed_fee_threshold else f' ({percentage_fee * 100}%)'
    final_amount = amount - commission
    
    message = "<b>📝 تفاصيل التحويل:</b>\n"
    
    if transfer_data.get('transfer_type') == 'name_transfer':
        message += (
            "<b>👤 معلومات المستلم:</b>\n"
            f"<b>الاسم:</b> <code>{transfer_data.get('recipient_name', '-')}</code>\n"
            f"<b>📱 رقم الهاتف:</b> <code>{transfer_data.get('recipient_number', '-')}</code>\n"
            f"<b>💱 العملة المحلية:</b> {transfer_data.get('local_currency', '-')}\n"
            f"<b>🌐 الشبكة:</b> {transfer_data.get('usdt_network', '-')}\n"
            f"<b>💎 العملة الرقمية:</b> USDT\n\n"
            "<b>💰 تفاصيل المبلغ:</b>\n"
            f"• <b>المبلغ الكلي:</b> <code>{amount:.2f}</code> USDT\n"
            f"• <b>العمولة:</b> <code>{commission:.2f}</code> USDT{commission_type}\n"
            f"• <b>صافي المبلغ:</b> <code>{final_amount:.2f}</code> USDT\n"
            f"• <b>بالعملة المحلية:</b> <code>{transfer_data.get('local_amount', 0)}</code> {transfer_data.get('local_currency', '')}\n"
        )
        if agency := transfer_data.get('transfer_agency'):
            message += f"<b>📍 جهة التحويل:</b> {agency}\n"
    else:
        message += (
            f"<b>🏦 المحفظة:</b> <code>{transfer_data.get('wallet_name', '-')}</code>\n"
            f"<b>📊 رقم الحساب:</b> <code>{transfer_data.get('account_number', '-')}</code>\n"
            f"<b>💱 العملة المحلية:</b> {transfer_data.get('local_currency', '-')}\n"
            f"<b>🌐 الشبكة:</b> {transfer_data.get('usdt_network', '-')}\n"
            f"<b>💎 العملة الرقمية:</b> USDT\n"
            f"• <b>المبلغ الكلي:</b> <code>{amount:.2f}</code> USDT\n"
            f"• <b>العمولة:</b> <code>{commission:.2f}</code> USDT{commission_type}\n"
            f"• <b>صافي المبلغ:</b> <code>{final_amount:.2f}</code> USDT\n"
            f"• <b>بالعملة المحلية:</b> <code>{transfer_data.get('local_amount', 0)}</code> {transfer_data.get('local_currency', '')}\n"
        )

    message += f"<b>🕐 وقت الإكمال:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    return message

def format_admin_message(transfer: dict, admin_username: str) -> str:
    amount = float(transfer.get('amount', 0))
    settings = db.get_settings()
    fixed_fee_threshold = settings.get('fixed_fee_threshold', 20)
    fixed_fee_amount = settings.get('fixed_fee_amount', 1)
    percentage_fee = settings.get('percentage_fee', 0.05)
    
    commission = fixed_fee_amount if amount <= fixed_fee_threshold else amount * percentage_fee
    final_amount = amount - commission
    local_currency = transfer.get('local_currency', 'USD')
    exchange_rate = db.get_exchange_rate(local_currency)
    local_amount = final_amount * exchange_rate
    
    message = (
        "✅ <b>تم تنفيذ الطلب بنجاح!</b>\n\n"
        "<b>📝 تفاصيل التحويل:</b>\n"
    )

    user = db.get_user(transfer.get('user_id'))
    registration_code = user.get('registration_code', '-') if user else '-'
    
    commission_type = ' (ثابتة)' if amount <= fixed_fee_threshold else f' ({percentage_fee * 100}%)'
    
    if transfer.get('transfer_type') == 'name_transfer':
        message += (
            f"<b>👤 معلومات العميل:</b>\n"
            f"<b>اسم العميل بالنظام:</b> <code>{registration_code}</code>\n"
            f"<b>معرف تيليجرام:</b> @{transfer.get('username', '-')}\n\n"
            f"<b>👤 معلومات المستلم:</b>\n"
            f"<b>الاسم:</b> <code>{transfer.get('recipient_name', '-')}</code>\n"
            f"<b>📱 رقم الهاتف:</b> <code>{transfer.get('recipient_number', '-')}</code>\n"
            f"<b>💱 العملة المحلية:</b> {local_currency}\n"
            f"<b>🌐 الشبكة:</b> {transfer.get('usdt_network', '-')}\n\n"
            f"<b>💰 تفاصيل المبلغ:</b>\n"
            f"• <b>المبلغ الكلي:</b> <code>{amount:.2f}</code> USDT\n"
            f"• <b>العمولة:</b> <code>{commission:.2f}</code> USDT{commission_type}\n"
            f"• <b>صافي المبلغ:</b> <code>{final_amount:.2f}</code> USDT\n"
            f"• <b>بالعملة المحلية:</b> <code>{local_amount:.2f}</code> {local_currency}\n"
        )
        
        if agency := transfer.get('transfer_agency'):
            message += f"<b>📍 جهة التحويل:</b> {agency}\n"
    else:
        message += (
            f"<b>👤 معلومات العميل:</b>\n"
            f"<b>اسم العميل بالنظام:</b> <code>{registration_code}</code>\n"
            f"<b>معرف تيليجرام:</b> @{transfer.get('username', '-')}\n\n"
            f"<b>🏦 معلومات الحساب:</b>\n"
            f"<b>المحفظة:</b> <code>{transfer.get('wallet_name', '-')}</code>\n"
            f"<b>رقم المحفظة:</b> <code>{transfer.get('account_number', '-')}</code>\n"
            f"<b>💱 العملة المحلية:</b> {local_currency}\n"
            f"<b>🌐 الشبكة:</b> {transfer.get('usdt_network', '-')}\n\n"
            f"<b>💰 تفاصيل المبلغ:</b>\n"
            f"• <b>المبلغ الكلي:</b> <code>{amount:.2f}</code> USDT\n"
            f"• <b>العمولة:</b> <code>{commission:.2f}</code> USDT{commission_type}\n"
            f"• <b>صافي المبلغ:</b> <code>{final_amount:.2f}</code> USDT\n"
            f"• <b>بالعملة المحلية:</b> <code>{local_amount:.2f}</code> {local_currency}\n"
        )
    
    admin_display = f"@{admin_username}" if '@' not in admin_username else admin_username
    message += f"\n<b>👤 تمت المعالجة بواسطة:</b> {admin_display}\n"
    message += f"<b>🕐 وقت الإكمال:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    return message

async def handle_transfer_info_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إرسال معلومات التحويل (صورة أو نص) من المشرف وإرسال رسالة واحدة للمستخدم."""
    try:
        transfer_id = context.user_data.get('active_transfer_id')
        if not transfer_id:
            await update.message.reply_text("❌ خطأ: لم يتم العثور على معرف التحويل")
            return ConversationHandler.END

        transfer = db.get_transfer(transfer_id)
        if not transfer:
            await update.message.reply_text("❌ خطأ: لم يتم العثور على بيانات التحويل")
            return ConversationHandler.END

        if transfer.get('status') in ['completed', 'rejected']:
            await update.message.reply_text("⚠️ لا يمكن تحديث هذا الطلب لأنه تم إكماله أو رفضه مسبقاً.")
            return ConversationHandler.END

        # تحديد نوع الرسالة وحفظها
        file_id = None
        message_type = None
        message_text = update.message.caption if update.message.photo else update.message.text

        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            message_type = 'photo'
        elif update.message.text:
            message_type = 'text'
        elif update.message.document and update.message.document.mime_type == 'application/pdf':
            file_id = update.message.document.file_id
            message_type = 'document'
        
        # حفظ البيانات في context.user_data للمراجعة
        context.user_data['transfer_info'] = {
            'transfer_id': transfer_id,
            'transfer': transfer,
            'file_id': file_id,
            'message_type': message_type,
            'message_text': message_text
        }
        
        # إعداد رسالة المعاينة للمشرف
        preview_message = "🔍 مراجعة المعلومات قبل الإرسال للعميل:\n\n"
        preview_message += format_user_message(transfer)
        
        if message_text:
            preview_message += f"\n📋 معلومات إضافية:\n{message_text}"
            
        # إنشاء أزرار التأكيد أو التعديل
        keyboard = [
            [InlineKeyboardButton("✅ تأكيد وإرسال للعميل", callback_data=f"confirm_send_{transfer_id}")],
            [InlineKeyboardButton("🔄 تعديل المعلومات", callback_data=f"edit_info_{transfer_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال رسالة المعاينة للمشرف
        if message_type == 'photo' and file_id:
            sent_message = await update.message.reply_photo(
                photo=file_id,
                caption=preview_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        elif message_type == 'document' and file_id:
            sent_message = await update.message.reply_document(
                document=file_id,
                caption=preview_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        else:
            sent_message = await update.message.reply_text(
                text=preview_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        
        # حفظ معرف رسالة المعاينة
        context.user_data['preview_message_id'] = sent_message.message_id
        
        return States.REVIEW_TRANSFER_INFO
        
    except Exception as e:
        logger.error(f"خطأ في معالجة معلومات التحويل: {e}")
        await update.message.reply_text("❌ حدث خطأ في معالجة معلومات التحويل")
        return ConversationHandler.END

async def handle_receipt_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة رفع صورة الإيصال"""
    try:
        # البحث عن معرف التحويل
        transfer_id = context.user_data.get('active_transfer_id')
        if not transfer_id:
            await update.message.reply_text("❌ خطأ: لم يتم العثور على معرف التحويل")
            return ConversationHandler.END

        transfer = db.get_transfer(transfer_id)
        if not transfer:
            await update.message.reply_text("❌ خطأ في قراءة بيانات التحويل")
            return ConversationHandler.END

        if transfer.get('status') in ['completed', 'rejected']:
            await update.message.reply_text(
                "⚠️ لا يمكن تحديث هذا الطلب لأنه تم إكماله أو رفضه مسبقاً."
            )
            return ConversationHandler.END

        if not update.message.photo:
            await update.message.reply_text("⚠️ الرجاء إرسال صورة الإيصال.")
            return States.UPLOAD_RECEIPT

        photo = update.message.photo[-1]
        file_id = photo.file_id

        success = db.update_transfer_status(
            transfer_id=transfer_id,
            status="completed",
            receipt_url=file_id
        )

        if not success:
            await update.message.reply_text("❌ حدث خطأ في حفظ الإيصال. الرجاء المحاولة مرة أخرى.")
            return States.UPLOAD_RECEIPT

        # تعديل رسالة التحقق السابقة
        user_id = transfer.get('user_id')
        verification_msg_id = context.user_data.get('verification_message_id')

        confirmation_message = (
            "✅ تم إكمال التحويل بنجاح!\n\n"
            f"{format_transfer_details(transfer)}\n"
        )

        if verification_msg_id:
            try:
                await edit_message_with_retry(
                    context=context,
                    chat_id=user_id,
                    message_id=verification_msg_id,
                    text=confirmation_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"خطأ في تعديل رسالة التحقق: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=confirmation_message,
                    parse_mode='HTML'
                )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=confirmation_message,
                parse_mode='HTML'
            )

        # إرسال الإيصال كصورة جديدة (اختياري)
        await context.bot.send_photo(
            chat_id=user_id,
            photo=file_id,
            caption="📸 إيصال التحويل",
            parse_mode='HTML'
        )

        # زر عملية جديدة
        keyboard = [[InlineKeyboardButton("🔄 بدء عملية جديدة", callback_data="start_new")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=user_id,
            text="يمكنك بدء عملية جديدة بالضغط على الزر أدناه:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        # تحديث رسالة المشرف
        admin_confirmation = (
            "✅ تم إرسال الإيصال والمعلومات للمستخدم بنجاح\n\n"
            f"{format_transfer_details(transfer)}\n"
            f"🔹 معرف التحويل: {transfer_id}\n"
            f"🔹 وقت الإكمال: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )

        admin_info = context.user_data.get('admin_info', {})
        if admin_info and 'message_id' in admin_info:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=admin_info['message_id'],
                    text=admin_confirmation,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"خطأ في تحديث رسالة المشرف: {e}")

        context.user_data.clear()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة رفع الإيصال: {e}")
        await update.message.reply_text("❌ حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END

async def handle_transfer_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال تفاصيل التحويل نصياً"""
    try:
        transfer_info = update.message.text.strip()
        transfer_id = context.user_data.get('active_transfer_id')
        if not transfer_id:
            await update.message.reply_text("❌ خطأ: لم يتم العثور على معرف التحويل")
            return ConversationHandler.END

        transfer = db.get_transfer(transfer_id)
        if not transfer:
            await update.message.reply_text("❌ خطأ في قراءة بيانات التحويل")
            return ConversationHandler.END

        if transfer.get('status') in ['completed', 'rejected']:
            await update.message.reply_text("⚠️ لا يمكن تحديث هذا الطلب لأنه تم إكماله أو رفضه مسبقاً.")
            return ConversationHandler.END

        if not transfer_info:
            await update.message.reply_text("⚠️ الرجاء إدخال تفاصيل التحويل.")
            return States.ENTER_TRANSFER_INFO

        success = db.update_transfer_status(
            transfer_id=transfer_id,
            status="completed",
            transfer_info=transfer_info
        )

        if not success:
            await update.message.reply_text("❌ حدث خطأ في حفظ التفاصيل. الرجاء المحاولة مرة أخرى.")
            return States.ENTER_TRANSFER_INFO

        # تعديل رسالة التحقق السابقة
        user_id = transfer.get('user_id')
        verification_msg_id = context.user_data.get('verification_message_id')

        confirmation_message = (
            "✅ تم إكمال التحويل بنجاح!\n\n"
            f"{format_transfer_details(transfer)}\n"
            f"📝 معلومات التحويل:\n"
            f"{transfer_info}\n"
        )

        if verification_msg_id:
            try:
                await edit_message_with_retry(
                    context=context,
                    chat_id=user_id,
                    message_id=verification_msg_id,
                    text=confirmation_message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"خطأ في تعديل رسالة التحقق: {e}")
                await context.bot.send_message(
                    chat_id=user_id,
                    text=confirmation_message,
                    parse_mode='HTML'
                )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=confirmation_message,
                parse_mode='HTML'
            )

        # زر عملية جديدة
        keyboard = [[InlineKeyboardButton("🔄 عملية جديدة", callback_data="start_new")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=user_id,
            text="يمكنك بدء عملية جديدة بالضغط على الزر أدناه:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

        # تحديث رسالة المشرف
        admin_confirmation = (
            "✅ تم إكمال العملية وإرسال التفاصيل للعميل بنجاح\n\n"
            f"{format_transfer_details(transfer)}\n"
            f"🔹 معرف التحويل: {transfer_id}\n"
            f"🔹 وقت الإكمال: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "📋 معلومات التحويل المضافة:\n"
            f"{transfer_info}\n"
        )

        admin_info = context.user_data.get('admin_info', {})
        if admin_info and 'message_id' in admin_info:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=admin_info['message_id'],
                    text=admin_confirmation,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(f"خطأ في تحديث رسالة المشرف: {e}")
                # إذا فشل التعديل، نحذف الرسالة ونرسل رسالة جديدة
                try:
                    await context.bot.delete_message(
                        chat_id=ADMIN_GROUP_ID,
                        message_id=admin_info['message_id']
                    )
                except Exception:
                    pass
                        
                await context.bot.send_message(
                    chat_id=ADMIN_GROUP_ID,
                    text=admin_confirmation,
                    parse_mode='HTML'
                )

        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"خطأ في معالجة تفاصيل التحويل: {e}")
        await update.message.reply_text("❌ حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return States.ENTER_TRANSFER_INFO

async def handle_admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرجوع في قائمة المشرف"""
    try:
        query = update.callback_query
        await query.answer()
        
        admin_message = (
            "👨‍💼 <b>لوحة تحكم المشرف</b>\n\n"
            "اختر إحدى العمليات التالية:"
        )
        
        keyboard = [
            [InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")],
            [InlineKeyboardButton("⚙️ الإعدادات", callback_data="admin_settings")],
            [InlineKeyboardButton("🔄 تحديث الرصيد", callback_data="update_balance")],
            [InlineKeyboardButton("🔙 العودة", callback_data="start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await edit_message_with_retry(
                context=context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"خطأ في تحديث رسالة المشرف: {e}")
            await query.message.reply_text(
                text=admin_message,
                parse_mode='HTML',
                reply_markup=reply_markup
            )
        
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"خطأ في معالجة العودة: {e}")
        return ConversationHandler.END

async def cancel_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء العملية الإدارية"""
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await edit_message_with_retry(
                context=context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="تم إلغاء العملية.",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"خطأ في تحديث رسالة الإلغاء: {e}")
            await query.message.reply_text("تم إلغاء العملية.")
    else:
        await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END

async def confirm_transfer_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تأكيد إرسال معلومات التحويل للعميل بعد المراجعة"""
    query = update.callback_query
    await query.answer()
    
    try:
        # استرجاع البيانات المخزنة
        transfer_info = context.user_data.get('transfer_info', {})
        if not transfer_info:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ خطأ: لم يتم العثور على معلومات التحويل"
            )
            return ConversationHandler.END
            
        transfer_id = transfer_info.get('transfer_id')
        transfer = transfer_info.get('transfer')
        file_id = transfer_info.get('file_id')
        message_type = transfer_info.get('message_type')
        message_text = transfer_info.get('message_text')
        
        if not transfer_id or not transfer:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ خطأ: بيانات التحويل غير مكتملة"
            )
            return ConversationHandler.END
            
        # تحديث حالة التحويل
        success = db.update_transfer_status(
            transfer_id=transfer_id,
            status="completed",
            receipt_url=file_id if file_id else None,
            transfer_info=message_text if message_text else None
        )

        if not success:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ حدث خطأ في حفظ معلومات التحويل."
            )
            return States.SEND_TRANSFER_INFO

        # إعداد رسالة التأكيد للمستخدم
        confirmation_message = "✅ تم تنفيذ الطلب بنجاح!\n\n"
        confirmation_message += format_user_message(transfer)
        
        if message_text:
            confirmation_message += f"\n📋 معلومات إضافية:\n{message_text}"

        # إرسال رسالة للمستخدم
        keyboard = [[InlineKeyboardButton("🔄 بدء عملية جديدة", callback_data="start_new")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if user_id := transfer.get('user_id'):
            try:
                if message_type == 'photo' and file_id:
                    await context.bot.send_photo(
                        chat_id=user_id,
                        photo=file_id,
                        caption=confirmation_message,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                elif message_type == 'document' and file_id:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=file_id,
                        caption=confirmation_message,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=confirmation_message,
                        parse_mode='HTML',
                        reply_markup=reply_markup
                    )
                    
                # إرسال تأكيد للمشرف
                try:
                    await query.message.edit_text(
                        "✅ تم إرسال المعلومات للعميل بنجاح!",
                        reply_markup=None
                    )
                except Exception as e:
                    logger.error(f"خطأ في تعديل رسالة المشرف: {e}")
                    try:
                        await query.message.delete()
                    except Exception:
                        pass
                        
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text="✅ تم إرسال المعلومات للعميل بنجاح!"
                    )
            except Exception as e:
                logger.error(f"خطأ في إرسال رسالة التأكيد للمستخدم: {e}")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="❌ حدث خطأ في إرسال رسالة التأكيد للمستخدم"
                )
                return ConversationHandler.END

        # تحديث رسالة المشرف في المجموعة
        admin_info = context.user_data.get('admin_info', {})
        admin_username = admin_info.get('admin_username', 'مشرف')
        admin_display = f"@{admin_username}" if '@' not in admin_username else admin_username
        
        admin_confirmation = format_admin_message(transfer, admin_display)

        admin_info = context.user_data.get('admin_info', {})
        if admin_info and 'message_id' in admin_info:
            try:
                await edit_message_with_retry(
                    context=context,
                    chat_id=ADMIN_GROUP_ID,  
                    message_id=admin_info['message_id'],
                    text=admin_confirmation,
                    parse_mode='HTML'
                )
            except telegram.error.BadRequest as e:
                if "There is no text in the message to edit" in str(e):
                    logger.info("El mensaje no tiene texto para editar, enviando un nuevo mensaje")
                    try:
                        await context.bot.send_message(
                            chat_id=ADMIN_GROUP_ID,
                            text=admin_confirmation,
                            parse_mode='HTML'
                        )
                    except Exception as send_err:
                        logger.error(f"Error al enviar nuevo mensaje: {send_err}")
                else:
                    logger.error(f"خطأ في تحديث رسالة المشرف: {e}")
                    # إذا فشل التعديل، نحذف الرسالة ونرسل رسالة جديدة
                    try:
                        await context.bot.delete_message(
                            chat_id=ADMIN_GROUP_ID,
                            message_id=admin_info['message_id']
                        )
                    except Exception:
                        pass
                        
                    await context.bot.send_message(
                        chat_id=ADMIN_GROUP_ID,
                        text=admin_confirmation,
                        parse_mode='HTML'
                    )

        context.user_data.clear()
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"خطأ في تأكيد معلومات التحويل: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ حدث خطأ في تأكيد معلومات التحويل"
        )
        return ConversationHandler.END

async def edit_transfer_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة طلب تعديل معلومات التحويل"""
    query = update.callback_query
    await query.answer()
    
    try:
        # استرجاع البيانات المخزنة
        transfer_info = context.user_data.get('transfer_info', {})
        if not transfer_info:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ خطأ: لم يتم العثور على معلومات التحويل"
            )
            return ConversationHandler.END
            
        transfer_id = transfer_info.get('transfer_id')
        
        if not transfer_id:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="❌ خطأ: معرف التحويل غير موجود"
            )
            return ConversationHandler.END
            
        # حذف رسالة المعاينة
        try:
            await query.message.delete()
        except Exception as e:
            logger.error(f"خطأ في حذف رسالة المعاينة: {e}")
            
        # إرسال رسالة للمشرف لإدخال المعلومات مرة أخرى
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="🔄 الرجاء إدخال معلومات التحويل مرة أخرى.\n"
                 "يمكنك إرسال نص أو صورة أو ملف PDF.",
            reply_markup=None
        )
        
        # الحفاظ على معرف التحويل النشط
        context.user_data['active_transfer_id'] = transfer_id
        
        return States.SEND_TRANSFER_INFO
        
    except Exception as e:
        logger.error(f"خطأ في تعديل معلومات التحويل: {e}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ حدث خطأ في تعديل معلومات التحويل"
        )
        return ConversationHandler.END
