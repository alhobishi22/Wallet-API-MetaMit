# services/withdrawal_manager.py

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Set
import asyncio
import logging
from enum import Enum

logger = logging.getLogger(__name__)

class LockStatus(Enum):
    """حالات القفل المختلفة"""
    LOCKED = "locked"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"

@dataclass
class TransactionLock:
    """فئة لتتبع حالة قفل المعاملة"""
    withdrawal_id: str
    admin_id: int
    admin_name: str
    start_time: float
    status: LockStatus
    attempts: int = 0
    last_update: float = 0
    tx_hash: Optional[str] = None
    error_message: Optional[str] = None
    processing_data: Optional[Dict] = None

class WithdrawalManager:
    """مدير عمليات السحب مع منع التكرار والتزامن"""
    
    def __init__(self):
        """تهيئة مدير السحب"""
        self._locks: Dict[str, TransactionLock] = {}
        self._lock = asyncio.Lock()
        self._processing: Set[str] = set()
        self.LOCK_TIMEOUT = 900  # 15 دقيقة
        self.MAX_ATTEMPTS = 3
        self.PROCESSING_TIMEOUT = 300  # 5 دقائق
        self._last_cleanup = datetime.now(timezone.utc).timestamp()
        # إضافة قاموس لتعقب عمليات التحديث للحالة لتجنب التكرار
        self._state_updates: Dict[str, Dict] = {}

    async def acquire_lock(self, withdrawal_id: str, admin_id: int, admin_name: str) -> bool:
        """
        محاولة الحصول على قفل للمعاملة
        
        Args:
            withdrawal_id: معرف عملية السحب
            admin_id: معرف المشرف
            admin_name: اسم المشرف
            
        Returns:
            bool: نجاح محاولة القفل
        """
        try:
            async with self._lock:
                current_time = datetime.now(timezone.utc).timestamp()
                
                # التحقق من وجود قفل حالي
                if withdrawal_id in self._locks:
                    lock = self._locks[withdrawal_id]
                    elapsed_time = current_time - lock.start_time
                    
                    # فحص حالة الطلب من قاعدة البيانات قبل القفل
                    from services.database_service import get_withdrawal
                    try:
                        withdrawal = await get_withdrawal(withdrawal_id)
                        if withdrawal and withdrawal.get('status') in ['completed', 'rejected']:
                            logger.warning(
                                f"⚠️ محاولة قفل طلب في حالة نهائية: {withdrawal_id} - "
                                f"الحالة الحالية: {withdrawal.get('status')}"
                            )
                            return False
                    except Exception as e:
                        logger.error(f"❌ خطأ في التحقق من حالة الطلب {withdrawal_id} قبل القفل: {str(e)}")
                    
                    logger.info(
                        f"🔒 محاولة قفل الطلب {withdrawal_id} بواسطة المشرف {admin_name} ({admin_id})"
                    )
                    
                    # إذا كان نفس المشرف يحاول القفل مرة أخرى خلال فترة قصيرة (أقل من 5 ثوانٍ)، نمنع محاولة القفل المتكررة
                    if lock.admin_id == admin_id and elapsed_time < 5:
                        logger.warning(f"⚠️ تجاهل محاولة قفل متكررة من نفس المشرف {admin_name} خلال فترة قصيرة")
                        return False
                    
                    logger.info(
                        f"ℹ️ الطلب {withdrawal_id} مقفل حالياً بواسطة "
                        f"{lock.admin_name} منذ {format_duration(elapsed_time)}"
                    )
                    
                    # التحقق من انتهاء صلاحية القفل
                    if elapsed_time > self.LOCK_TIMEOUT:
                        logger.warning(
                            f"⚠️ تم انتهاء صلاحية القفل للطلب {withdrawal_id} - "
                            f"مدة القفل: {format_duration(elapsed_time)}"
                        )
                        del self._locks[withdrawal_id]
                    else:
                        if lock.admin_id != admin_id:
                            logger.info(
                                f"❌ تم رفض محاولة القفل من المشرف {admin_name} - "
                                f"الطلب مقفل بواسطة {lock.admin_name}"
                            )
                        return False

                # فحص حالة الطلب من قاعدة البيانات قبل إنشاء قفل جديد
                from services.database_service import get_withdrawal
                try:
                    withdrawal = await get_withdrawal(withdrawal_id)
                    if withdrawal and withdrawal.get('status') in ['completed', 'rejected']:
                        logger.warning(
                            f"⚠️ محاولة قفل طلب في حالة نهائية: {withdrawal_id} - "
                            f"الحالة الحالية: {withdrawal.get('status')}"
                        )
                        return False
                except Exception as e:
                    logger.error(f"❌ خطأ في التحقق من حالة الطلب {withdrawal_id} قبل إنشاء قفل جديد: {str(e)}")

                # إنشاء قفل جديد
                self._locks[withdrawal_id] = TransactionLock(
                    withdrawal_id=withdrawal_id,
                    admin_id=admin_id,
                    admin_name=admin_name,
                    start_time=current_time,
                    status=LockStatus.LOCKED,
                    attempts=0,
                    last_update=current_time
                )
                
                logger.info(f"✅ تم قفل الطلب {withdrawal_id} بنجاح بواسطة {admin_name}")
                return True
                
        except Exception as e:
            logger.error(f"❌ خطأ في محاولة قفل الطلب {withdrawal_id}: {str(e)}")
            return False

    async def release_lock(self, withdrawal_id: str):
        """
        تحرير قفل المعاملة
        
        Args:
            withdrawal_id: معرف عملية السحب
        """
        async with self._lock:
            if withdrawal_id in self._locks:
                lock = self._locks[withdrawal_id]
                # التحقق من حالة الطلب قبل التحرير للسجلات
                from services.database_service import get_withdrawal
                current_status = "غير معروف"
                try:
                    withdrawal = await get_withdrawal(withdrawal_id)
                    if withdrawal:
                        current_status = withdrawal.get('status', 'غير معروف')
                except Exception as e:
                    logger.error(f"❌ خطأ في التحقق من حالة الطلب {withdrawal_id} قبل تحرير القفل: {str(e)}")
                
                logger.info(
                    f"🔓 تحرير قفل الطلب {withdrawal_id} "
                    f"(كان مقفلاً بواسطة {lock.admin_name}, الحالة الحالية: {current_status})"
                )
                del self._locks[withdrawal_id]
                logger.info(f"✅ تم تحرير القفل بنجاح للطلب {withdrawal_id}")
            else:
                # بدلاً من إصدار تحذير، فقط سجل وتجاهل
                logger.info(f"ℹ️ الطلب {withdrawal_id} غير مقفل، تجاهل محاولة التحرير")

    async def is_locked(self, withdrawal_id: str) -> bool:
        """
        التحقق مما إذا كان الطلب مقفلًا حاليًا
        
        Args:
            withdrawal_id: معرف عملية السحب
            
        Returns:
            bool: هل الطلب مقفل
        """
        async with self._lock:
            return withdrawal_id in self._locks

    async def update_lock_status(
        self, 
        withdrawal_id: str, 
        status: LockStatus, 
        error_message: Optional[str] = None,
        tx_hash: Optional[str] = None
    ):
        """
        تحديث حالة القفل
        
        Args:
            withdrawal_id: معرف عملية السحب
            status: الحالة الجديدة
            error_message: رسالة الخطأ (اختياري)
            tx_hash: معرف المعاملة (اختياري)
        """
        async with self._lock:
            # التحقق من آخر حالة تم تحديثها لتجنب التحديثات غير المنطقية
            last_state = self._state_updates.get(withdrawal_id, {}).get('status')
            
            # منع التحديثات غير المنطقية
            if last_state == LockStatus.COMPLETED and status == LockStatus.FAILED:
                logger.warning(f"⚠️ منع تحديث غير منطقي: {withdrawal_id} من COMPLETED إلى FAILED")
                return
                
            # تجنب التحديثات المتكررة لنفس الحالة
            if last_state == status:
                logger.info(f"ℹ️ تجاهل تحديث متكرر لنفس الحالة: {withdrawal_id} إلى {status.value}")
                return
                
            if withdrawal_id in self._locks:
                lock = self._locks[withdrawal_id]
                lock.status = status
                lock.last_update = datetime.now(timezone.utc).timestamp()
                
                if error_message:
                    lock.error_message = error_message
                if tx_hash:
                    lock.tx_hash = tx_hash
                    
                # تخزين آخر تحديث حالة
                self._state_updates[withdrawal_id] = {
                    'status': status,
                    'timestamp': datetime.now(timezone.utc).timestamp()
                }
                    
                logger.info(
                    f"📝 تم تحديث حالة الطلب {withdrawal_id} إلى {status.value}"
                )

    async def get_lock_info(self, withdrawal_id: str) -> Optional[TransactionLock]:
        """
        الحصول على معلومات القفل
        
        Args:
            withdrawal_id: معرف عملية السحب
            
        Returns:
            Optional[TransactionLock]: معلومات القفل أو None
        """
        async with self._lock:
            return self._locks.get(withdrawal_id)

    async def increment_attempts(self, withdrawal_id: str) -> int:
        """
        زيادة عداد محاولات التنفيذ
        
        Args:
            withdrawal_id: معرف عملية السحب
            
        Returns:
            int: عدد المحاولات الحالي
        """
        async with self._lock:
            if withdrawal_id in self._locks:
                self._locks[withdrawal_id].attempts += 1
                return self._locks[withdrawal_id].attempts
            return 0

    async def get_active_locks(self) -> dict:
        """
        الحصول على جميع الأقفال النشطة
        
        Returns:
            dict: قاموس يحتوي على معلومات الأقفال النشطة
        """
        async with self._lock:
            current_time = datetime.now(timezone.utc).timestamp()
            active_locks = {}
            
            for withdrawal_id, lock in self._locks.items():
                duration = current_time - lock.start_time
                active_locks[withdrawal_id] = {
                    'admin_name': lock.admin_name,
                    'admin_id': lock.admin_id,
                    'start_time': lock.start_time,
                    'duration': duration,
                    'duration_formatted': format_duration(duration),
                    'status': lock.status.value,
                    'attempts': lock.attempts
                }
            
            return active_locks

    async def cleanup_expired_locks(self):
        """تنظيف الأقفال منتهية الصلاحية"""
        async with self._lock:
            current_time = datetime.now(timezone.utc).timestamp()
            expired_count = 0
            
            for withdrawal_id in list(self._locks.keys()):
                lock = self._locks[withdrawal_id]
                duration = current_time - lock.start_time
                
                if duration > self.LOCK_TIMEOUT:
                    logger.warning(
                        f"⚠️ تنظيف قفل منتهي الصلاحية للطلب {withdrawal_id} - "
                        f"مقفل بواسطة {lock.admin_name} منذ {format_duration(duration)}"
                    )
                    del self._locks[withdrawal_id]
                    expired_count += 1
            
            if expired_count > 0:
                logger.info(f"🧹 تم تنظيف {expired_count} أقفال منتهية الصلاحية")

def format_duration(seconds: float) -> str:
    """
    تنسيق المدة الزمنية بشكل مقروء
    
    Args:
        seconds: عدد الثواني
        
    Returns:
        str: المدة الزمنية منسقة
    """
    if seconds < 60:
        return f"{int(seconds)} ثانية"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        seconds_remainder = int(seconds % 60)
        return f"{minutes} دقيقة و {seconds_remainder} ثانية"
    else:
        hours = int(seconds / 3600)
        minutes_remainder = int((seconds % 3600) / 60)
        return f"{hours} ساعة و {minutes_remainder} دقيقة"

# إنشاء نسخة عالمية من مدير السحب
withdrawal_manager = WithdrawalManager()