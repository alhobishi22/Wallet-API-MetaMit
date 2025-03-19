import psutil
import logging
import asyncio
from datetime import datetime, timedelta
import os
from functools import partial

logger = logging.getLogger(__name__)

class MonitoringService:
    """خدمة مراقبة أداء النظام والتطبيق"""

    def __init__(self):
        self.start_time = datetime.now()
        self.process = psutil.Process()
        self.monitoring_interval = 5  # ثواني
        self._running = True
        self._last_warning_time = {}  # لتتبع وقت آخر تحذير
        self.warning_threshold = {
            'disk': 95,      # تحذير عند 95% استخدام
            'memory': 500,   # تحذير عند 500MB
            'cpu': 80       # تحذير عند 80%
        }
        self.warning_interval = 3600  # ساعة واحدة بين التحذيرات

    def get_uptime(self) -> timedelta:
        """الحصول على وقت تشغيل التطبيق"""
        return datetime.now() - self.start_time

    def get_memory_usage(self) -> float:
        """الحصول على استخدام الذاكرة بالميجابايت"""
        return self.process.memory_info().rss / 1024 / 1024

    def get_cpu_usage(self) -> float:
        """الحصول على نسبة استخدام المعالج"""
        return self.process.cpu_percent()

    def get_disk_usage(self) -> dict:
        """الحصول على معلومات استخدام القرص"""
        disk = psutil.disk_usage('/')
        return {
            'total': disk.total / (1024 * 1024 * 1024),  # GB
            'used': disk.used / (1024 * 1024 * 1024),    # GB
            'free': disk.free / (1024 * 1024 * 1024),    # GB
            'percent': disk.percent
        }

    def _should_send_warning(self, warning_type: str) -> bool:
        """التحقق مما إذا كان يجب إرسال تحذير"""
        current_time = datetime.now()
        last_warning = self._last_warning_time.get(warning_type)
        
        if last_warning is None or (current_time - last_warning).total_seconds() >= self.warning_interval:
            self._last_warning_time[warning_type] = current_time
            return True
        return False

    async def monitor_resources(self):
        """مراقبة موارد النظام بشكل مستمر"""
        while self._running:
            try:
                # استخدام run_in_executor لتنفيذ العمليات الثقيلة في thread منفصل
                loop = asyncio.get_event_loop()
                memory_usage = await loop.run_in_executor(None, self.get_memory_usage)
                cpu_usage = await loop.run_in_executor(None, self.get_cpu_usage)
                disk_usage = await loop.run_in_executor(None, self.get_disk_usage)
                uptime = self.get_uptime()

                # تسجيل معلومات النظام
                logger.info(
                    f"ℹ️ معلومات النظام - "
                    f"وقت التشغيل: {uptime}, "
                    f"الذاكرة: {memory_usage:.2f} MB, "
                    f"المعالج: {cpu_usage:.1f}%, "
                    f"القرص: {disk_usage['percent']}% مستخدم"
                )

                # التحقق من الموارد وإرسال تحذيرات عند الحاجة
                warnings = []

                if memory_usage > self.warning_threshold['memory'] and self._should_send_warning('memory'):
                    warnings.append(f"⚠️ استخدام الذاكرة مرتفع: {memory_usage:.1f} MB")
                    logger.warning(f"⚠️ استخدام الذاكرة مرتفع: {memory_usage:.2f} MB")

                if cpu_usage > self.warning_threshold['cpu'] and self._should_send_warning('cpu'):
                    warnings.append(f"⚠️ استخدام المعالج مرتفع: {cpu_usage:.1f}%")
                    logger.warning(f"⚠️ استخدام المعالج مرتفع: {cpu_usage:.1f}%")

                if disk_usage['percent'] > self.warning_threshold['disk'] and self._should_send_warning('disk'):
                    warnings.append(
                        f"⚠️ مساحة القرص منخفضة: {disk_usage['free']:.1f} GB متبقية\n"
                        f"({disk_usage['percent']}% مستخدم)"
                    )
                    logger.warning(f"⚠️ مساحة القرص منخفضة: {disk_usage['free']:.1f} GB متبقية")

                # إذا كان هناك تحذيرات، قم بإرسالها في رسالة واحدة
                if warnings:
                    warning_message = "🚨 تحذير حالة النظام:\n\n" + "\n\n".join(warnings)
                    # هنا يمكنك إضافة كود لإرسال التحذير للمشرفين
                    logger.warning(warning_message)

            except Exception as e:
                logger.error(f"❌ خطأ في مراقبة الموارد: {str(e)}")

            await asyncio.sleep(self.monitoring_interval)

    def stop_monitoring(self):
        """إيقاف المراقبة"""
        self._running = False

    def get_system_info(self) -> str:
        """الحصول على تقرير كامل عن حالة النظام"""
        try:
            memory = self.get_memory_usage()
            cpu = self.get_cpu_usage()
            disk = self.get_disk_usage()
            uptime = self.get_uptime()

            return (
                f"📊 تقرير حالة النظام:\n\n"
                f"⏱ وقت التشغيل: {uptime}\n"
                f"💾 استخدام الذاكرة: {memory:.2f} MB\n"
                f"🔄 استخدام المعالج: {cpu:.1f}%\n"
                f"💽 القرص:\n"
                f"  - المساحة الكلية: {disk['total']:.1f} GB\n"
                f"  - المستخدم: {disk['used']:.1f} GB ({disk['percent']}%)\n"
                f"  - المتبقي: {disk['free']:.1f} GB\n"
            )
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء تقرير النظام: {str(e)}")
            return "⚠️ حدث خطأ أثناء جمع معلومات النظام"

# إنشاء كائن monitoring_service
monitoring_service = MonitoringService()