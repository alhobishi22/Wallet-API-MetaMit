import telegram
import logging
import asyncio

logger = logging.getLogger(__name__)

async def send_message_with_retry(context, chat_id, text, reply_markup=None, max_retries=3, parse_mode=None):
    """إرسال رسالة مع إعادة المحاولة في حالة فشل الاتصال"""
    for attempt in range(max_retries):
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
        except telegram.error.TimedOut as e:
            if attempt == max_retries - 1:  # آخر محاولة
                logger.error(f"فشل في إرسال الرسالة بعد {max_retries} محاولات: {e}")
                raise
            await asyncio.sleep(2 ** attempt)  # انتظار متزايد بين المحاولات
        except Exception as e:
            logger.error(f"خطأ في إرسال الرسالة: {e}")
            raise

async def send_photo_with_retry(context, chat_id, photo, caption=None, reply_markup=None, max_retries=3, parse_mode=None):
    """إرسال صورة مع إعادة المحاولة في حالة فشل الاتصال"""
    for attempt in range(max_retries):
        try:
            return await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
        except telegram.error.TimedOut as e:
            if attempt == max_retries - 1:  # آخر محاولة
                logger.error(f"فشل في إرسال الصورة بعد {max_retries} محاولات: {e}")
                raise
            await asyncio.sleep(2 ** attempt)  # انتظار متزايد بين المحاولات
        except Exception as e:
            logger.error(f"خطأ في إرسال الصورة: {e}")
            raise

async def edit_message_with_retry(context, chat_id, message_id, text, reply_markup=None, max_retries=3, parse_mode=None):
    """تعديل رسالة مع إعادة المحاولة في حالة فشل الاتصال"""
    for attempt in range(max_retries):
        try:
            return await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
        except telegram.error.TimedOut as e:
            if attempt == max_retries - 1:  # آخر محاولة
                logger.error(f"فشل في تعديل الرسالة بعد {max_retries} محاولات: {e}")
                raise
            await asyncio.sleep(2 ** attempt)  # انتظار متزايد بين المحاولات
        except telegram.error.BadRequest as e:
            # في حالة وجود مشكلة في تعديل الرسالة (مثلاً الرسالة قديمة جداً)
            logger.error(f"خطأ في تعديل الرسالة: {e}")
            raise
        except Exception as e:
            logger.error(f"خطأ غير متوقع في تعديل الرسالة: {e}")
            raise

async def edit_message_reply_markup_with_retry(context, chat_id, message_id, reply_markup=None, max_retries=3):
    """تعديل أزرار الرسالة مع إعادة المحاولة في حالة فشل الاتصال"""
    for attempt in range(max_retries):
        try:
            return await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
        except telegram.error.TimedOut as e:
            if attempt == max_retries - 1:  # آخر محاولة
                logger.error(f"فشل في تعديل أزرار الرسالة بعد {max_retries} محاولات: {e}")
                raise
            await asyncio.sleep(2 ** attempt)  # انتظار متزايد بين المحاولات
        except telegram.error.BadRequest as e:
            # في حالة وجود مشكلة في تعديل الرسالة (مثلاً الرسالة قديمة جداً)
            logger.error(f"خطأ في تعديل أزرار الرسالة: {e}")
            raise
        except Exception as e:
            logger.error(f"خطأ غير متوقع في تعديل أزرار الرسالة: {e}")
            raise

def round_local_amount(amount: float) -> int:
    """
    تقريب المبلغ بالعملة المحلية إلى أقرب رقم صحيح حسب القواعد التالية:
    - إذا كان الجزء العشري أقل من أو يساوي 0.8، يتم تقريبه إلى 0
    - إذا كان الجزء العشري أكبر من 0.8، يتم تقريبه إلى 1
    
    :param amount: المبلغ الأصلي
    :return: المبلغ المقرب كرقم صحيح
    """
    decimal_part = amount - int(amount)
    if decimal_part <= 0.8:
        return int(amount)
    else:
        return int(amount) + 1
