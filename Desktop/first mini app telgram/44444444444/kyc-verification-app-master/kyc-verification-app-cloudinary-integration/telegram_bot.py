import os
import time
import logging
import asyncio
import threading
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, CallbackQuery, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# تهيئة التسجيل
logger = logging.getLogger(__name__)

# متغيرات عامة
_bot_instance = None
_bot_running = False
_max_retries = 3  # عدد محاولات إعادة تشغيل البوت
_event_loop = None

def ensure_bot_running():
    """التأكد من أن البوت يعمل"""
    global _bot_instance, _bot_running
    if _bot_instance is None or not _bot_running:
        for i in range(_max_retries):
            try:
                _bot_instance = create_application()
                if _bot_instance:
                    # تشغيل البوت في thread منفصل
                    def run_bot_async():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(run_bot(_bot_instance))
                        finally:
                            loop.close()

                    bot_thread = threading.Thread(target=run_bot_async, daemon=True)
                    bot_thread.start()
                    _bot_running = True
                    logger.info("تم إعادة تشغيل البوت بنجاح")
                    return True
            except Exception as e:
                logger.error(f"محاولة {i+1}/{_max_retries} لتشغيل البوت فشلت: {e}")
                time.sleep(1)  # انتظار قبل المحاولة مرة أخرى
    return _bot_running

async def handle_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الردود على الرسائل"""
    try:
        # التحقق من وجود طلب معلق
        request_id = context.user_data.get('pending_request_id')
        action = context.user_data.get('pending_action')
        
        if not request_id or not action:
            return
        
        # الحصول على الرد
        reply_text = update.message.text.strip()
        
        # تحديث حالة الطلب
        if action == 'approve':
            # إرسال كود التحقق للعميل
            await update.message.reply_text(
                f"جاري إرسال كود التحقق {reply_text} للعميل..."
            )
            # TODO: تحديث حالة الطلب في قاعدة البيانات
            
        elif action == 'reject':
            # إرسال سبب الرفض للعميل
            await update.message.reply_text(
                f"جاري إرسال سبب الرفض للعميل..."
            )
            # TODO: تحديث حالة الطلب في قاعدة البيانات
        
        # تنظيف البيانات المؤقتة
        context.user_data.pop('pending_request_id', None)
        context.user_data.pop('pending_action', None)
        
    except Exception as e:
        logger.error(f"خطأ في معالجة الرد: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ أثناء معالجة الرد. الرجاء المحاولة مرة أخرى."
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الضغط على الأزرار"""
    try:
        query: CallbackQuery = update.callback_query
        await query.answer()  # إغلاق مؤشر الانتظار

        # استخراج الأمر ومعرف الطلب
        action, request_id = query.data.split('_')
        
        if action == 'approve':
            # طلب كود التحقق
            await query.message.reply_text(
                text="الرجاء إدخال كود التحقق للعميل:",
                reply_markup=ForceReply(selective=True)
            )
        elif action == 'reject':
            # طلب سبب الرفض
            await query.message.reply_text(
                text="الرجاء إدخال سبب رفض الطلب:",
                reply_markup=ForceReply(selective=True)
            )
        
        # حفظ معرف الطلب في بيانات المحادثة
        context.user_data['pending_request_id'] = request_id
        context.user_data['pending_action'] = action
        
    except Exception as e:
        logger.error(f"خطأ في معالجة الضغط على الزر: {e}")
        await update.callback_query.message.reply_text(
            "عذراً، حدث خطأ أثناء معالجة الطلب. الرجاء المحاولة مرة أخرى."
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أمر /start"""
    try:
        # حفظ معرف المستخدم في قاعدة البيانات
        chat_id = update.message.chat_id
        
        # إنشاء زر الدخول
        web_app_url = os.environ.get('WEB_APP_URL', 'https://kyc-verification-app-teon.onrender.com')
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                text="توثيق الحساب",
                web_app=WebAppInfo(url=web_app_url)
            )]
        ])

        welcome_text = (
            "👋 *مرحباً بك في خدمة توثيق الحساب\\!*\n\n"
            "للبدء في عملية التوثيق، اتبع الخطوات التالية:\n"
            "1\\. اضغط على زر \"توثيق الحساب\" أدناه\n"
            "2\\. قم بتعبئة البيانات المطلوبة\n"
            "3\\. التقط صورة لهويتك وصورة شخصية\n"
            "4\\. انتظر مراجعة طلبك\n\n"
            "سيتم إبلاغك بحالة طلبك عبر رسالة في هذه المحادثة\\."
        )

        await update.message.reply_text(
            text=welcome_text,
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )
        
        logger.info(f"تم إرسال رسالة الترحيب للمستخدم {chat_id}")
    except Exception as e:
        logger.error(f"خطأ في معالجة أمر start: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ أثناء بدء عملية التوثيق. الرجاء المحاولة مرة أخرى."
        )

def create_application() -> Application:
    """إنشاء تطبيق البوت"""
    try:
        # الحصول على توكن البوت
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not bot_token:
            logger.error("لم يتم تعيين TELEGRAM_BOT_TOKEN")
            return None

        # إنشاء التطبيق
        application = Application.builder().token(bot_token).build()

        # إضافة معالجات الأوامر والأزرار
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, handle_reply))

        logger.info("تم إنشاء تطبيق البوت بنجاح")
        return application

    except Exception as e:
        logger.error(f"خطأ في إنشاء تطبيق البوت: {e}")
        return None

async def run_bot(app):
    """تشغيل البوت"""
    global _bot_running, _event_loop
    try:
        # حفظ حلقة الأحداث الحالية
        _event_loop = asyncio.get_running_loop()
        
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
            if app.updater and app.updater.running:
                await app.updater.stop()
            if app.running:
                await app.stop()
            await app.shutdown()
        except Exception as e:
            logger.error(f"خطأ في إيقاف البوت: {e}")
        finally:
            _event_loop = None

def escape_markdown(text):
    """تنظيف النص للتوافق مع MarkdownV2"""
    if not text:
        return text
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in chars:
        text = text.replace(char, f'\\{char}')
    return text

async def send_admin_notification(request_data: dict, notification_type: str = 'new'):
    """إرسال إشعار إلى مجموعة الأدمن"""
    try:
        # التأكد من أن البوت يعمل
        if not ensure_bot_running():
            logger.error("فشل في تشغيل البوت")
            return

        admin_group_id = os.environ.get('ADMIN_GROUP_ID')
        if not admin_group_id:
            logger.error("لم يتم تعيين ADMIN_GROUP_ID")
            return

        # تحضير نص الرسالة
        if notification_type == 'new':
            text = "🆕 *طلب توثيق جديد*\n"
            text += "━━━━━━━━━━━━━━\n\n"
            text += "👤 *معلومات العميل:*\n"
            text += f"• الاسم: `{escape_markdown(request_data.get('full_name', ''))}`\n"
            text += f"• رقم الهوية: `{escape_markdown(request_data.get('id_number', ''))}`\n"
            text += f"• رقم الهاتف: `{escape_markdown(request_data.get('phone', ''))}`\n"
            text += f"• العنوان: `{escape_markdown(request_data.get('address', ''))}`\n\n"
            text += "📋 *تفاصيل الطلب:*\n"
            text += f"• معرف الطلب: `{escape_markdown(request_data.get('id', ''))}`\n"
            text += f"• تاريخ التقديم: {datetime.now().strftime('%Y/%m/%d %I:%M %p')}\n\n"
            text += "⚡️ *الإجراءات المطلوبة:*\n"
            text += "• مراجعة صورة الهوية\n"
            text += "• مراجعة الصورة الشخصية\n"
            text += "• التحقق من تطابق المعلومات\n"
            text += "• اتخاذ قرار (قبول/رفض)"
        elif notification_type == 'status_update':
            text = "📝 *تحديث حالة الطلب*\n"
            text += "━━━━━━━━━━━━━━\n\n"
            text += "🔍 *معلومات الطلب:*\n"
            text += f"• معرف الطلب: `{escape_markdown(request_data.get('id', ''))}`\n"
            status_map = {
                'pending': '⏳ قيد المراجعة',
                'approved': '✅ تم القبول',
                'rejected': '❌ تم الرفض'
            }
            status = status_map.get(request_data.get('status', ''), request_data.get('status', ''))
            text += f"• الحالة: {status}\n"
            text += f"• تاريخ التحديث: {datetime.now().strftime('%Y/%m/%d %I:%M %p')}\n\n"
            
            if request_data.get('verification_code'):
                text += "🔐 *معلومات التوثيق:*\n"
                text += f"• كود التحقق: `{escape_markdown(request_data.get('verification_code', ''))}`\n"
                text += "• صلاحية الكود: مرة واحدة فقط"
            elif request_data.get('rejection_reason'):
                text += "❌ *سبب الرفض:*\n"
                text += f"• السبب: `{escape_markdown(request_data.get('rejection_reason', ''))}`\n"
                text += "• يمكن للعميل تقديم طلب جديد بعد معالجة السبب"

        # إضافة زر لوحة التحكم
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "🔐 لوحة التحكم",
                url="https://kyc-verification-app-teon.onrender.com/admin/dashboard"
            )]
        ])

        # إرسال الرسالة إلى مجموعة الأدمن
        for _ in range(3):  # محاولة الإرسال 3 مرات
            try:
                await _bot_instance.bot.send_message(
                    chat_id=admin_group_id,
                    text=text,
                    parse_mode='MarkdownV2',
                    reply_markup=keyboard
                )
                logger.info(f"تم إرسال إشعار للأدمن: {notification_type}")
                break
            except Exception as e:
                logger.error(f"محاولة إرسال الإشعار للأدمن فشلت: {e}")
                await asyncio.sleep(1)  # انتظار قبل المحاولة مرة أخرى

    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار للأدمن: {e}")

async def send_status_notification(chat_id: int, request_id: str, message: str):
    """إرسال إشعار بحالة الطلب للمستخدم"""
    try:
        # التأكد من أن البوت يعمل
        if not ensure_bot_running():
            logger.error("فشل في تشغيل البوت")
            return

        if not chat_id:
            logger.error("لم يتم تحديد chat_id")
            return

        # تحضير نص الرسالة
        text = "🔔 *تحديث حالة الطلب*\n"
        text += "━━━━━━━━━━━━━━\n\n"
        text += f"🆔 *معرف الطلب:*\n`{escape_markdown(request_id)}`\n\n"
        
        # تحديد نوع الإشعار ورموزه
        if "كود التحقق" in message:
            text += "✅ *تم قبول طلبك\\!*\n"
            text += "━━━━━━━━━━━━━━\n\n"
            # استخراج كود التحقق
            import re
            code_match = re.search(r'كود التحقق: (\d+)', message)
            if code_match:
                code = code_match.group(1)
                text += f"🔐 *كود التحقق الخاص بك:*\n`{escape_markdown(code)}`\n\n"
                text += "⚠️ *تنبيه هام:*\n"
                text += "• يرجى الاحتفاظ بهذا الكود في مكان آمن\n"
                text += "• لا تشارك هذا الكود مع أي شخص\n"
                text += "• الكود صالح للاستخدام مرة واحدة فقط\n\n"
                text += "🎉 *مبروك\\! تم توثيق حسابك بنجاح*"
        elif "سبب الرفض" in message:
            text += "❌ *تم رفض طلبك*\n"
            text += "━━━━━━━━━━━━━━\n\n"
            # استخراج سبب الرفض
            reason_match = re.search(r'سبب الرفض: (.+)', message)
            if reason_match:
                reason = reason_match.group(1)
                text += f"📝 *سبب الرفض:*\n{escape_markdown(reason)}\n\n"
                text += "📌 *ملاحظات:*\n"
                text += "• يمكنك تقديم طلب جديد بعد معالجة سبب الرفض\n"
                text += "• تأكد من تصحيح جميع الملاحظات قبل إعادة التقديم\n"
                text += "• للمساعدة، يرجى التواصل مع فريق الدعم"
        else:
            text += "ℹ️ *تحديث الحالة:*\n"
            text += escape_markdown(message)

        # إرسال الرسالة للمستخدم
        for _ in range(3):  # محاولة الإرسال 3 مرات
            try:
                await _bot_instance.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode='MarkdownV2'
                )
                logger.info(f"تم إرسال إشعار الحالة إلى المستخدم {chat_id}")
                break
            except Exception as e:
                logger.error(f"محاولة إرسال الإشعار فشلت: {e}")
                await asyncio.sleep(1)  # انتظار قبل المحاولة مرة أخرى
        
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار الحالة: {e}")

async def shutdown_bot():
    """إيقاف تشغيل البوت بشكل آمن"""
    global _bot_instance, _bot_running, _event_loop
    if _bot_instance is not None:
        try:
            # التأكد من استخدام نفس حلقة الأحداث
            current_loop = asyncio.get_running_loop()
            if _event_loop and current_loop != _event_loop:
                logger.warning("محاولة إيقاف البوت من حلقة أحداث مختلفة")
                return

            _bot_running = False
            
            # إيقاف المحدث إذا كان قيد التشغيل
            if hasattr(_bot_instance, 'updater') and _bot_instance.updater:
                if _bot_instance.updater.running:
                    await _bot_instance.updater.stop()
            
            # إيقاف البوت إذا كان قيد التشغيل
            if _bot_instance.running:
                await _bot_instance.stop()
            
            # إيقاف التطبيق
            await _bot_instance.shutdown()
            
            # تنظيف المتغيرات
            _bot_instance = None
            _event_loop = None
            
            logger.info("تم إيقاف البوت بنجاح")
            
        except Exception as e:
            logger.error(f"خطأ في إيقاف البوت: {e}")
        finally:
            # تنظيف المتغيرات حتى في حالة الخطأ
            _bot_instance = None
            _bot_running = False
            _event_loop = None