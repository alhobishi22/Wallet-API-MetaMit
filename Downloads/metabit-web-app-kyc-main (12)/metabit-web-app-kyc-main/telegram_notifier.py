import os
import logging
import aiohttp
import asyncio
import requests
import database
from dotenv import load_dotenv
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import CallbackQueryHandler
import database

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ADMIN_GROUP_ID = int(os.getenv('ADMIN_GROUP_ID')) if os.getenv('ADMIN_GROUP_ID') else None
ADMIN_TELEGRAM_ID = os.getenv('ADMIN_TELEGRAM_ID')

# وظيفة أساسية لإرسال الإشعارات
async def send_telegram_message(chat_id, message, parse_mode=None, photo=None, reply_markup=None):
    """
    وظيفة أساسية لإرسال رسائل تلغرام (نص أو صور)
    """
    try:
        if not chat_id:
            logger.warning("لم يتم تحديد معرف دردشة")
            return False

        # تنظيف معرف الدردشة
        if isinstance(chat_id, str):
            chat_id = chat_id.strip()
            if chat_id.startswith('@'):
                chat_id = chat_id[1:]
            try:
                chat_id = int(chat_id)
            except ValueError:
                logger.warning(f"معرف دردشة غير صالح: {chat_id}")
                return False

        # التحقق من أن المعرف رقم صحيح غير صفري
        # معرفات المجموعات يمكن أن تكون سالبة، لذا نتحقق فقط أنها ليست صفر
        if chat_id == 0:
            logger.warning(f"معرف دردشة غير صالح (صفر): {chat_id}")
            return False

        # إنشاء البوت
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        try:
            if photo:
                # إرسال صورة
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=message,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            else:
                # إرسال نص
                await bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                )
            
            logger.info(f"تم إرسال الإشعار بنجاح للمستخدم {chat_id}")
            return True
        
        except Exception as e:
            logger.error(f"خطأ في إرسال الإشعار للمستخدم: {str(e)}")
            
            # محاولة إرسال الإشعار باستخدام الطريقة البديلة
            logger.info(f"محاولة إرسال الإشعار باستخدام الطريقة البديلة...")
            
            # استخدام HTTP API مباشرة
            api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            if photo:
                api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": parse_mode
            }
            
            if photo:
                payload = {
                    "chat_id": chat_id,
                    "photo": photo,
                    "caption": message,
                    "parse_mode": parse_mode
                }
            
            if reply_markup:
                payload["reply_markup"] = reply_markup.to_dict() if hasattr(reply_markup, 'to_dict') else reply_markup
            
            # سجل الطلب للتشخيص
            logger.info(f"إرسال طلب HTTP إلى {api_url} مع chat_id={chat_id}")
            
            # إرسال الطلب
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload) as response:
                    response_text = await response.text()
                    logger.info(f"استجابة Telegram API: {response_text}")
                    
                    # التحقق من نجاح الطلب
                    if response.status == 200:
                        logger.info(f"تم إرسال الإشعار بنجاح للمستخدم {chat_id} باستخدام الطريقة البديلة")
                        return True
                    else:
                        logger.error(f"فشل في إرسال الإشعار باستخدام الطريقة البديلة: {response_text}")
                        return False
        finally:
            try:
                await bot.close()
            except Exception as e:
                logger.error(f"خطأ عند إغلاق اتصال البوت: {str(e)}")
    
    except Exception as e:
        logger.error(f"خطأ في إرسال الإشعار: {str(e)}")
        return False

# وظيفة لإرسال إشعار للمستخدم
async def send_user_notification(chat_id, message, parse_mode=None, photo=None, reply_markup=None):
    """
    إرسال إشعار للمستخدم
    """
    return await send_telegram_message(chat_id, message, parse_mode, photo, reply_markup)

# وظيفة لإرسال مجموعة صور
async def send_media_group(chat_id, media_list):
    """
    إرسال مجموعة من الصور
    """
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        await bot.send_media_group(chat_id=chat_id, media=media_list)
        logger.info(f"تم إرسال مجموعة الصور بنجاح إلى {chat_id}")
        return True
    except Exception as e:
        logger.error(f"خطأ في إرسال مجموعة الصور: {str(e)}")
        return False
    finally:
        try:
            await bot.close()
        except Exception as e:
            logger.error(f"خطأ عند إغلاق اتصال البوت: {str(e)}")

# وظيفة لإرسال إشعار بطلب KYC جديد إلى المشرفين
async def send_admin_notification(kyc_data):
    """
    إرسال إشعار بطلب KYC جديد إلى مجموعة المشرفين
    """
    if not ADMIN_GROUP_ID:
        logger.warning("لم يتم تعيين معرف مجموعة المشرفين")
        return False

    try:
        # إنشاء البوت
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        
        # إعداد الرسالة
        message = f"""
📝 *طلب توثيق جديد*

🆔 رقم الطلب: `{kyc_data['application_id']}`
👤 الاسم: `{kyc_data['full_name']}`
📱 رقم الهاتف: `{kyc_data['phone_number']}`
🏠 العنوان: {kyc_data['address']}
🔗 معرف التلغرام: `{kyc_data.get('telegram_chat_id', 'غير متوفر')}`
        """
        
        # إضافة معلومات الجهاز والموقع الجغرافي إذا كانت متاحة
        device_info_message = "\n📱 *معلومات الجهاز والموقع*\n"
        
        # إضافة عنوان IP
        ip_address = kyc_data.get('ip_address', 'غير متاح')
        device_info_message += f"🌐 عنوان IP: `{ip_address}`\n"
        
        # إضافة معلومات الموقع الجغرافي
        geo_location = kyc_data.get('geo_location', {})
        if geo_location:
            country = geo_location.get('country', 'غير متاح')
            city = geo_location.get('city', 'غير متاح')
            region = geo_location.get('region', 'غير متاح')
            org = geo_location.get('org', 'غير متاح')
            device_info_message += f"🗺️ الموقع: {country}, {city}, {region}\n"
            device_info_message += f"🏢 مزود الخدمة: {org}\n"
        
        # إضافة معلومات المتصفح ونظام التشغيل
        device_info = kyc_data.get('device_info', {})
        if device_info:
            browser_info = device_info.get('browser', {})
            system_info = device_info.get('system', {})
            
            browser_name = browser_info.get('name', 'غير متاح')
            browser_language = browser_info.get('language', 'غير متاح')
            
            os_name = system_info.get('os', 'غير متاح')
            time_zone = system_info.get('timeZone', 'غير متاح')
            
            device_info_message += f"🌐 المتصفح: {browser_name}\n"
            device_info_message += f"💻 نظام التشغيل: {os_name}\n"
            device_info_message += f"🕒 المنطقة الزمنية: {time_zone}\n"
        
        # إضافة معلومات الجهاز إلى الرسالة الرئيسية
        message += device_info_message
        
        # إنشاء أزرار التحكم
        keyboard = [
            [
                InlineKeyboardButton("قبول ✅", callback_data=f"approve_{kyc_data['application_id']}"),
                InlineKeyboardButton("رفض ❌", callback_data=f"reject_{kyc_data['application_id']}")
            ],
            [
                InlineKeyboardButton("عرض الهوية 🪪", callback_data=f"view_id_{kyc_data['application_id']}"),
                InlineKeyboardButton("عرض الصورة الشخصية 🤳", callback_data=f"view_selfie_{kyc_data['application_id']}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # إرسال الإشعار إلى مجموعة المشرفين
        await bot.send_message(
            chat_id=ADMIN_GROUP_ID,
            text=message,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        
        logger.info(f"تم إرسال إشعار بطلب KYC جديد إلى مجموعة المشرفين")
        return True
        
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار KYC للمشرفين: {str(e)}")
        return False

# معالج الاستجابة للأزرار
async def button_callback_handler(update, context):
    """
    معالجة الضغط على الأزرار في رسائل التلغرام
    """
    query = update.callback_query
    await query.answer()  # إرسال إشعار بأن الزر تم الضغط عليه
    
    callback_data = query.data
    
    # التحقق من نوع الإجراء
    if callback_data.startswith("approve_"):
        # استخراج رقم الطلب
        request_id = callback_data.replace("approve_", "")
        
        # إنشاء رمز التسجيل
        registration_code = f"MB-{os.urandom(4).hex().upper()}"
        
        # الحصول على اسم المشرف
        admin_full_name = update.effective_user.full_name
        
        # تحديث حالة الطلب في قاعدة البيانات
        success, message = database.approve_application(request_id, admin_full_name, registration_code)
        
        if success:
            # تحديث الرسالة الأصلية
            new_text = f"""
✅ *تم قبول الطلب*

🆔 رقم الطلب: `{request_id}`
👤 تم القبول بواسطة: {admin_full_name}
🔑 رمز التسجيل: `{registration_code}`
            """
            
            await query.edit_message_text(
                text=new_text,
                parse_mode="Markdown"
            )
            
            # إرسال إشعار للمستخدم إذا كان لديه معرف تلغرام
            user_chat_id = database.get_user_telegram_id(request_id)
            
            if user_chat_id:
                user_message = f"""
🎉 *تهانينا!* 🎉

تم الموافقة على طلب التوثيق الخاص بك بنجاح.

🆔 رقم الطلب: `{request_id}`
🔑 رمز التسجيل الخاص بك: `{registration_code}`

*خطوات التفعيل:*
1. *انقر على رمز التسجيل أعلاه* لنسخه تلقائياً.
2. *انتقل إلى بوت الإيداع الرسمي* والصق الرمز لتفعيل حسابك والاستفادة من جميع الخدمات.

_شكراً لثقتكم بنا - فريق ميتابت_
                """
                
                # إنشاء أزرار للانتقال إلى بوت الإيداع وبوت السحب
                keyboard = [
                    [
                        InlineKeyboardButton("بوت الإيداع 💰", url="https://t.me/MetaBit_Trx_Bot"),
                        InlineKeyboardButton("بوت السحب 💸", url="https://t.me/metabittradebot")
                    ]
                ]
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await send_user_notification(user_chat_id, user_message, parse_mode="Markdown", reply_markup=reply_markup)
        else:
            # إظهار رسالة الخطأ
            await query.edit_message_text(
                text=f"❌ حدث خطأ أثناء قبول الطلب: {message}",
                parse_mode="Markdown"
            )
    
    elif callback_data.startswith("reject_"):
        # استخراج رقم الطلب
        request_id = callback_data.replace("reject_", "")
        
        # إنشاء أزرار لتأكيد الرفض وإدخال السبب
        keyboard = [
            [
                InlineKeyboardButton("تأكيد الرفض ❌", callback_data=f"confirm_reject_{request_id}_بيانات غير صحيحة"),
                InlineKeyboardButton("إلغاء ↩️", callback_data=f"cancel_reject_{request_id}")
            ],
            [
                InlineKeyboardButton("بيانات غير صحيحة", callback_data=f"confirm_reject_{request_id}_بيانات غير صحيحة"),
                InlineKeyboardButton("صور غير واضحة", callback_data=f"confirm_reject_{request_id}_صور غير واضحة")
            ],
            [
                InlineKeyboardButton("هوية منتهية", callback_data=f"confirm_reject_{request_id}_هوية منتهية"),
                InlineKeyboardButton("معلومات ناقصة", callback_data=f"confirm_reject_{request_id}_معلومات ناقصة")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"🛑 *تأكيد رفض الطلب*\n\nالرجاء اختيار سبب الرفض أو تأكيد الرفض:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    elif callback_data.startswith("confirm_reject_"):
        # استخراج رقم الطلب وسبب الرفض
        parts = callback_data.replace("confirm_reject_", "").split("_", 1)
        request_id = parts[0]
        rejection_reason = parts[1] if len(parts) > 1 else "بيانات غير صحيحة"
        
        # الحصول على اسم المشرف
        admin_full_name = update.effective_user.full_name
        
        # تحديث حالة الطلب في قاعدة البيانات
        success, message = database.reject_application(request_id, admin_full_name, rejection_reason)
        
        if success:
            # تحديث الرسالة الأصلية
            new_text = f"""
❌ *تم رفض الطلب*

🆔 رقم الطلب: `{request_id}`
👤 تم الرفض بواسطة: {admin_full_name}
❓ سبب الرفض: {rejection_reason}
            """
            
            await query.edit_message_text(
                text=new_text,
                parse_mode="Markdown"
            )
            
            # إرسال إشعار للمستخدم إذا كان لديه معرف تلغرام
            user_chat_id = database.get_user_telegram_id(request_id)
            
            if user_chat_id:
                user_message = f"""
⚠️ *إشعار بخصوص طلب التوثيق* ⚠️

نأسف لإبلاغك بأنه تم رفض طلب التوثيق الخاص بك.
🆔 رقم الطلب: `{request_id}`
❓ سبب الرفض: {rejection_reason}

يمكنك تقديم طلب جديد بعد تصحيح المشكلة.
                """
                
                await send_user_notification(user_chat_id, user_message, parse_mode="Markdown")
        else:
            # إظهار رسالة الخطأ
            await query.edit_message_text(
                text=f"❌ حدث خطأ أثناء رفض الطلب: {message}",
                parse_mode="Markdown"
            )
    
    elif callback_data.startswith("cancel_reject_"):
        # استخراج رقم الطلب
        request_id = callback_data.replace("cancel_reject_", "")
        
        # إعادة عرض أزرار التحكم الأصلية
        keyboard = [
            [
                InlineKeyboardButton("قبول ✅", callback_data=f"approve_{request_id}"),
                InlineKeyboardButton("رفض ❌", callback_data=f"reject_{request_id}")
            ],
            [
                InlineKeyboardButton("عرض الهوية 🪪", callback_data=f"view_id_{request_id}"),
                InlineKeyboardButton("عرض الصورة الشخصية 🤳", callback_data=f"view_selfie_{request_id}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=query.message.text.split("\n\n")[0] + "\n\nتم إلغاء عملية الرفض.",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    
    elif callback_data.startswith("view_id_") or callback_data.startswith("view_selfie_"):
        # استخراج رقم الطلب
        request_id = callback_data.replace("view_id_", "").replace("view_selfie_", "")
        
        # تحديد نوع الصورة
        is_id_photo = callback_data.startswith("view_id_")
        
        # الحصول على رابط الصورة من قاعدة البيانات
        success, photo_url = database.get_photo_url(request_id, is_id_photo)
        
        if success and photo_url:
            # إرسال الصورة كرسالة جديدة
            photo_type = "صورة الهوية" if is_id_photo else "الصورة الشخصية"
            caption = f"{photo_type} للطلب رقم: {request_id}"
            
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo_url,
                caption=caption
            )
        else:
            # إرسال رسالة خطأ
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ تعذر العثور على الصورة: {photo_url}"
            )

# Non-async version for direct API calls
def send_notification_to_user(chat_id, message, parse_mode=None, photo=None, reply_markup=None):
    """
    إرسال إشعار للمستخدم (نسخة غير متزامنة)
    """
    try:
        if not chat_id:
            logger.warning("لم يتم تحديد معرف دردشة")
            return {"ok": False, "description": "Chat ID not provided"}

        # تنظيف معرف الدردشة
        if isinstance(chat_id, str):
            chat_id = chat_id.strip()
            if chat_id.startswith('@'):
                chat_id = chat_id[1:]
            try:
                chat_id = int(chat_id)
            except ValueError:
                logger.warning(f"معرف دردشة غير صالح: {chat_id}")
                return {"ok": False, "description": "Invalid chat ID format"}

        # التحقق من أن المعرف رقم صحيح غير صفري
        # معرفات المجموعات يمكن أن تكون سالبة، لذا نتحقق فقط أنها ليست صفر
        if chat_id == 0:
            logger.warning(f"معرف دردشة غير صالح (صفر): {chat_id}")
            return {"ok": False, "description": "Invalid chat ID value"}

        if photo:
            # إرسال صورة
            api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
            payload = {
                "chat_id": chat_id,
                "photo": photo,
                "caption": message,
                "parse_mode": parse_mode
            }
        else:
            # إرسال نص
            api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": parse_mode
            }

        if reply_markup:
            payload["reply_markup"] = reply_markup.to_dict() if hasattr(reply_markup, 'to_dict') else reply_markup

        # إرسال الطلب
        response = requests.post(api_url, json=payload)
        result = response.json()

        if result.get("ok"):
            if photo:
                logger.info(f"تم إرسال الصورة بنجاح إلى {chat_id}")
            else:
                logger.info(f"تم إرسال الإشعار بنجاح إلى {chat_id}")
        else:
            error_desc = result.get('description', 'خطأ غير معروف')
            logger.error(f"فشل في إرسال الإشعار: {error_desc}")

        return result

    except Exception as e:
        logger.error(f"خطأ في إرسال الإشعار: {str(e)}")
        return {"ok": False, "description": str(e)}

# وظيفة لإرسال إشعار KYC
async def send_kyc_notification(request_id, status, details=""):
    """
    إرسال إشعار KYC للمستخدم بناءً على حالة الطلب
    
    :param request_id: معرف طلب KYC
    :param status: حالة الطلب (approved/rejected)
    :param details: تفاصيل إضافية (رمز التسجيل أو سبب الرفض)
    """
    try:
        # الحصول على معرف دردشة المستخدم من قاعدة البيانات
        user_chat_id = database.get_user_telegram_id(request_id)
        
        if not user_chat_id:
            logger.warning(f"لا يوجد معرف تلغرام للمستخدم صاحب الطلب {request_id}")
            return False
        
        # إعداد الرسالة بناءً على حالة الطلب
        if status == "approved":
            message = f"""
🎉 *تهانينا!* 🎉

تم الموافقة على طلب التوثيق الخاص بك بنجاح.

🆔 رقم الطلب: `{request_id}`
🔑 رمز التسجيل الخاص بك: `{details}`

*خطوات التفعيل:*
1. *انقر على رمز التسجيل أعلاه* لنسخه تلقائياً.
2. *انتقل إلى بوت الإيداع الرسمي* والصق الرمز لتفعيل حسابك والاستفادة من جميع الخدمات.

_شكراً لثقتكم بنا - فريق ميتابت_
            """
            
            # إنشاء أزرار للانتقال إلى بوت الإيداع وبوت السحب
            keyboard = [
                [
                    InlineKeyboardButton("بوت الإيداع 💰", url="https://t.me/MetaBit_Trx_Bot"),
                    InlineKeyboardButton("بوت السحب 💸", url="https://t.me/metabittradebot")
                ]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # إرسال الإشعار للمستخدم مع الأزرار
            result = await send_telegram_message(user_chat_id, message, parse_mode="Markdown", reply_markup=reply_markup)
            
            # حذف رسالة الترحيب إذا كانت موجودة
            welcome_message_id = database.get_welcome_message_id(user_chat_id)
            logger.info(f"معرف رسالة الترحيب للمستخدم {user_chat_id}: {welcome_message_id}")
            
            if welcome_message_id:
                logger.info(f"محاولة حذف رسالة الترحيب (معرف: {welcome_message_id}) للمستخدم {user_chat_id}")
                delete_result = await delete_telegram_message(user_chat_id, welcome_message_id)
                if delete_result:
                    logger.info(f"تم حذف رسالة الترحيب للمستخدم {user_chat_id} بنجاح")
                else:
                    logger.warning(f"فشل في حذف رسالة الترحيب للمستخدم {user_chat_id}")
            else:
                logger.info(f"لا يوجد معرف رسالة ترحيب للمستخدم {user_chat_id} لم يقم بحذف رسالة الترحيب")
        elif status == "rejected":
            message = f"""
⚠️ *إشعار بخصوص طلب التوثيق* ⚠️

نأسف لإبلاغك بأنه تم رفض طلب التوثيق الخاص بك.
🆔 رقم الطلب: `{request_id}`
❓ سبب الرفض: {details}

يمكنك تقديم طلب جديد بعد تصحيح المشكلة.
            """
        
            # إرسال الإشعار للمستخدم
            result = await send_telegram_message(user_chat_id, message, parse_mode="Markdown")
        else:
            message = f"""
📢 *إشعار بخصوص طلب التوثيق* 📢

هناك تحديث على طلب التوثيق الخاص بك:
🆔 رقم الطلب: `{request_id}`
📝 التفاصيل: {details}
            """
        
            # إرسال الإشعار للمستخدم
            result = await send_telegram_message(user_chat_id, message, parse_mode="Markdown")
        
        if result:
            logger.info(f"تم إرسال إشعار KYC للمستخدم {user_chat_id} بنجاح (الطلب: {request_id}, الحالة: {status})")
        else:
            logger.warning(f"فشل في إرسال إشعار KYC للمستخدم {user_chat_id} (الطلب: {request_id}, الحالة: {status})")
        
        return result
        
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار KYC للطلب {request_id}: {str(e)}")
        return False

# وظيفة للتحقق من صحة معرف المحادثة
def validate_chat_id(chat_id):
    """
    التحقق من صحة معرف المحادثة وتنظيفه
    
    :param chat_id: معرف الدردشة (رقم أو نص)
    :return: معرف الدردشة المعالج أو None إذا كان غير صالح
    """
    if not chat_id:
        return None

    # تنظيف معرف الدردشة
    if isinstance(chat_id, str):
        chat_id = chat_id.strip()
        if chat_id.startswith('@'):
            chat_id = chat_id[1:]
        try:
            chat_id = int(chat_id)
        except ValueError:
            logger.warning(f"معرف دردشة غير صالح: {chat_id}")
            return None

    # التحقق من أن المعرف رقم صحيح غير صفري
    # معرفات المجموعات يمكن أن تكون سالبة، لذا نتحقق فقط أنها ليست صفر
    if chat_id == 0:
        logger.warning("معرف الدردشة لا يمكن أن يكون صفر")
        return None
        
    return chat_id

# وظيفة لتحديث رسالة موجودة في تلغرام
async def update_telegram_message(chat_id, message_id, text, parse_mode=None, reply_markup=None):
    """
    تحديث رسالة موجودة في تلغرام
    """
    try:
        if not chat_id or not message_id:
            logger.warning("لم يتم تحديد معرف دردشة أو معرف رسالة")
            return False

        # إنشاء البوت
        bot = Bot(token=TELEGRAM_BOT_TOKEN)

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
            
            logger.info(f"تم تحديث الرسالة {message_id} بنجاح في الدردشة {chat_id}")
            return True
        
        except Exception as e:
            logger.error(f"خطأ في تحديث الرسالة: {str(e)}")
            
            # محاولة إرسال الرسالة باستخدام الطريقة البديلة
            logger.info(f"محاولة تحديث الرسالة باستخدام الطريقة البديلة...")
            
            # استخدام HTTP API مباشرة
            api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText"
            
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode
            }
            
            if reply_markup:
                payload["reply_markup"] = reply_markup.to_dict() if hasattr(reply_markup, 'to_dict') else reply_markup
            
            # سجل الطلب للتشخيص
            logger.info(f"إرسال طلب HTTP إلى {api_url} مع chat_id={chat_id}, message_id={message_id}")
            
            # إرسال الطلب
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=payload) as response:
                    response_text = await response.text()
                    logger.info(f"استجابة Telegram API: {response_text}")
                    
                    try:
                        result = await response.json()
                        
                        if result.get("ok"):
                            logger.info(f"تم تحديث الرسالة بنجاح عبر HTTP")
                            return True
                        else:
                            error_desc = result.get('description', 'خطأ غير معروف')
                            logger.error(f"فشل في تحديث الرسالة عبر HTTP: {error_desc}")
                            return False
                    except Exception as json_error:
                        logger.error(f"خطأ في تحليل استجابة JSON: {str(json_error)}")
                        return False
        
        finally:
            try:
                await bot.close()
            except Exception as e:
                logger.error(f"خطأ عند إغلاق اتصال البوت: {str(e)}")
    
    except Exception as e:
        logger.error(f"خطأ في تحديث الرسالة: {str(e)}")
        return False

# وظيفة لحذف رسالة من تلغرام
async def delete_telegram_message(chat_id, message_id):
    """
    حذف رسالة من تلغرام
    
    :param chat_id: معرف الدردشة
    :param message_id: معرف الرسالة
    :return: True إذا تم الحذف بنجاح، False في حالة الفشل
    """
    try:
        # التحقق من صحة المعرفات
        if not chat_id or not message_id:
            logger.warning("معرف الدردشة أو معرف الرسالة غير صالح")
            return False
        
        # تنظيف معرف الدردشة
        chat_id = validate_chat_id(chat_id)
        if not chat_id:
            logger.warning("معرف الدردشة غير صالح بعد التحقق")
            return False
            
        # التأكد من أن معرف الرسالة رقم
        try:
            message_id = int(message_id)
        except (ValueError, TypeError):
            logger.warning(f"معرف الرسالة غير صالح: {message_id}")
            return False
        
        # إعداد عنوان API
        api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
        
        # إعداد البيانات
        payload = {
            "chat_id": chat_id,
            "message_id": message_id
        }
        
        # إرسال الطلب
        logger.info(f"إرسال طلب حذف الرسالة {message_id} في الدردشة {chat_id}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload) as response:
                response_data = await response.json()
                
                if response.status == 200 and response_data.get('ok'):
                    logger.info(f"تم حذف الرسالة {message_id} بنجاح من الدردشة {chat_id}")
                    return True
                else:
                    error_description = response_data.get('description', 'خطأ غير معروف')
                    logger.warning(f"فشل في حذف الرسالة {message_id} من الدردشة {chat_id}: {error_description}")
                    return False
    
    except Exception as e:
        logger.error(f"خطأ في حذف الرسالة {message_id} من الدردشة {chat_id}: {str(e)}")
        return False