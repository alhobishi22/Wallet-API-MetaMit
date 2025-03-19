import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

class RateLimitingService:
    def __init__(self):
        self.requests = defaultdict(list)
        self.initialized = False
        self.max_requests = 20  # الحد الأقصى للطلبات
        self.time_window = 60   # النافذة الزمنية بالثواني

    async def initialize(self):
        """تهيئة الخدمة"""
        if not self.initialized:
            logger.info("تم تهيئة خدمة تحديد المعدل.")
            self.initialized = True

    def _cleanup_old_requests(self, user_id: int):
        """تنظيف الطلبات القديمة"""
        current_time = datetime.now()
        self.requests[user_id] = [
            req_time for req_time in self.requests[user_id]
            if current_time - req_time < timedelta(seconds=self.time_window)
        ]

    async def check_rate_limit(self, user_id: int) -> bool:
        """التحقق من حد المعدل للمستخدم"""
        try:
            self._cleanup_old_requests(user_id)
            
            # إضافة الطلب الحالي
            current_time = datetime.now()
            self.requests[user_id].append(current_time)
            
            # التحقق من عدد الطلبات
            return len(self.requests[user_id]) <= self.max_requests

        except Exception as e:
            logger.error(f"خطأ في التحقق من حد المعدل: {e}")
            return True  # السماح بالطلب في حالة حدوث خطأ

    async def close(self):
        """إغلاق الخدمة"""
        self.requests.clear()
        self.initialized = False
        logger.info("تم إغلاق خدمة تحديد المعدل.")

# إنشاء نسخة واحدة من الخدمة
rate_limiting_service = RateLimitingService()
