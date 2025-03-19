# services/telegram_service.py
from typing import Any, Optional, Union
import logging
from telegram import Bot, ReplyKeyboardMarkup, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TimedOut, NetworkError, RetryAfter
from telegram.request import HTTPXRequest
from config.settings import TELEGRAM_TOKEN
import asyncio
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

logger = logging.getLogger(__name__)

class TelegramService:
    """خدمة التلجرام مع دعم إعادة المحاولات والتعامل مع الأخطاء"""

    def __init__(self):
        """تهيئة خدمة Telegram مع إعدادات مخصصة"""
        # تكوين طلب HTTP مع المهل المحددة
        request = HTTPXRequest(
            connection_pool_size=100,
            read_timeout=30.0,
            write_timeout=30.0,
            connect_timeout=30.0,
            pool_timeout=3.0
        )
        
        # إنشاء كائن البوت مع الإعدادات المخصصة
        self.bot = Bot(token=TELEGRAM_TOKEN, request=request)
        self._setup_bot()

    def _setup_bot(self):
        """إعداد خيارات Bot الإضافية"""
        logger.info("✅ تم إعداد البوت بنجاح")

    async def send_message(
        self, 
        chat_id: int, 
        text: str, 
        parse_mode: str = ParseMode.MARKDOWN,
        reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None, 
        disable_web_page_preview: bool = False, 
        disable_notification: bool = False
    ) -> None:
        """
        إرسال رسالة إلى المستخدم أو المجموعة مع دعم لوحات المفاتيح التفاعلية.

        Args:
            chat_id: معرف الدردشة المستهدفة
            text: نص الرسالة المراد إرسالها
            parse_mode: وضع التحليل للنص (Markdown، HTML، إلخ)
            reply_markup: لوحة المفاتيح التفاعلية
            disable_web_page_preview: تعطيل معاينة الروابط
            disable_notification: إرسال الرسالة بدون إشعار
        """
        await self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
            disable_notification=disable_notification
        )
        logger.info(f"✅ تم إرسال الرسالة إلى {chat_id}")

    @retry(
        retry=retry_if_exception_type((TimedOut, NetworkError, RetryAfter)),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    async def send_message_with_retry(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        timeout_seconds: int = 30
    ) -> bool:
        """إرسال رسالة مع إعادة المحاولة تلقائية في حالة الفشل
        
        Args:
            chat_id: معرف المستخدم أو المجموعة
            text: نص الرسالة
            parse_mode: نمط تنسيق النص
            reply_markup: أزرار تفاعلية
            disable_web_page_preview: تعطيل معاينة الروابط
            disable_notification: إرسال الرسالة بدون إشعار
            timeout_seconds: مهلة الانتظار بالثواني
            
        Returns:
            bool: True إذا نجح الإرسال، False إذا فشل
        """
        try:
            await asyncio.wait_for(
                self.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=disable_web_page_preview,
                    disable_notification=disable_notification
                ),
                timeout=timeout_seconds
            )
            return True
        except asyncio.TimeoutError:
            logger.error(f"تجاوز الوقت المحدد عند إرسال رسالة إلى {chat_id}")
            return False
        except Exception as e:
            logger.error(f"خطأ غير متوقع عند إرسال رسالة إلى {chat_id}: {str(e)}")
            return False

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = ParseMode.MARKDOWN,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        timeout_seconds: int = 30
    ) -> bool:
        """
        تعديل رسالة موجودة

        Args:
            chat_id: معرف الدردشة
            message_id: معرف الرسالة
            text: النص الجديد
            parse_mode: نمط تنسيق النص
            reply_markup: أزرار تفاعلية جديدة
            timeout_seconds: مهلة الانتظار بالثواني

        Returns:
            bool: True إذا نجح التعديل، False إذا فشل
        """
        try:
            await asyncio.wait_for(
                self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup
                ),
                timeout=timeout_seconds
            )
            logger.info(f"✅ تم تعديل الرسالة {message_id} في الدردشة {chat_id}")
            return True
        except Exception as e:
            logger.error(f"❌ فشل تعديل الرسالة {message_id} في الدردشة {chat_id}: {str(e)}")
            return False

# إنشاء كائن telegram_service
telegram_service = TelegramService()