import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
import psutil
from pathlib import Path
from datetime import datetime
import codecs
import aiohttp
from asyncio import Lock
import signal
from services.withdrawal_manager import withdrawal_manager, LockStatus
from aiohttp import web
from contextlib import suppress
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    JobQueue,
    Defaults,
    CallbackContext,
    PicklePersistence
)

from handlers.confirmation_handler import get_conversation_handler, handle_cancel_pending
from handlers.admin_handler import get_admin_handlers
from handlers.admin_conversation import get_admin_conversation_handler as get_admins_conversation_handler
from handlers.help_handler import help_command
from config.settings import TELEGRAM_TOKEN, ADMIN_USER_IDS
from services.binance_service import binance_service
from services.database_service import (
    close_pool,
    initialize_database,
    get_active_withdrawals,
    update_withdrawal_status,
    cancel_stale_requests,
    create_pool,
    create_admin_actions_table,
    cleanup_admin_actions
)
from services.rate_limiting_service import rate_limiting_service
from services.settings_service import load_settings
from services.telegram_service import telegram_service
from services.monitoring_service import monitoring_service

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

async def periodic_cleanup(context: CallbackContext):
    """تنفيذ التنظيف الدوري للبيانات القديمة"""
    try:
        # تنظيف الإجراءات القديمة
        await cleanup_admin_actions()
        logger.info("تم تنفيذ التنظيف الدوري بنجاح")
    except Exception as e:
        logger.error(f"خطأ في التنظيف الدوري: {e}")

class BotApplication:
    def __init__(self):
        """تهيئة تطبيق البوت"""
        # المتغيرات الأساسية
        self.app = None
        self.web_app = None
        self.session = None
        self.pid_file = "bot.pid"
        
        # متغيرات التحكم
        self.running = False
        self.cleanup_on_startup = True
        self.stop_event = asyncio.Event()
        self._lock = Lock()
        
        # المهام الدورية
        self.health_check_task = None
        self.cleanup_task = None
        
        # معلومات الحالة
        self.start_time = None
        
        # إعدادات الاتصال
        self.connection_pool = None
        self.max_connections = 100
        self.request_timeout = 30
        self.update_interval = 1.0
        
        # الذاكرة المؤقتة والإعدادات
        self._cache: Dict[str, Any] = {}
        self._cleanup_interval = 60
        self._health_check_interval = 5

        # متغيرات تتبع التحذيرات
        self._last_memory_warning = None
        self._last_cpu_warning = None
        self._last_disk_warning = None
        self._warning_interval = 3600  # ساعة واحدة بين التحذيرات
        self._warning_thresholds = {
            'memory': 500,  # MB
            'cpu': 80,    # %
            'disk': 95    # %
        }

    async def init_database(self):
        """تهيئة قاعدة البيانات"""
        try:
            await initialize_database()
            # إنشاء جدول إجراءات المشرفين
            await create_admin_actions_table()
            logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}")
            raise

    async def setup_application(self):
        """إعداد تطبيق البوت"""
        try:
            if not TELEGRAM_TOKEN:
                raise ValueError("لم يتم تعيين TELEGRAM_TOKEN")

            logger.info("جاري إعداد تطبيق البوت...")

            # إعداد الاستمرارية
            persistence = PicklePersistence(
                filepath="data/bot_data.pickle",
                single_file=True,
                update_interval=60  # حفظ البيانات كل 60 ثانية
            )

            # تكوين التطبيق مع الإعدادات المحسنة
            builder = (
                ApplicationBuilder()
                .token(TELEGRAM_TOKEN)
                .persistence(persistence)  # إضافة الاستمرارية
                .read_timeout(30)
                .write_timeout(30)
                .connect_timeout(30)
                .pool_timeout(30)
                .connection_pool_size(self.max_connections)
                .concurrent_updates(True)
                .get_updates_http_version("1.1")
            )

            # إضافة خيارات إضافية للتعامل مع الأخطاء
            builder.rate_limiter(rate_limiter=None)  # تعطيل محدد المعدل الداخلي
            builder.arbitrary_callback_data(True)    # تمكين البيانات العشوائية للأزرار
            
            # بناء التطبيق
            self.app = builder.build()
            logger.info("✅ تم إنشاء تطبيق البوت")

            # إضافة معالج الأخطاء
            self.app.add_error_handler(self.error_handler)
            logger.info("✅ تم إضافة معالج الأخطاء")
            
            # إضافة معالج إلغاء الطلب السابق
            self.app.add_handler(CallbackQueryHandler(
                handle_cancel_pending,
                pattern="^cancel_pending_"
            ))
            logger.info("✅ تم إضافة معالج إلغاء الطلبات")
            
            # إضافة معالج المساعدة
            self.app.add_handler(CommandHandler("help", help_command))
            logger.info("✅ تم إضافة معالج المساعدة")
            
            # إضافة معالجات المشرفين
            logger.info("جاري إضافة معالجات المشرفين...")
            admin_conversation = get_admins_conversation_handler()
            self.app.add_handler(admin_conversation)

            for handler in get_admin_handlers():
                self.app.add_handler(handler)
            logger.info("✅ تم إضافة معالجات المشرفين")
            
            # إضافة معالج المحادثة العام
            conversation_handler = get_conversation_handler()
            self.app.add_handler(conversation_handler)
            logger.info("✅ تم إضافة معالج المحادثة العام")

            # إضافة مهمة التنظيف الدوري للإجراءات القديمة
            self.app.job_queue.run_repeating(
                periodic_cleanup,
                interval=3600,  # كل ساعة
                first=60  # بدء أول تنظيف بعد دقيقة
            )

            logger.info("✅ تم إعداد تطبيق البوت بنجاح")
            
        except Exception as e:
            logger.error(f"❌ خطأ في إعداد تطبيق البوت: {e}")
            raise

    async def init_services(self):
        """تهيئة الخدمات المطلوبة"""
        try:
            await self.init_database()
            await create_pool()
            await binance_service.initialize()
            await rate_limiting_service.initialize()
            
            if self.app:
                await load_settings(self.app.bot_data)
                # إضافة مهمة التنظيف الدوري لمدير السحب
                self.app.job_queue.run_repeating(
                    lambda context: withdrawal_manager.cleanup_expired_locks(),
                    interval=300,  # كل 5 دقائق
                    first=10  # بدء أول تنظيف بعد 10 ثواني من تشغيل البوت
                )
                
                # بدء المهام الدورية
                self.cleanup_task = asyncio.create_task(self.periodic_cleanup())
                self.health_check_task = asyncio.create_task(self.periodic_health_check())
                
                # بدء مهمة مراقبة الموارد
                asyncio.create_task(monitoring_service.monitor_resources())
                
                logger.info("✅ تم تهيئة جميع الخدمات بنجاح")
            
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة الخدمات: {e}")
            raise

    async def periodic_cleanup(self):
        """تنظيف دوري للنظام"""
        while not self.stop_event.is_set():
            try:
                await cancel_stale_requests()
                self._cache.clear()
                await asyncio.sleep(self._cleanup_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ خطأ في التنظيف الدوري: {e}")
                await asyncio.sleep(5)

    async def periodic_health_check(self):
        """فحص دوري لصحة النظام باستخدام خدمة المراقبة"""
        while not self.stop_event.is_set():
            try:
                # استخدام خدمة المراقبة للحصول على معلومات النظام
                memory_use = monitoring_service.get_memory_usage()
                cpu_percent = monitoring_service.get_cpu_usage()
                disk_usage = monitoring_service.get_disk_usage()
                uptime = monitoring_service.get_uptime()

                # التحقق من استخدام الموارد وتجميع التحذيرات
                warnings = []
                current_time = datetime.now()
                
                # فحص الذاكرة
                if memory_use > 500:
                    last_memory_warning = getattr(self, '_last_memory_warning', None)
                    if last_memory_warning is None or (current_time - last_memory_warning).total_seconds() > 3600:
                        warnings.append(f"⚠️ استخدام الذاكرة مرتفع: {memory_use:.1f} MB")
                        self._last_memory_warning = current_time

                # فحص المعالج
                if cpu_percent > 80:
                    last_cpu_warning = getattr(self, '_last_cpu_warning', None)
                    if last_cpu_warning is None or (current_time - last_cpu_warning).total_seconds() > 3600:
                        warnings.append(f"⚠️ استخدام المعالج مرتفع: {cpu_percent:.1f}%")
                        self._last_cpu_warning = current_time

                # فحص القرص
                if disk_usage['percent'] > 95:  # رفع العتبة إلى 95%
                    last_disk_warning = getattr(self, '_last_disk_warning', None)
                    if last_disk_warning is None or (current_time - last_disk_warning).total_seconds() > 3600:
                        warnings.append(
                            f"⚠️ مساحة القرص منخفضة: {disk_usage['free']:.1f} GB متبقية\n"
                            f"({disk_usage['percent']}% مستخدم)"
                        )
                        self._last_disk_warning = current_time

                # إرسال التحذيرات المجمعة للمشرفين
                if warnings:
                    warning_message = "🚨 تحذير حالة النظام:\n\n" + "\n\n".join(warnings)
                    logger.warning(warning_message)
                    
                    for admin_id in ADMIN_USER_IDS:
                        try:
                            await telegram_service.send_message_with_retry(
                                chat_id=admin_id,
                                text=warning_message
                            )
                        except Exception as e:
                            logger.error(f"خطأ في إرسال التحذير للمشرف {admin_id}: {e}")

                # تسجيل معلومات النظام
                logger.info(
                    f"ℹ️ معلومات النظام - "
                    f"وقت التشغيل: {uptime}, "
                    f"الذاكرة: {memory_use:.2f} MB, "
                    f"المعالج: {cpu_percent:.1f}%, "
                    f"القرص: {disk_usage['percent']}% مستخدم"
                )

                await asyncio.sleep(self._health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ خطأ في فحص صحة النظام: {e}")
                await asyncio.sleep(5)

    def setup_signal_handlers(self):
        """إعداد معالجات الإشارات"""
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, lambda s, f: asyncio.create_task(self.stop()))
            except NotImplementedError:
                pass

    async def ensure_single_instance(self) -> bool:
        """التأكد من عدم وجود نسخة أخرى من البوت"""
        try:
            pid_path = Path(self.pid_file)
            if pid_path.exists():
                try:
                    old_pid = int(pid_path.read_text().strip())
                    if psutil.pid_exists(old_pid):
                        process = psutil.Process(old_pid)
                        if process.name().startswith('python'):
                            logger.warning(f"⚠️ نسخة أخرى من البوت قيد التشغيل (PID: {old_pid})")
                            return False
                except (ValueError, psutil.NoSuchProcess):
                    pass
                pid_path.unlink()
            
            pid_path.write_text(str(os.getpid()))
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من النسخ المتعددة: {e}")
            return False

    async def start(self):
        """بدء تشغيل البوت"""
        try:
            async with self._lock:
                if self.running:
                    return False

                if not await self.ensure_single_instance():
                    return False

                self.start_time = datetime.now()
                self.setup_signal_handlers()
                
                # تهيئة جلسة HTTP
                self.session = aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(
                        limit=self.max_connections,
                        ttl_dns_cache=300,
                        force_close=True
                    ),
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout)
                )

                await self.init_services()
                await self.setup_application()
                
                # بدء تشغيل البوت
                await self.app.initialize()
                await self.app.start()
                await self.app.updater.start_polling(
                    allowed_updates=['message', 'callback_query'],
                    drop_pending_updates=True,
                    read_timeout=5,
                    timeout=5
                )
                
                self.running = True
                logger.info("✅ تم بدء تشغيل البوت بنجاح")
                return True

        except Exception as e:
            logger.error(f"❌ خطأ في بدء تشغيل البوت: {e}")
            await self.stop()
            raise

    async def stop(self):
        """إيقاف البوت"""
        try:
            async with self._lock:
                if not self.running:
                    return

                logger.info("جاري إيقاف البوت...")
                self.stop_event.set()
                self.running = False

                # إيقاف المهام الدورية
                tasks = []
                for task in [self.cleanup_task, self.health_check_task]:
                    if task and not task.done():
                        task.cancel()
                        tasks.append(task)

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                    logger.info("✅ تم إيقاف المهام الدورية")

                # إيقاف الخدمات أولاً
                try:
                    await asyncio.gather(
                        binance_service.close(),
                        rate_limiting_service.close(),
                        close_pool(),
                        return_exceptions=True
                    )
                    logger.info("✅ تم إيقاف الخدمات")
                except Exception as e:
                    logger.error(f"❌ خطأ في إيقاف الخدمات: {e}")

                # إيقاف البوت
                if self.app:
                    try:
                        # إيقاف المحدث أولاً
                        if self.app.updater:
                            await self.app.updater.stop()
                            logger.info("✅ تم إيقاف محدث البوت")

                        # ثم إيقاف التطبيق
                        await self.app.stop()
                        await self.app.shutdown()
                        logger.info("✅ تم إيقاف تطبيق البوت")
                    except Exception as e:
                        logger.error(f"❌ خطأ في إيقاف البوت: {e}")

                # إغلاق الجلسات والاتصالات
                try:
                    if self.session and not self.session.closed:
                        await self.session.close()
                        logger.info("✅ تم إغلاق جلسة HTTP")

                    if self.web_app:
                        await self.web_app.cleanup()
                        logger.info("✅ تم إيقاف تطبيق الويب")
                except Exception as e:
                    logger.error(f"❌ خطأ في إغلاق الجلسات: {e}")

                # تنظيف الملفات
                try:
                    if Path(self.pid_file).exists():
                        Path(self.pid_file).unlink()
                        logger.info("✅ تم تنظيف ملفات النظام")
                except Exception as e:
                    logger.error(f"❌ خطأ في تنظيف الملفات: {e}")

                logger.info("✅ تم إيقاف البوت بنجاح")

        except Exception as e:
            logger.error(f"❌ خطأ في إيقاف البوت: {e}")
            raise

    async def error_handler(self, update, context):
        """معالج الأخطاء العام"""
        try:
            logger.error(f"⚠️ خطأ في التحديث {update}: {context.error}")
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى."
                )
        except Exception as e:
            logger.error(f"❌ خطأ في معالج الأخطاء: {e}")

async def main():
    """الدالة الرئيسية"""
    # تحميل المتغيرات البيئية
    load_dotenv()
    
    if not TELEGRAM_TOKEN:
        logger.error("❌ لم يتم تعيين TELEGRAM_TOKEN")
        return

    # إنشاء وتشغيل البوت
    bot = BotApplication()
    try:
        success = await bot.start()
        if not success:
            return

        # انتظار إشارة الإيقاف
        while not bot.stop_event.is_set():
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("تم إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
    finally:
        await bot.stop()

if __name__ == '__main__':
    try:
        # تعيين سياسة الحلقة
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # تشغيل البوت
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("تم إيقاف البوت")
    except Exception as e:
        logger.error(f"❌ خطأ في تشغيل البوت: {e}")
        sys.exit(1)