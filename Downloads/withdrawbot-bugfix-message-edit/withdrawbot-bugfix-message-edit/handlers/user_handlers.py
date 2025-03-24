import telegram
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from utils.message_utils import send_message_with_retry, edit_message_with_retry, edit_message_reply_markup_with_retry, round_local_amount

__all__ = [
    'start',
    'verify_registration_code',
    'show_transfer_options',
    'transfer_type_selected',
    'local_currency_selected',
    'wallet_selected',
    'account_number_entered',
    'usdt_network_selected',
    'amount_entered',
    'recipient_name_entered',
    'recipient_number_entered',
    'verify_txid',
    'request_txid',
    'cancel',
    'handle_pending_operation',
    'handle_recipient_confirmation',
    'handle_back',
    'handle_back_to_currencies',
    'handle_recipient_notes',
    'digital_currency_selected',
    'handle_transfer_agency',
    'handle_menu_selection',
    'update_registration_code',
    'handle_code_update'
]
from datetime import datetime, timedelta
import uuid
import logging
from decimal import Decimal
import asyncio
from typing import Dict

from config.config import States, WALLETS, USDT_NETWORKS, ADMIN_GROUP_ID, NETWORK_INFO, COMMISSION_SETTINGS, CURRENCIES, DIGITAL_CURRENCIES,CURRENCY_SYMBOLS,NETWORK_ADDRESSES
from utils.database import Database
from utils.blockchain_scanner import BlockchainScanner
from handlers.admin_handlers import send_admin_notification

logger = logging.getLogger(__name__)

db = Database()

def add_cancel_button(keyboard: list) -> list:
    """إضافة زر الإلغاء إلى لوحة المفاتيح"""
    keyboard.append([InlineKeyboardButton("❌ إلغاء", callback_data="cancel")])
    return keyboard

async def update_registration_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بدء عملية تحديث كود التسجيل"""
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        # التحقق من وجود المستخدم
        user = db.get_user(user_id)
        if not user:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ عذراً، يجب عليك التسجيل أولاً باستخدام /start"
            )
            return ConversationHandler.END
            
        # إنشاء أزرار التأكيد
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم", callback_data="confirm_code_update"),
                InlineKeyboardButton("❌ لا", callback_data="cancel")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال رسالة التأكيد
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ تنبيه: هل أنت متأكد من رغبتك في تحديث كود التسجيل؟\n"
                "سيتم إلغاء الكود الحالي وسيتوجب عليك إدخال كود جديد."
            ),
            reply_markup=reply_markup
        )
        
        # تخزين معرف الرسالة للحذف لاحقاً
        if 'bot_messages' not in context.user_data:
            context.user_data['bot_messages'] = []
        context.user_data['bot_messages'].append(msg.message_id)
        
        return States.CONFIRM_CODE_UPDATE
        
    except Exception as e:
        logger.error(f"خطأ في بدء تحديث الكود: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END

async def handle_code_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تأكيد تحديث الكود"""
    query = update.callback_query
    await query.answer()
    
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if query.data == "confirm_code_update":
            # حذف الرسالة السابقة
            try:
                await query.message.delete()
            except Exception:
                pass
                
            # طلب الكود الجديد
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "👋 مرحباً بك في عملية تحديث الكود!\n\n"
                    "⚠️ تنبيه هام:\n"
                    "• يجب كتابة الكود الجديد بالضبط كما هو مرسل لك\n"
                    "• لا تقم بإدخال أي كلمات أو أرقام أخرى\n\n"
                    "الرجاء إدخال كود التسجيل الجديد الآن:"
                )
            )
            
            # تخزين معرف الرسالة
            context.user_data['bot_messages'] = [msg.message_id]
            
            return States.ENTER_NEW_CODE
            
        else:  # إلغاء العملية
            # حذف رسالة التأكيد
            try:
                await query.message.delete()
            except Exception:
                pass
                
            # إرسال رسالة الإلغاء
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="تم إلغاء عملية تحديث الكود."
            )
            
            context.user_data['bot_messages'] = [msg.message_id]
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"خطأ في معالجة تحديث الكود: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى لاحقاً."
        )
        return ConversationHandler.END


last_start_time: Dict[int, datetime] = {}
START_COOLDOWN = 2  # ثواني بين كل تنفيذ

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بداية المحادثة مع منع الاستخدام في المجموعات"""
    try:
        # التحقق من نوع المحادثة
        if update.effective_chat.type != "private":
            logger.warning(f"محاولة استخدام البوت في مجموعة: {update.effective_chat.id}")
            return ConversationHandler.END
            
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        # التحقق من الوقت المنقضي منذ آخر تنفيذ
        current_time = datetime.now()
        if user_id in last_start_time:
            time_diff = (current_time - last_start_time[user_id]).total_seconds()
            if time_diff < START_COOLDOWN:
                try:
                    if update.message:
                        await update.message.delete()
                except Exception:
                    pass
                return
        
        # تحديث وقت آخر تنفيذ
        last_start_time[user_id] = current_time

        # حذف جميع الرسائل السابقة للبوت
        if 'bot_messages' in context.user_data:
            for msg_id in context.user_data['bot_messages']:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
            context.user_data['bot_messages'] = []
        
        # تنظيف البيانات السابقة
        context.user_data.clear()
        context.user_data['last_start_time'] = current_time

        # حذف رسالة /start
        if update.message:
            try:
                await update.message.delete()
            except Exception:
                pass

        # استخدام asyncio.wait_for لتحديد مهلة زمنية للاتصال بقاعدة البيانات
        try:
            # تحويل استدعاء قاعدة البيانات إلى وظيفة غير متزامنة
            async def get_user_data():
                return db.get_user(user_id)
            
            # تنفيذ الاستدعاء مع مهلة زمنية
            user = await asyncio.wait_for(get_user_data(), timeout=5.0)  # 5 ثوانٍ كحد أقصى
            
            if user and user.get('registration_code'):
                # تحويل التحقق من الكود إلى وظيفة غير متزامنة
                async def verify_code():
                    return db.verify_registration_code(user['registration_code'])
                
                # تنفيذ التحقق مع مهلة زمنية
                is_valid_code = await asyncio.wait_for(verify_code(), timeout=5.0)  # 5 ثوانٍ كحد أقصى
                
                if not is_valid_code:
                    error_msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ عذراً، الكود المستخدم غير نشط. الرجاء التواصل مع الدعم للحصول على كود جديد."
                    )
                    context.user_data['bot_messages'] = [error_msg.message_id]
                    return States.ENTER_REGISTRATION_CODE

                # إنشاء القائمة السفلية
                bottom_menu = ReplyKeyboardMarkup([
                    [KeyboardButton("💰 ايداع"), KeyboardButton("🏧 سحب")]
                ], resize_keyboard=True, one_time_keyboard=False, is_persistent=True)
                
                # إرسال رسالة الترحيب مع القائمة السفلية
                welcome_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text="مرحباً بك في بوت التحويلات MetaBit! 👋",
                    reply_markup=bottom_menu
                )
                context.user_data['bot_messages'] = [welcome_msg.message_id]
                
                return ConversationHandler.END
                
        except asyncio.TimeoutError:
            logger.error("انتهت مهلة الاتصال بقاعدة البيانات")
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ عذراً، يبدو أن هناك مشكلة في الاتصال بالخادم. الرجاء المحاولة مرة أخرى لاحقاً."
            )
            return ConversationHandler.END

        # للمستخدمين غير المسجلين
        reg_message = await context.bot.send_message(
            chat_id=chat_id,
            text="👋 مرحباً بك في بوت التحويلات!\n\n"
                 "⚠️ تنبيه هام:\n"
                 "•  يجب كتابة الكود بالضبط كما هو مرسل لك من قبل المشرف\n"
                 "• لا تقم بإدخال أي كلمات أو أرقام أخرى\n\n"
                 "الرجاء إدخال كود التسجيل الآن:"
        )
        context.user_data['bot_messages'] = [reg_message.message_id]
        return States.ENTER_REGISTRATION_CODE

    except Exception as e:
        logger.error(f"خطأ في دالة start: {e}")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
            )
        except Exception:
            pass
        return ConversationHandler.END

async def handle_pending_operation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المستخدم للعملية المعلقة"""
    query = update.callback_query
    await query.answer()

    if query.data == "start_new":
        # تنظيف البيانات
        context.user_data.clear()

        # بدء عملية جديدة
        return await show_transfer_options(update, context)

    elif query.data == "continue_current":
        # حذف رسالة التحذير
        try:
            await query.message.delete()
        except Exception:
            pass

        # استعادة آخر حالة
        current_state = context.user_data.get('current_state')
        if current_state:
            # إظهار آخر رسالة كان المستخدم عندها
            last_message = context.user_data.get('last_message')
            last_markup = context.user_data.get('last_markup')

            if last_message:
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=last_message,
                    reply_markup=last_markup
                )
            return current_state
        else:
            # إذا لم نتمكن من استعادة الحالة، نبدأ من جديد
            return await show_transfer_options(update, context)
async def verify_registration_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من كود التسجيل"""
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        # الحصول على الكود المدخل
        registration_code = update.message.text.strip()
        
        # حذف رسالة المستخدم
        try:
            await update.message.delete()
        except Exception:
            pass
            
        # التحقق من صحة الكود في جدول registration_codes
        if db.verify_registration_code(registration_code):
            # إضافة أو تحديث المستخدم بالكود الجديد
            if db.add_user(user_id, registration_code):
                # تخزين في Cache
                context.user_data['verified_user'] = True
                return await show_transfer_options(update, context)
            else:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ حدث خطأ أثناء تسجيل الكود. الرجاء المحاولة مرة أخرى."
                )
                context.user_data['bot_messages'] = [msg.message_id]
                return States.ENTER_REGISTRATION_CODE
        else:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ عذراً، الكود غير صالح أو منتهي الصلاحية.\n"
                     "الرجاء كتابة الكود بشكل صحيح اوالتواصل مع الدعم واتساب للحصول على كود جديد 774506423."
            )
            context.user_data['bot_messages'] = [msg.message_id]
            return States.ENTER_REGISTRATION_CODE
            
    except Exception as e:
        logger.error(f"خطأ في التحقق من الكود: {e}")
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        context.user_data['bot_messages'] = [msg.message_id]
        return States.ENTER_REGISTRATION_CODE
async def any_handler_function(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مثال على تتبع الرسائل في أي دالة"""
    try:
        chat_id = update.effective_chat.id
        
        # إرسال رسالة جديدة
        new_message = await context.bot.send_message(
            chat_id=chat_id,
            text="نص الرسالة هنا"
        )
        
        # تتبع معرف الرسالة
        if 'bot_messages' not in context.user_data:
            context.user_data['bot_messages'] = []
        context.user_data['bot_messages'].append(new_message.message_id)
        
        # تحديد الحالة التالية
        return States.NEXT_STATE  # استخدم حالة محددة من States class

    except Exception as e:
        logger.error(f"خطأ: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return ConversationHandler.END
async def show_transfer_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض خيارات التحويل"""
    try:
        keyboard = [
            [
                InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
                InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
            ],
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # تنظيف قائمة الرسائل السابقة
        context.user_data['bot_messages'] = []
        
        message = (
            "👋👋 مرحباً بكم في خدمة السحب الالي من MetaBit 🔷\n\n"
            "💸 الرجاء اختيار طريقة التحويل المبلغ اليك:"
        )

        # إرسال رسالة خيارات التحويل مع الحفاظ على القائمة السفلية
        sent_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            reply_markup=reply_markup
        )

        # تتبع معرف الرسالة
        context.user_data['bot_messages'] = [sent_message.message_id]
        
        logger.info(f"تم عرض خيارات التحويل للمستخدم {update.effective_user.id}")
        return States.SELECT_TRANSFER_TYPE

    except Exception as e:
        logger.error(f"خطأ في دالة show_transfer_options: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى باستخدام /start"
        )
        return ConversationHandler.END

async def handle_error_message(context, chat_id, message):
    """معالجة موحدة لرسائل الخطأ"""
    await context.bot.send_message(
        chat_id=chat_id,
        text=message
    )
    return ConversationHandler.END

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض تعليمات استخدام البوت"""
    try:
        chat_id = update.effective_chat.id
        
        # حذف الرسائل السابقة للبوت
        if 'bot_messages' in context.user_data:
            for msg_id in context.user_data['bot_messages']:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
            context.user_data['bot_messages'] = []

        # نص التعليمات
        help_text = (
           "📖 <b>دليل السحب السريع من MetaBit</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    "1️⃣ <b>بدء عملية السحب</b>\n"
    "    • اضغط على زر 🏧 سحب في القائمة\n"
    "    • اختر طريقة التحويل (عبر الاسم أو رقم الحساب)\n\n"
    
    "2️⃣ <b>اختيار الشبكة</b>\n"
    "    • TRC20 ⭐️ \n"
    "    • BEP20 💫 رسوم تحويل منخفضة (موصى بها)\n\n"
    
    "3️⃣ <b>إدخال المبلغ</b>\n"
    "    • سيتم عرض المبلغ المطلوب تحويله بالضبط\n"
    "    • العمولة تحسب تلقائياً\n\n"
    
    "4️⃣ <b>خطوات التحويل</b>\n"
    "    • انسخ المبلغ المطلوب مع الكسور العشرية بالضبط\n"
    "      مثال: <code>20.0015</code>\n"
    "    • انسخ عنوان المحفظة\n"
    "    • تأكد من اختيار نفس الشبكة عند التحويل\n"
    "    • قم بالتحويل وانتظر تأكيد المعاملة\n\n"
    
    "5️⃣ <b>تأكيد المعاملة</b>\n"
    "    • انسخ رمز المعاملة (TXID)\n"
    "    • أرسله في نفس المحادثة\n"
    "    • ⚠️ لا تقم بإلغاء العملية إلا إذا أردت التحويل من جديد\n"
    "      (في حال الإلغاء لن يتم قبول رمز المعاملة الحالي)\n"
    "    • انتظر تأكيد النظام\n\n"
    
    "⚠️ <b>نصائح هامة</b>\n"
    "━━━━━━━━━━━━━\n"
    "    • تأكد دائماً من اختيار الشبكة الصحيحة\n"
    "    • لا تغلق المحادثة قبل اكتمال العملية\n"
    "    • للمساعدة تواصل معنا على واتساب:\n"
    "      <code>774506423</code> - <code>774994534</code>\n\n"
    
    "🔄 <b>للبدء بعملية سحب جديدة، اضغط على 🏧 سحب</b>"
            )

        # إرسال رسالة التعليمات
        msg = await context.bot.send_message(
        chat_id=chat_id,
        text=help_text,
        parse_mode='HTML'  # تغيير لـ HTML لدعم التنسيق المضاف
)
        
        # تخزين معرف الرسالة
        context.user_data['bot_messages'] = [msg.message_id]
        
        return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"خطأ في عرض التعليمات: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return ConversationHandler.END

async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار القائمة مع منع التكرار"""
    try:
        if not update.message:
            return ConversationHandler.END
            
        text = update.message.text
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        # منع التكرار السريع
        current_time = datetime.now().timestamp()
        last_action = context.user_data.get('last_menu_action', 0)
        if current_time - last_action < 2:  # منع التكرار خلال ثانيتين
            try:
                await update.message.delete()
            except Exception:
                pass
            return
        
        context.user_data['last_menu_action'] = current_time
        
        # حذف رسالة المستخدم
        try:
            await update.message.delete()
        except Exception:
            pass
            
        # حذف الرسائل السابقة للبوت
        if 'bot_messages' in context.user_data:
            for msg_id in context.user_data['bot_messages']:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
            context.user_data['bot_messages'] = []
        
        if text in ["🏧 سحب", "سحب"]:
            # إنشاء أزرار التحويل
            keyboard = [
                [
                    InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
                    InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
                ],
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            inline_markup = InlineKeyboardMarkup(keyboard)
            
            # إنشاء القائمة السفلية
            bottom_menu = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton("💰 ايداع"), KeyboardButton("🏧 سحب")]],
                resize_keyboard=True,
                one_time_keyboard=False,
                selective=False,
                input_field_placeholder="اختر عملية",
                is_persistent=True
            )

            # إرسال رسالة واحدة مع كلا القائمتين
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="💸 الرجاء اختيار طريقة تحويل الأموال إليك:",
                reply_markup=inline_markup
            )

            # إرسال رسالة ثانية للحفاظ على القائمة السفلية
            await context.bot.send_message(
                chat_id=chat_id,
                text="MetaBit",
                reply_markup=bottom_menu
            )

            # تخزين معرف الرسالة للحذف لاحقاً
            context.user_data['bot_messages'] = [msg.message_id]
            return States.SELECT_TRANSFER_TYPE
            
        elif text in ["💰 ايداع", "ايداع"]:
            deposit_button = InlineKeyboardMarkup([
                [InlineKeyboardButton("فتح بوت الإيداع", url="https://t.me/MetaBit_Trx_Bot")]
            ])
            
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="للإيداع، اضغط على الزر أدناه للانتقال إلى بوت الإيداع:",
                reply_markup=deposit_button
            )
            context.user_data['bot_messages'] = [msg.message_id]
            return ConversationHandler.END
            
    except Exception as e:
        logger.error(f"خطأ في معالجة اختيار القائمة: {e}")
        return ConversationHandler.END
    
async def check_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle deposit check request"""
    keyboard = [[InlineKeyboardButton("✍️ إدخال رمز المعاملة يدوياً", callback_data="enter_txid")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📝 الرجاء إدخال رمز المعاملة للتحقق منها.",
        reply_markup=reply_markup
    )
    return States.WAITING_DEPOSIT
async def local_currency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار العملة المحلية"""
    try:
        query = update.callback_query
        await query.answer()
        
        currency_code = query.data.split('_')[1].upper()
        context.user_data['local_currency'] = currency_code
        
        transfer_type = context.user_data.get('transfer_type')
        
        if transfer_type == "transfer_account":
            # طلب إدخال رقم الحساب
            wallet_name = context.user_data.get('wallet_name')
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=f"📝 الرجاء إدخال رقم حسابك {wallet_name}:",
                reply_markup=reply_markup
            )
            return States.ENTER_ACCOUNT_NUMBER
        else:
            # التحويل عبر الاسم - طلب إدخال الاسم الرباعي
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="👤 الرجاء إدخال الاسم الرباعي للمستلم:\n",
                reply_markup=reply_markup
            )
            return States.ENTER_RECIPIENT_NAME
            
    except Exception as e:
        logger.error(f"خطأ في معالجة اختيار العملة المحلية: {e}")
        await query.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return ConversationHandler.END
# إضافة معالج للرجوع إلى اختيار العملات
async def handle_back_to_recipient_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرجوع إلى إدخال اسم المستلم"""
    try:
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await edit_message_with_retry(
            context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text="👤 الرجاء إدخال الاسم الرباعي للمستلم:\n",
            reply_markup=reply_markup
        )
        return States.ENTER_RECIPIENT_NAME
    except Exception as e:
        logger.error(f"خطأ في دالة handle_back_to_recipient_name: {e}")
        await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END

async def handle_back_to_currencies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الرجوع إلى اختيار العملات"""
    try:
        query = update.callback_query
        
        # التحقق من وجود معالجة جارية
        if context.user_data.get('processing_action'):
            await query.answer("⏳ جاري معالجة الطلب السابق...")
            return
        
        # تعيين علامة المعالجة
        context.user_data['processing_action'] = True
        await query.answer()
        
        keyboard = []
        for currency in CURRENCIES:
            button_text = f"{currency['name']} ({currency['symbol']})"
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"currency_{currency['code']}")
            ])
        
        keyboard.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)
    
        await edit_message_with_retry(
            context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text="💱 الرجاء اختيار عملة التحويل :",
            reply_markup=reply_markup
        )
        # إعادة تعيين علامة المعالجة
        context.user_data['processing_action'] = False
        return States.SELECT_LOCAL_CURRENCY
    except Exception as e:
        logger.error(f"خطأ في دالة handle_back_to_currencies: {e}")
        # إعادة تعيين علامة المعالجة في حالة الخطأ
        context.user_data['processing_action'] = False
        await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.ENDndler.END

async def transfer_type_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار نوع التحويل"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        transfer_type = query.data
        
        # تخزين نوع التحويل في context
        context.user_data.update({
            'transfer_id': str(uuid.uuid4()),
            'user_id': user_id,
            'transfer_type': 'name_transfer' if transfer_type == "name_transfer" else 'transfer_account',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

        if transfer_type == "name_transfer":
            keyboard = []
            for currency in CURRENCIES:
                button_text = f"{currency['name']} ({currency['symbol']})"
                keyboard.append([
                    InlineKeyboardButton(button_text, callback_data=f"currency_{currency['code']}")
                ])
            keyboard.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="💱 الرجاء اختيار عملة التحويل:",
                reply_markup=reply_markup
            )
            return States.SELECT_LOCAL_CURRENCY
            
        else:
            keyboard = []
            for wallet in WALLETS:
                button_text = f"💸📱 {wallet['name']}" if wallet.get('is_highlighted') else wallet['name']
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"wallet_{wallet['id']}")])
            keyboard.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="💼 الرجاء اختيار المحفظة:",
                reply_markup=reply_markup
            )
            return States.SELECT_WALLET

    except Exception as e:
        logger.error(f"خطأ في اختيار نوع التحويل: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return ConversationHandler.END


async def currency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار العملة"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    currency = query.data.split('_')[1].upper()
    context.user_data['currency'] = currency

    keyboard = [
        [InlineKeyboardButton("Binance Smart Chain (BEP20) 🌟", callback_data="network_BEP20")],
        [InlineKeyboardButton("Tron Network (TRC20) 🌟", callback_data="network_TRC20")],
        [InlineKeyboardButton("Ethereum Network (ERC20)", callback_data="network_ERC20")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.reply_text(
        "الرجاء اختيار شبكة التحويل:",
        reply_markup=reply_markup
    )
    return States.SELECT_USDT_NETWORK


async def wallet_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار المحفظة"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    wallet_id = int(query.data.split('_')[1])

    wallet = next((w for w in WALLETS if w['id'] == wallet_id), None)
    if not wallet:
        await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END

    context.user_data['wallet_id'] = wallet_id
    context.user_data['wallet_name'] = wallet['name']
    
    # عرض قائمة العملات المحلية
    keyboard = []
    for currency in CURRENCIES:
        button_text = f"{currency['name']} ({currency['symbol']})"
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"currency_{currency['code']}")
        ])
    
    keyboard.extend([
        [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await edit_message_with_retry(
        context,
        chat_id=query.message.chat_id,
        message_id=query.message.message_id,
        text=f"✅ تم اختيار محفظة {wallet['name']}\n\n"
        "💱 الرجاء اختيار عملة التحويل:",
        reply_markup=reply_markup
    )
    return States.SELECT_LOCAL_CURRENCY


async def account_number_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال رقم الحساب"""
    try:
        account_number = update.message.text.strip()
        if not account_number:
            await update.message.reply_text("⚠️ الرجاء إدخال رقم الحساب")
            return States.ENTER_ACCOUNT_NUMBER

        context.user_data['account_number'] = account_number

        # عرض اختيار العملة الرقمية
        keyboard = []
        for currency in DIGITAL_CURRENCIES:
            button_text = f"💎 {currency['name']}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"digital_{currency['id']}")])

        keyboard.extend([
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "💱 الرجاء اختيار العملة الرقمية:",
            reply_markup=reply_markup
        )
        return States.SELECT_DIGITAL_CURRENCY

    except Exception as e:
        logger.error(f"خطأ في معالجة إدخال رقم الحساب: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return ConversationHandler.END

async def digital_currency_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار العملة الرقمية"""
    try:
        query = update.callback_query
        await query.answer()
        
        currency_id = int(query.data.split('_')[1])
        selected_currency = next((c for c in DIGITAL_CURRENCIES if c['id'] == currency_id), None)
        
        if not selected_currency:
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="❌ عذراً، حدث خطأ في اختيار العملة الرقمية.\n"
                "الرجاء المحاولة مرة أخرى."
            )
            return ConversationHandler.END
            
        context.user_data['digital_currency'] = selected_currency['symbol']
        
        # عرض شبكات العملة المختارة
        keyboard = []
        for network in selected_currency['networks']:
            network_info = NETWORK_INFO.get(network, {})
            keyboard.append([InlineKeyboardButton(
                f"{network} ({network_info.get('name', network)})",
                callback_data=f"network_{network}"
            )])
        
        keyboard.extend([
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"📡 الرجاء اختيار شبكة {selected_currency['name']}:\n\n"     
            
        await edit_message_with_retry(
            context,
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=message,
            reply_markup=reply_markup
        )
        return States.SELECT_USDT_NETWORK
        
    except Exception as e:
        logger.error(f"خطأ في معالجة اختيار العملة الرقمية: {e}")
        await query.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return ConversationHandler.END


async def usdt_network_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
   try:
       query = update.callback_query
       await query.answer()
       
       network = query.data.split('_')[1]
       context.user_data['usdt_network'] = network
       
       network_info = NETWORK_INFO.get(network)
       if not network_info:
           await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
           return ConversationHandler.END
           
       user_id = query.from_user.id
       
       keyboard = [
           [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
       ]
       reply_markup = InlineKeyboardMarkup(keyboard)

       combined_message = (
           f"✅ تم اختيار {network_info['name']}\n\n"
           "💰 الرجاء إدخال المبلغ المراد تحويله بالـ USDT:\n"
       )
       
       await edit_message_with_retry(
           context,
           chat_id=query.message.chat_id,
           message_id=query.message.message_id,
           text=combined_message,
           reply_markup=reply_markup
       )
       
       return States.ENTER_AMOUNT
       
   except Exception as e:
       logger.error(f"خطأ في دالة usdt_network_selected: {e}")
       await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
       return ConversationHandler.END


async def recipient_name_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال اسم المستلم الرباعي"""
    try:
        recipient_name = update.message.text.strip()
        
        # التحقق من أن الاسم رباعي
        name_parts = recipient_name.split()
        if len(name_parts) < 4:
            await update.message.reply_text(
                "⚠️ الرجاء إدخال الاسم الرباعي كاملاً\n"
            )
            return States.ENTER_RECIPIENT_NAME
        
        context.user_data['recipient_name'] = recipient_name
        
        keyboard = [
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📱 الرجاء إدخال رقم هاتف المستلم:\n"
            "مثال: 774994534",
            reply_markup=reply_markup
        )
        return States.ENTER_RECIPIENT_NUMBER
        
    except Exception as e:
        logger.error(f"خطأ في معالجة إدخال اسم المستلم: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return States.ENTER_RECIPIENT_NAME
    
    except Exception as e:
        logger.error(f"خطأ في دالة recipient_name_entered: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return States.ENTER_RECIPIENT_NAME


# تحديث دالة إدخال رقم الهاتف
async def recipient_number_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال رقم هاتف المستلم"""
    try:
        phone_number = update.message.text.strip()

        # التحقق من صحة رقم الهاتف
        if not phone_number.isdigit() or len(phone_number) != 9:
            await update.message.reply_text(
                "⚠️ رقم الهاتف غير صحيح\n"
                "الرجاء إدخال رقم هاتف صحيح مكون من 9 أرقام\n"
                "مثال: 774994534"
            )
            return States.ENTER_RECIPIENT_NUMBER

        context.user_data['recipient_number'] = phone_number

        keyboard = [
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "📍 الرجاء إدخال جهة التحويل:\n"
            "مثال: صرافة النجم، حزمي، شبكة جنوب، شبكة شمال",
            reply_markup=reply_markup
        )
        return States.ENTER_TRANSFER_AGENCY

    except Exception as e:
        logger.error(f"خطأ في معالجة إدخال رقم الهاتف: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return States.ENTER_RECIPIENT_NUMBER

async def handle_transfer_agency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال جهة التحويل"""
    try:
        agency = update.message.text.strip()
        if not agency:
            await update.message.reply_text(
                "⚠️ الرجاء إدخال جهة التحويل"
            )
            return States.ENTER_TRANSFER_AGENCY

        context.user_data['transfer_agency'] = agency

        # عرض ملخص البيانات للتأكيد
        recipient_info = (
   "💫 تفاصيل العملية\n"
   "──────────────\n\n"
   f"👤 المستلم: {context.user_data.get('recipient_name')}\n"
   f"📱 الجوال: {context.user_data.get('recipient_number')}\n" 
   f"🏦 جهة التحويل: {agency}\n"
   f"💱 العملة: {context.user_data.get('local_currency')}\n\n"
   "✅ هل المعلومات صحيحة؟"
)

        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، متابعة", callback_data="confirm_recipient_info"),
                InlineKeyboardButton("❌ تعديل المعلومات", callback_data="edit_recipient_info")
            ],
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(recipient_info, reply_markup=reply_markup)
        return States.CONFIRM_RECIPIENT_INFO

    except Exception as e:
        logger.error(f"خطأ في معالجة إدخال جهة التحويل: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return States.ENTER_TRANSFER_AGENCY

# إضافة دالة جديدة لمعالجة الملاحظات
async def handle_recipient_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال ملاحظات التحويل"""
    try:
        user_id = update.effective_user.id
        
        # التعامل مع زر التخطي
        if update.callback_query:
            query = update.callback_query
            await query.answer()
            notes = ""
            await query.message.delete()
        else:
            notes = update.message.text.strip()
        
        context.user_data['transfer_notes'] = notes
        
        # عرض ملخص المعلومات للتأكيد
        recipient_info = (
            "📋 ملخص معلومات التحويل:\n\n"
            f"👤 اسم المستلم: {context.user_data.get('recipient_name')}\n"
            f"📱 رقم الهاتف: {context.user_data.get('recipient_number')}"
        )
        
        # إضافة الملاحظات إذا وجدت
        if notes:
            recipient_info += f"\n📝 الملاحظات: {notes}"
            
        recipient_info += "\n\nهل المعلومات صحيحة؟"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، متابعة", callback_data="confirm_recipient_info"),
                InlineKeyboardButton("❌ إعادة الإدخال", callback_data="edit_recipient_info")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=recipient_info,
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                recipient_info,
                reply_markup=reply_markup
            )
            
        return States.CONFIRM_RECIPIENT_INFO
        
    except Exception as e:
        logger.error(f"خطأ في دالة handle_recipient_notes: {e}")
        await update.effective_message.reply_text(
            "عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
        )
        return States.CONFIRM_RECIPIENT_INFO


async def handle_recipient_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة تأكيد معلومات المستلم"""
    try:
        query = update.callback_query
        await query.answer()
        
        action = query.data
        if action == "edit_recipient_info":
            keyboard = [
                [InlineKeyboardButton("🔙 رجوع للعملات", callback_data="back_to_currencies")],
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="👤 الرجاء إدخال الاسم الرباعي للمستلم:\n",
                reply_markup=reply_markup
            )
            return States.ENTER_RECIPIENT_NAME
            
        elif action == "confirm_recipient_info":
            # حفظ المعلومات المؤكدة في context
            context.user_data['confirmed_recipient_info'] = {
                'name': context.user_data.get('recipient_name'),
                'phone': context.user_data.get('recipient_number'),
                'agency': context.user_data.get('transfer_agency')
            }
            
            # عرض اختيار العملة الرقمية
            keyboard = []
            for currency in DIGITAL_CURRENCIES:
                button_text = f"💎 {currency['name']}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"digital_{currency['id']}")])
            
            keyboard.extend([
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # عرض ملخص المعلومات المؤكدة
            summary = (
                "✅ تم تأكيد المعلومات:\n\n"
                f"👤 اسم المستلم: {context.user_data.get('recipient_name')}\n"
                f"📱 رقم الهاتف: {context.user_data.get('recipient_number')}\n"
                f"📍 جهة التحويل: {context.user_data.get('transfer_agency')}\n"
                f"💱 العملة المحلية: {context.user_data.get('local_currency', '-')}\n\n"
                "الرجاء اختيار العملة الرقمية:"
            )
            
            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=summary,
                reply_markup=reply_markup
            )
            return States.SELECT_DIGITAL_CURRENCY
            return States.SELECT_CURRENCY
            
        elif query.data == "edit_recipient_info":
            # حذف رسالة التأكيد
            await query.message.delete()
            
            # العودة لإدخال الاسم
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.reply_text(
                "⭐️ التحويل عبر الاسم\n\n"
                "الرجاء إدخال الاسم الرباعي للمستلم:\n",
                reply_markup=reply_markup
            )
            return States.ENTER_RECIPIENT_NAME
    
        else:
            # غير معروف
            await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
            return ConversationHandler.END
    except Exception as e:
        logger.error(f"خطأ في دالة handle_recipient_confirmation: {e}")
        await query.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END
async def amount_entered(update: Update, context: ContextTypes.DEFAULT_TYPE):
   try:
       user_id = update.message.from_user.id
       
       if context.user_data.get('processing_amount'):
           await update.message.reply_text("⚠️ يتم معالجة طلبك السابق. الرجاء الانتظار...")
           return States.ENTER_AMOUNT
           
       context.user_data['processing_amount'] = True

       try:
           amount = float(update.message.text)
           if amount <= 0:
               raise ValueError

           settings = db.get_settings()
           min_withdrawal = settings.get('min_withdrawal', 10)
           max_withdrawal = settings.get('max_withdrawal', 1000)
           fixed_fee_threshold = settings.get('fixed_fee_threshold', 20)
           fixed_fee_amount = settings.get('fixed_fee_amount', 1)
           percentage_fee = settings.get('percentage_fee', 0.05)
           
           if amount < min_withdrawal:
               await update.message.reply_text(f"❌ عذراً، المبلغ أقل من الحد الأدنى ({min_withdrawal} USDT)")
               context.user_data['processing_amount'] = False
               return States.ENTER_AMOUNT
               
           if amount > max_withdrawal:
               await update.message.reply_text(f"❌ عذراً، المبلغ أعلى من الحد الأقصى ({max_withdrawal} USDT)")
               context.user_data['processing_amount'] = False
               return States.ENTER_AMOUNT

           from random import uniform
           unique_amount = round(amount + uniform(0.001, 0.099), 3)

           commission = fixed_fee_amount if amount <= fixed_fee_threshold else amount * percentage_fee
           final_amount = amount - commission

           local_currency = context.user_data.get('local_currency', 'USD')
           exchange_rate = db.get_exchange_rate(local_currency)
           local_amount = final_amount * exchange_rate

           # تقريب المبلغ بالعملة المحلية حسب القواعد المطلوبة
           rounded_local_amount = round_local_amount(local_amount)

           context.user_data.update({
               'base_amount': amount,
               'unique_amount': unique_amount, 
               'final_usdt_amount': final_amount,
               'local_amount': local_amount,
               'rounded_local_amount': rounded_local_amount,
               'deposit_start_time': datetime.now()
           })

           network = context.user_data.get('usdt_network')
           if not network:
               await update.message.reply_text("عذراً، حدث خطأ في تحديد الشبكة.")
               context.user_data['processing_amount'] = False
               return ConversationHandler.END

           deposit_address = NETWORK_ADDRESSES.get(network)
           context.user_data['deposit_address'] = deposit_address

           commission_type = ' (ثابتة)' if amount <= fixed_fee_threshold else f' ({percentage_fee * 100}%)'

           amount_message = (
    f"💎 <b>يرجى تحويل هذا المبلغ بالضبط:</b>\n\n"
     
    "🔻🔻🔻🔻🔻🔻🔻🔻🔻🔻\n"
    f"<b><code>{unique_amount:.3f}</code> USDT</b>\n"
    "🔺🔺🔺🔺🔺🔺🔺🔺🔺🔺\n\n"
    "🔔<b>تنبيه...</b>\n"
    "📢 قم بالضغط على المبلغ لنسخه وتحويله بالضبط مع الكسور لكي تتم عملية السحب بنجاح.\n\n"
    "=============================\n"
    f"<code>{deposit_address}</code>\n"
    "=============================\n\n"
    "💵💵💵 <b>التفاصيل</b> 💵💵💵\n"
    f"• المبلغ الكلي: <b>{amount:.2f}</b> USDT\n"
    f"• العمولة: <b>{commission}</b> {commission_type}\n"
    f"• صافي المبلغ: <b>{final_amount:.1f}</b> USDT\n"
    f"• بالـ {local_currency}: <b>{int(rounded_local_amount)}</b> {CURRENCY_SYMBOLS.get(local_currency, '')}\n"
    f"• سعر الصرف: $1 = {exchange_rate:.2f} {CURRENCY_SYMBOLS.get(local_currency, '')}\n\n"
    "-----------------------------\n\n"
    "✅ اضغط على زر <b>إدخال رمز المعاملة</b> بعد التحويل.\n"
 
)


           keyboard = [
               [InlineKeyboardButton("✍️ إدخال رمز المعاملة", callback_data="enter_txid")],
               [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
           ]
           reply_markup = InlineKeyboardMarkup(keyboard)

           await update.message.reply_text(amount_message, parse_mode='HTML', reply_markup=reply_markup)

           context.user_data['processing_amount'] = False
           return States.WAITING_DEPOSIT

       except ValueError:
           await update.message.reply_text("⚠️ الرجاء إدخال مبلغ صحيح (مثال: 100.5)")
           context.user_data['processing_amount'] = False
           return States.ENTER_AMOUNT

   except Exception as e:
       logger.error(f"خطأ في معالجة إدخال المبلغ: {e}")
       context.user_data['processing_amount'] = False
       await update.message.reply_text("عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
       return States.ENTER_AMOUNT

async def request_txid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transaction hash entry request"""
    try:
        query = update.callback_query
        await query.answer()
        
        if not context.user_data.get('unique_amount'):
            await query.message.reply_text(
                "❌ لا توجد عملية تحويل نشطة. الرجاء بدء عملية جديدة."
            )
            return ConversationHandler.END

        network = context.user_data.get('usdt_network', 'TRC20')
        hash_example = "0x123...abc" if network in ["BEP20", "ERC20"] else "123...abc"
        
        await query.message.reply_text(
   "🔍 الرجاء إدخال رمز المعاملة (TXID):\n\n"
   f"📝 مثال: {hash_example}\n\n"
   "⚠️ تنبيهات هامة:\n\n"
   "• يجب نسخ الرمز بشكل كامل\n"
   "• تأكد من اكتمال تأكيد المعاملة على الشبكة",
   reply_markup=InlineKeyboardMarkup([[
       InlineKeyboardButton("❌ إلغاء", callback_data="cancel")
   ]])
)
        return States.ENTER_TXID
        
    except Exception as e:
        logger.error(f"Error in request_txid: {e}")
        if query:
            await query.message.reply_text("❌ حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END
async def verify_txid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التحقق من رمز المعاملة وإرسال الإشعار للمشرفين بعد التحقق من جميع الشروط"""
    try:
        user_id = update.message.from_user.id
        tx_id = update.message.text.strip()
        transfer_id = context.user_data.get('transfer_id')

        if not transfer_id:
            await update.message.reply_text(
                "⚠️ لا يمكن إتمام العملية حالياً، يرجى إعادة إدخال رمز المعاملة مرة أخرى:"
            )
            return States.ENTER_TXID

        transfer_data = context.user_data
        
        # محاولة إرسال رسالة مع معالجة خطأ انتهاء المهلة
        try:
            status_message = await update.message.reply_text("⏳ جاري التحقق من المعاملة...", parse_mode='HTML')
        except telegram.error.TimedOut:
            # في حالة انتهاء المهلة، نحاول مرة أخرى بدون تنسيق HTML
            logger.warning("تم انتهاء مهلة الاتصال عند إرسال رسالة التحقق. محاولة مرة أخرى...")
            try:
                status_message = await update.message.reply_text("جاري التحقق من المعاملة...")
            except Exception as e:
                logger.error(f"فشل في إرسال رسالة التحقق بعد المحاولة الثانية: {e}")
                return ConversationHandler.END
        
        # التحقق من تكرار رمز المعاملة في قاعدة البيانات
        if db.check_duplicate_txid(tx_id):
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_message.edit_text(
                "❌ رمز المعاملة مستخدم بالفعل!\n\n"
                "⚠️ لقد تم استخدام رمز المعاملة هذا في عملية سابقة.\n"
                "يرجى التأكد من إدخال رمز معاملة صحيح وغير مستخدم من قبل.",
                reply_markup=reply_markup
            )
            return States.ENTER_TXID

        # استخدام BlockchainScanner للتحقق من المعاملة
        scanner = BlockchainScanner()
        
        # التحقق من المعاملة مع جميع الشروط
        try:
            tx = await scanner.verify_transaction_by_hash(
                transfer_data.get('usdt_network', 'TRC20'),  # نوع الشبكة
                tx_id,  # رمز المعاملة
                Decimal(str(transfer_data['unique_amount'])),  # المبلغ المتوقع
                transfer_data['deposit_address']  # عنوان الإيداع
            )
        except telegram.error.TimedOut:
            logger.error(f"خطأ في التحقق من المعاملة: Timed out")
            keyboard = [
                [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data="retry_verification")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await status_message.edit_text(
                    "⚠️ انتهت مهلة الاتصال أثناء التحقق من المعاملة!\n\n"
                    "قد يكون هناك مشكلة في الاتصال بخدمة التحقق أو بطء في الشبكة.\n"
                    "يرجى المحاولة مرة أخرى بعد قليل.",
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"فشل في تحديث رسالة الخطأ: {e}")
                try:
                    await update.message.reply_text(
                        "⚠️ انتهت مهلة الاتصال أثناء التحقق من المعاملة!\n"
                        "يرجى المحاولة مرة أخرى بعد قليل.",
                        reply_markup=reply_markup
                    )
                except:
                    pass
            return States.ENTER_TXID
        except Exception as e:
            logger.error(f"خطأ في التحقق من المعاملة: {e}")
            keyboard = [
                [InlineKeyboardButton("🔄 إعادة المحاولة", callback_data="retry_verification")],
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                await status_message.edit_text(
                    "⚠️ حدث خطأ أثناء التحقق من المعاملة!\n\n"
                    "قد يكون هناك مشكلة في الاتصال بخدمة التحقق.\n"
                    "يرجى المحاولة مرة أخرى بعد قليل.",
                    reply_markup=reply_markup
                )
            except Exception as inner_e:
                logger.error(f"فشل في تحديث رسالة الخطأ: {inner_e}")
                try:
                    await update.message.reply_text(
                        "⚠️ حدث خطأ أثناء التحقق من المعاملة!\n"
                        "يرجاء المحاولة مرة أخرى بعد قليل.",
                        reply_markup=reply_markup
                    )
                except:
                    pass
            return States.ENTER_TXID

        if not tx:
            logger.error("لم يتم العثور على المعاملة")
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_message.edit_text(
                "❌ لم يتم العثور على المعاملة!\n\n"
                "⚠️ لقد تم التحقق من المعاملة، ولكن لم يتم العثور على المعاملة.\n"
                "يرجى التأكد من:\n"
                "• صحة رمز المعاملة\n"
                "• اكتمال المعاملة على الشبكة\n"
                "• استخدام عملة USDT\n"
                "• استخدام الشبكة الصحيحة",
                reply_markup=reply_markup
            )
            return States.ENTER_TXID
            
        contract_address = tx.get('contract_address', '').strip()
        if not contract_address:
            logger.error("لم يتم العثور على عنوان العقد في المعاملة")
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_message.edit_text(
                "❌ خطأ في التحقق من المعاملة!\n\n"
                "لم يتم العثور على معلومات العقد. يرجى التأكد من:\n"
                "• استخدام عملة USDT\n"
                "• اكتمال المعاملة على الشبكة\n"
                "• صحة رمز المعاملة",
                reply_markup=reply_markup
            )
            return States.ENTER_TXID
            
        expected_network = transfer_data.get('usdt_network', 'TRC20').upper()
        
        # تحديد الشبكة من عنوان العقد
        network_contracts = {
            'BEP20': ['0x55d398326f99059ff775485246999027b3197955'],  # BSC USDT
            'TRC20': ['TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'],         # TRON USDT
            'ERC20': ['0xdac17f958d2ee523a2206206994597c13d831ec7'],   # ETH USDT
            'ARB20': ['0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9']   # Arbitrum One USDT
        }
        
        actual_network = None
        contract_address_lower = contract_address.lower()
        for network, contracts in network_contracts.items():
            if any(contract.lower() == contract_address_lower for contract in contracts):
                actual_network = network
                break
                
        if not actual_network:
            logger.warning(f"عقد غير معروف: {contract_address} للشبكة المتوقعة: {expected_network}")
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            network_contracts_info = {
                'BEP20': 'Binance Smart Chain (BSC)',
                'TRC20': 'TRON Network',
                'ERC20': 'Ethereum Network',
                'ARB20': 'Arbitrum One'
            }
            
            await status_message.edit_text(
                f"❌ لم يتم التعرف على عقد USDT!\n\n"
                f"⚠️ تأكد من استخدام عقد USDT الصحيح:\n"
                f"• الشبكة المطلوبة: {expected_network} ({network_contracts_info.get(expected_network, '')})\n"
                f"• العقد المستخدم: {contract_address}\n\n"
                f"ℹ️ يرجى التأكد من إرسال USDT على شبكة {network_contracts_info.get(expected_network, expected_network)}",
                reply_markup=reply_markup
            )
            return States.ENTER_TXID
            
        if actual_network != expected_network:
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_message.edit_text(
                "❌ الشبكة المستخدمة غير صحيحة!\n\n"
                "⚠️ تفاصيل الخطأ:\n"
                f"• الشبكة المطلوبة: {expected_network}\n"
                f"• الشبكة المستخدمة: {actual_network}\n\n"
                "ℹ️ يرجى إرسال المبلغ على نفس الشبكة المطلوبة.",
                reply_markup=reply_markup
            )
            return States.ENTER_TXID

        # حساب العمولة والمبالغ
        settings = db.get_settings()
        amount = float(tx['amount'])
        commission = (settings['fixed_fee_amount'] 
                    if amount <= settings['fixed_fee_threshold'] 
                    else amount * settings['percentage_fee'])
        usd_amount = round(amount - commission, 2)
        
        # حساب المبلغ بالعملة المحلية
        local_currency = transfer_data.get('local_currency', 'USD')
        exchange_rate = db.get_exchange_rate(local_currency)
        local_amount = round(usd_amount * exchange_rate, 2)

        # تحديث بيانات التحويل
        transfer_data.update({
            'amount': amount,
            'tx_hash': tx['txid'],
            'status': 'pending_review',
            'verified_at': datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            'username': update.effective_user.username,
            'usd_amount': usd_amount,
            'commission': commission,
            'local_amount': local_amount,
            'exchange_rate': exchange_rate,
            'network': actual_network,
            'contract_address': tx.get('contract_address', ''),
            'from_address': tx.get('from_address', '')
        })

        if not db.save_transfer(transfer_data):
            raise Exception("فشل في حفظ بيانات التحويل")

        # إنشاء رسالة التحقق
        verification_message = (
            "✅ <b>تم التحقق من المعاملة بنجاح!</b>\n\n"
            "<b>📝 تفاصيل التحويل:</b>\n"
            f"💰 <b>نوع التحويل:</b> {transfer_data.get('transfer_type', 'تحويل عبر الاسم') if transfer_data.get('transfer_type') == 'name_transfer' else 'إيداع لرقم حساب'}\n"
            f"🏦 <b>المحفظة:</b> <code>{transfer_data.get('wallet_name', '-')}</code>\n"
            f"📊 <b>رقم الحساب:</b> <code>{transfer_data.get('account_number', '-')}</code>\n"
            f"💱 <b>العملة المحلية:</b> {local_currency}\n\n"
            "<b>💰 تفاصيل المبلغ:</b>\n"
            f"• <b>المبلغ الكلي:</b> <code>{amount:.2f}</code> USDT\n"
            f"• <b>العمولة:</b> <code>{commission:.2f}</code> USDT{' (ثابتة)' if amount <= settings['fixed_fee_threshold'] else ' (' + str(settings['percentage_fee']*100) + '%)'}\n"
            f"• <b>صافي المبلغ:</b> <code>{usd_amount:.2f}</code> USDT\n"
            f"• <b>بالعملة المحلية:</b> <code>{int(local_amount)}</code> {local_currency}\n"
            f"• <b>سعر الصرف:</b> $1 = {exchange_rate:.2f} {local_currency}\n\n"
            "⏳ <b>جاري مراجعة طلبك .....، سيتم إرسال تأكيد التحويل قريباً...</b>"
        )

        await status_message.edit_text(verification_message, parse_mode='HTML')

        # إرسال إشعار للمشرفين
        await send_admin_notification(context, transfer_data)

        context.user_data['verification_message_id'] = status_message.message_id
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في التحقق من المعاملة: {str(e)}", exc_info=True)
        error_message = "⚠️ حدث خطأ أثناء التحقق من المعاملة.\n"
        
        if 'status_message' in locals():
            await status_message.edit_text(
                error_message + "الرجاء المحاولة مرة أخرى بعد قليل.",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(error_message, parse_mode='HTML')
        
        return States.ENTER_TXID

# تصدير الدوال المطلوبة
__all__ = [
    'start',
    'verify_registration_code',
    'show_transfer_options',
    'transfer_type_selected',
    'local_currency_selected',
    'wallet_selected',
    'account_number_entered',
    'usdt_network_selected',
    'amount_entered',
    'recipient_name_entered',
    'recipient_number_entered',
    'verify_txid',
    'request_txid',
    'cancel',
    'handle_pending_operation',
    'handle_recipient_confirmation',
    'handle_back',
    'handle_back_to_currencies',
    'handle_recipient_notes',
    'digital_currency_selected',
    'handle_transfer_agency',
    'handle_menu_selection',
    'update_registration_code',
    'handle_code_update'
]
from utils.message_utils import send_message_with_retry, send_photo_with_retry

async def start_new_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة طلب بدء عملية تحويل جديدة"""
    try:
        query = update.callback_query
        await query.answer()

        # تنظيف البيانات
        context.user_data.clear()

        # لا نقوم بحذف الرسالة السابقة

        user_id = query.from_user.id
        user = db.get_user(user_id)

        if user and db.verify_registration_code(user.get('registration_code')):
            # المستخدم مسجّل
            keyboard = [
                [
                    InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
                    InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
                ],
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            new_message = await send_message_with_retry(
                context=context,
                chat_id=update.effective_chat.id,
                text="👋👋 مرحباً بكم في خدمة السحب الالي من MetaBit 🔷\n\n"
                     "💸 الرجاء اختيار طريقة التحويل المبلغ اليك:",
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
            context.user_data['bot_messages'] = [new_message.message_id]

            # إرجاع الحالة لإخبار الـ ConversationHandler أننا في مرحلة اختيار نوع التحويل
            return States.SELECT_TRANSFER_TYPE
        else:
            # المستخدم غير مسجّل - مطالبة بإدخال كود التسجيل
            reg_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="👋 مرحباً بك!\n\n"
                     "⚠️ يجب عليك التسجيل أولاً.\n"
            )
            context.user_data['bot_messages'] = [reg_message.message_id]
            return States.ENTER_REGISTRATION_CODE

    except Exception as e:
        logger.error(f"خطأ في بدء عملية جديدة: {e}", exc_info=True)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى باستخدام /start"
        )
        return ConversationHandler.END

def calculate_commission(amount: float, settings: dict) -> float:
    """حساب العمولة على المبلغ"""
    if amount <= settings['fixed_fee_threshold']:
        return settings['fixed_fee_amount']
    return amount * settings['percentage_fee']
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء العملية الحالية وبدء عملية جديدة"""
    try:
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        # حذف الرسالة التي تحتوي على زر الإلغاء
        if update.callback_query:
            await update.callback_query.answer()
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
        elif update.message:
            try:
                await update.message.delete()
            except Exception:
                pass

        # تنظيف البيانات
        context.user_data.clear()

        # بدء عملية جديدة
        keyboard = [
            [
                InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
                InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
            ],
            [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        new_message = await context.bot.send_message(
            chat_id=chat_id,
            text="👋👋 مرحباً بكم في خدمة السحب الالي من MetaBit 🔷\n\n"
                 "💸 الرجاء اختيار طريقة التحويل المبلغ اليك:",
            reply_markup=reply_markup
        )
        
        # تخزين معرف الرسالة الجديدة
        context.user_data['bot_messages'] = [new_message.message_id]
        
        return States.SELECT_TRANSFER_TYPE

    except Exception as e:
        logger.error(f"خطأ في دالة الإلغاء: {e}")
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
            )
        except Exception:
            pass
        return ConversationHandler.END

async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة أزرار الرجوع المختلفة"""
    try:
        query = update.callback_query
        await query.answer()
        
        action = query.data.split('_')[1]  # مثل back_to_networks -> networks

        if action == "to_networks":
            # الرجوع لاختيار الشبكة
            keyboard = []
            for network_code, info in NETWORK_INFO.items():
                button_text = f"{network_code} ({info['name']})"
                if info.get('is_highlighted'):
                    button_text += " ⭐️"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"network_{network_code}")])
            
            keyboard.extend([
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = (
                "🌐 الرجاء اختيار شبكة التحويل:\n\n"
                "ℹ️ معلومات الشبكات:\n"
                "• TRC20: رسوم تحويل منخفضة (1 USDT)\n"
                "• BEP20: رسوم تحويل متوسطة (0.5-1 USDT)\n"
                "• ERC20: رسوم تحويل مرتفعة (10-50 USDT)"
            )

            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=message,
                reply_markup=reply_markup
            )
            return States.SELECT_USDT_NETWORK

        elif action == "to_transfer_type":
            # الرجوع لاختيار نوع التحويل
            keyboard = [
                [
                    InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
                    InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
                ],
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="👋 مرحباً بك في خدمة السحب الالي من MetaBit 🔷\n\n"
                "💸 الرجاء اختيار طريقة التحويل:",
                reply_markup=reply_markup
            )
            return States.SELECT_TRANSFER_TYPE

        elif action == "to_currencies":
            # الرجوع لاختيار العملة
            keyboard = []
            for currency in CURRENCIES:
                button_text = f"{currency['name']} ({currency['symbol']})"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"currency_{currency['code']}")])
            
            keyboard.append([InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="💱 الرجاء اختيار عملة التحويل:",
                reply_markup=reply_markup
            )
            return States.SELECT_LOCAL_CURRENCY

        elif action == "to_wallet":
            # الرجوع لاختيار المحفظة
            keyboard = []
            for wallet in WALLETS:
                button_text = f"📱 {wallet['name']}" if wallet.get('is_highlighted') else wallet['name']
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"wallet_{wallet['id']}")])
            
            keyboard.extend([
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ])
            reply_markup = InlineKeyboardMarkup(keyboard)

            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="💼 الرجاء اختيار المحفظة:",
                reply_markup=reply_markup
            )
            return States.SELECT_WALLET

        elif action == "to_recipient_info":
            # الرجوع لمعلومات المستلم
            keyboard = [
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await edit_message_with_retry(
                context,
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text="👤 الرجاء إدخال الاسم الرباعي للمستلم:\n",
                reply_markup=reply_markup
            )
            return States.ENTER_RECIPIENT_NAME

        else:
            logger.warning(f"زر رجوع غير معروف: {action}")
            await query.message.reply_text("⚠️ عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
            return ConversationHandler.END

    except Exception as e:
        logger.error(f"خطأ في معالجة زر الرجوع: {e}")
        await query.message.reply_text("⚠️ عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى.")
        return ConversationHandler.END
async def handle_persistent_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة الأزرار من الرسائل القديمة"""
    try:
        query = update.callback_query
        data = query.data
        
        if data == 'cancel':
            # حذف الرسالة التي تحتوي على الزر
            try:
                await query.message.delete()
            except Exception:
                pass

            # تنظيف البيانات
            context.user_data.clear()

            # بدء عملية جديدة
            keyboard = [
                [
                    InlineKeyboardButton("👤 تحويل عبر الاسم", callback_data="name_transfer"),
                    InlineKeyboardButton("🏦 إيداع لرقم حساب", callback_data="transfer_account")
                ],
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            new_message = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="👋👋 مرحباً بكم في خدمة السحب الالي من MetaBit 🔷\n\n"
                     "💸 الرجاء اختيار طريقة التحويل المبلغ اليك:",
                reply_markup=reply_markup
            )
            
            # تخزين معرف الرسالة الجديدة
            context.user_data['bot_messages'] = [new_message.message_id]
            
            return States.SELECT_TRANSFER_TYPE

    except Exception as e:
        logger.error(f"خطأ في معالجة callback دائم: {e}")
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="عذراً، حدث خطأ. الرجاء المحاولة مرة أخرى."
            )
        except Exception:
            pass
        return ConversationHandler.END

# تصدير جميع الدوال المطلوبة
__all__ = [
    'start',
    'verify_registration_code',
    'start_new_transfer',
    'show_transfer_options',
    'transfer_type_selected',
    'currency_selected',
    'recipient_name_entered',
    'recipient_number_entered',
    'wallet_selected',
    'account_number_entered',
    'usdt_network_selected',
    'amount_entered',
    'check_deposit',
    'request_txid',
    'verify_txid',
    'cancel',
    'handle_pending_operation',
    'handle_back',
    'local_currency_selected',
    'handle_recipient_confirmation',
    'handle_recipient_notes',
    'handle_back_to_currencies',
    'digital_currency_selected',
    'handle_transfer_agency'
]
