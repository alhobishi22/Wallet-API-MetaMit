"""
وحدة للتحكم في معدل الرسائل وتجنب مشاكل Flood Control
"""
import time
from collections import deque
from dataclasses import dataclass
from typing import Dict, Deque
import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

@dataclass
class RateLimit:
    """فئة لتتبع معدل الرسائل"""
    window_size: int  # حجم النافذة بالثواني
    max_requests: int  # الحد الأقصى للطلبات في النافذة
    requests: Deque[float]  # قائمة بأوقات الطلبات

    def __init__(self, window_size: int, max_requests: int):
        self.window_size = window_size
        self.max_requests = max_requests
        self.requests = deque()

    def can_proceed(self) -> tuple[bool, float]:
        """
        التحقق مما إذا كان يمكن إجراء طلب جديد
        Returns:
            tuple[bool, float]: (يمكن المتابعة، وقت الانتظار المطلوب)
        """
        now = time.time()
        
        # إزالة الطلبات القديمة
        while self.requests and now - self.requests[0] > self.window_size:
            self.requests.popleft()
        
        if len(self.requests) < self.max_requests:
            return True, 0
        
        # حساب وقت الانتظار المطلوب
        next_available = self.requests[0] + self.window_size
        wait_time = next_available - now
        return False, max(0, wait_time)

    def add_request(self):
        """تسجيل طلب جديد"""
        self.requests.append(time.time())

class RateLimiter:
    """مدير التحكم في معدل الرسائل"""
    def __init__(self):
        # معدلات مختلفة للعمليات المختلفة
        self.limits: Dict[str, RateLimit] = {
            'edit_message': RateLimit(5, 10),  # 10 تعديلات كل 5 ثوان
            'send_message': RateLimit(5, 10),  # 10 رسائل كل 5 ثوان
            'answer_callback': RateLimit(3, 15),  # 15 رد كل 3 ثوان
        }
        
        # تتبع آخر وقت تم فيه إرسال رد للمستخدم
        self.last_user_response: Dict[int, float] = {}
        
    async def acquire(self, operation: str) -> bool:
        """
        محاولة اكتساب إذن لإجراء عملية
        Args:
            operation: نوع العملية ('edit_message', 'send_message', 'answer_callback')
        Returns:
            bool: هل تم السماح بالعملية
        """
        if operation not in self.limits:
            return True
            
        rate_limit = self.limits[operation]
        can_proceed, wait_time = rate_limit.can_proceed()
        
        if not can_proceed:
            logger.warning(f"تجاوز معدل الطلبات لـ {operation}. انتظار {wait_time:.1f} ثوان")
            await asyncio.sleep(wait_time)
            return await self.acquire(operation)
            
        rate_limit.add_request()
        return True
        
    def can_respond_to_user(self, user_id: int, cooldown: float = 2.0) -> bool:
        """
        التحقق مما إذا كان يمكن الرد على المستخدم (تجنب الردود المتكررة)
        Args:
            user_id: معرف المستخدم
            cooldown: فترة الانتظار بين الردود (بالثواني)
        Returns:
            bool: هل يمكن الرد على المستخدم
        """
        now = time.time()
        last_response = self.last_user_response.get(user_id, 0)
        
        if now - last_response < cooldown:
            return False
            
        self.last_user_response[user_id] = now
        return True

# إنشاء نسخة عامة من مدير التحكم
rate_limiter = RateLimiter()
