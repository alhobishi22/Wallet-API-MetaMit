# services/database_service.py

import asyncpg
import logging
import os
import socket
import ssl
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple  # إضافة Tuple هنا

logger = logging.getLogger(__name__)

# تعريف المتغير العالمي للتجمع
pool: Optional[asyncpg.Pool] = None

async def get_all_users_with_codes():
    """
    استرجاع جميع المستخدمين مع أكواد التسجيل الخاصة بهم

    Returns:
        list: قائمة بمعلومات المستخدمين وأكوادهم
    """
    try:
        conn = await get_connection()
        rows = await conn.fetch("""
            SELECT 
                u.user_id,
                u.registration_date,
                rc.code,
                u.is_registered
            FROM users u
            LEFT JOIN registration_codes rc 
                ON u.user_id = rc.user_id 
                AND rc.is_used = TRUE
            ORDER BY u.registration_date DESC
        """)
        
        await release_connection(conn)
        return [dict(row) for row in rows]
        
    except Exception as e:
        logger.error(f"Error fetching users with codes: {e}")
        return []

async def create_pool():
    """إنشاء تجمع اتصالات بقاعدة البيانات"""
    global pool
    try:
        # إعداد SSL context
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # معلومات الاتصال
        connection_params = {
            'user': 'alhubaishi',
            'password': 'jAtNbIdExraRUo1ZosQ1f0EEGz3fMZWt',
            'database': 'meta_bit_database',
            'host': 'dpg-csserj9u0jms73ea9gmg-a.singapore-postgres.render.com',
            'port': 5432,
            'ssl': ssl_context
        }

        logger.info(f"جاري الاتصال بقاعدة البيانات... {connection_params['host']}")
        
        # محاولة إنشاء التجمع
        pool = await asyncpg.create_pool(
            **connection_params,
            min_size=1,
            max_size=10,
            command_timeout=60
        )
        
        # اختبار الاتصال
        if pool:
            async with pool.acquire() as connection:
                version = await connection.fetchval('SELECT version()')
                logger.info(f"✅ تم الاتصال بنجاح. إصدار PostgreSQL: {version}")
        
    except Exception as e:
        logger.error(f"❌ خطأ في إنشاء تجمع الاتصالات: {str(e)}")
        # إظهار معلومات إضافية للتصحيح
        try:
            ip = socket.gethostbyname(connection_params['host'])
            logger.info(f"IP address for {connection_params['host']}: {ip}")
        except Exception as dns_error:
            logger.error(f"❌ خطأ في حل اسم النطاق: {str(dns_error)}")
        raise

async def has_pending_request(user_id: int) -> bool:
    """التحقق من وجود طلبات معلقة للمستخدم"""
    try:
        conn = await get_connection()
        async with conn.transaction():
            # إلغاء الطلبات القديمة أولاً
            await conn.execute("""
                UPDATE withdrawal_requests 
                SET status = 'cancelled',
                    cancellation_reason = 'تم الإلغاء تلقائياً لانتهاء المهلة'
                WHERE user_id = $1 
                AND status IN ('pending', 'processing')
                AND created_at < NOW() - INTERVAL '15 minutes'
            """, user_id)

            # ثم التحقق من وجود طلبات حالية
            result = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 
                    FROM withdrawal_requests 
                    WHERE user_id = $1 
                    AND status IN ('pending', 'processing')
                    AND created_at > NOW() - INTERVAL '15 minutes'
                    AND withdrawal_id NOT IN (
                        SELECT withdrawal_id 
                        FROM withdrawal_requests 
                        WHERE status IN ('completed', 'cancelled', 'rejected')
                    )
                )
            """, user_id)

            # في حالة وجود طلب نشط جديد
            if result:
                # جلب معلومات الطلب لإضافتها للسجل
                active_request = await conn.fetchrow("""
                    SELECT withdrawal_id, created_at, status
                    FROM withdrawal_requests 
                    WHERE user_id = $1 
                    AND status IN ('pending', 'processing')
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, user_id)
                if active_request:
                    logger.info(
                        f"طلب نشط للمستخدم {user_id}: "
                        f"withdrawal_id={active_request['withdrawal_id']}, "
                        f"status={active_request['status']}, "
                        f"created_at={active_request['created_at']}"
                    )

        await release_connection(conn)
        return result

    except Exception as e:
        logger.error(f"خطأ في التحقق من الطلبات المعلقة للمستخدم {user_id}: {e}")
        if conn:
            await release_connection(conn)
        return False

async def clean_stuck_requests():
    """تنظيف الطلبات العالقة"""
    try:
        conn = await get_connection()
        await conn.execute("""
            UPDATE withdrawal_requests 
            SET status = 'cancelled',
                cancellation_reason = 'تم الإلغاء تلقائياً بسبب انتهاء المهلة'
            WHERE status IN ('pending', 'processing')
            AND created_at < NOW() - INTERVAL '1 hour'
        """)
        await release_connection(conn)
    except Exception as e:
        logger.error(f"خطأ في تنظيف الطلبات العالقة: {e}")

async def cancel_stale_requests():
    """إلغاء الطلبات المتأخرة/العالقة"""
    try:
        conn = await get_connection()
        cancelled = await conn.fetch("""
            WITH cancelled_requests AS (
                UPDATE withdrawal_requests 
                SET status = 'cancelled',
                    cancellation_reason = 'تم الإلغاء تلقائياً بسبب انتهاء المهلة'
                WHERE status IN ('pending', 'processing')
                AND created_at < NOW() - INTERVAL '1 hour'
                RETURNING user_id, withdrawal_id
            )
            SELECT user_id, withdrawal_id FROM cancelled_requests
        """)
        await release_connection(conn)
        return cancelled
    except Exception as e:
        logger.error(f"خطأ في إلغاء الطلبات العالقة: {e}")
        return []

async def get_connection() -> asyncpg.Connection:
    """الحصول على اتصال من التجمع"""
    global pool
    if not pool:
        await create_pool()
    return await pool.acquire()

async def release_connection(conn: asyncpg.Connection):
    """إعادة الاتصال إلى التجمع"""
    global pool
    if pool and conn:
        await pool.release(conn)

async def close_pool():
    """إغلاق تجمع الاتصالات"""
    global pool
    if pool:
        await pool.close()
        pool = None

async def initialize_database():
    """تهيئة قاعدة البيانات وإنشاء الجداول اللازمة"""
    try:
        # إنشاء جدول إجراءات المشرفين
        await create_admin_actions_table()
        logger.info("تم تهيئة قاعدة البيانات بنجاح")
    except Exception as e:
        logger.error(f"خطأ في تهيئة قاعدة البيانات: {e}")
        raise
    conn = None
    try:
        conn = await get_connection()
        
        # إنشاء جدول المستخدمين
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                registration_code VARCHAR(50),
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # إنشاء جدول طلبات السحب
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS withdrawal_requests (
                withdrawal_id VARCHAR(50) PRIMARY KEY,
                user_id BIGINT REFERENCES users(user_id),
                status VARCHAR(20),
                crypto_currency VARCHAR(10),
                network_code VARCHAR(20),
                network_name VARCHAR(50),
                local_currency VARCHAR(10),
                local_currency_name VARCHAR(50),
                local_amount DECIMAL(20, 8),
                wallet_address TEXT,
                transfer_number VARCHAR(100),
                transfer_issuer VARCHAR(100),
                cancellation_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                executed_by BIGINT,
                failed_by BIGINT,
                processing_start TIMESTAMP,
                completion_time TIMESTAMP,
                tx_hash VARCHAR(100),
                failure_time TIMESTAMP
            )
        """)
        
        # إنشاء جدول الإعدادات
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(50) PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # إنشاء جدول أسعار الصرف
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS exchange_rates (
                currency_code VARCHAR(10) PRIMARY KEY,
                rate DECIMAL(20, 8),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")
        
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {str(e)}")
        raise
    finally:
        if conn:
            await release_connection(conn)

async def init_db():
    """
    تهيئة قاعدة البيانات وإضافة الجداول الأساسية
    """
    await initialize_database()

async def add_user(user_id: int):
    """
    إضافة مستخدم جديد إلى قاعدة البيانات.
    """
    try:
        conn = await get_connection()
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO users (user_id)
                VALUES ($1)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)
        logger.info(f"✅ تم إضافة المستخدم {user_id} إلى قاعدة البيانات.")
        await release_connection(conn)
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة المستخدم {user_id}: {e}")
        raise

async def is_user_registered(user_id: int) -> bool:
    """
    التحقق مما إذا كان المستخدم مسجلاً وله كود تسجيل صالح
    """
    try:
        conn = await get_connection()
        result = await conn.fetchval("""
            SELECT EXISTS(
                SELECT 1 
                FROM users u
                JOIN registration_codes rc ON u.user_id = rc.user_id
                WHERE u.user_id = $1 
                AND u.is_registered = TRUE
                AND rc.is_used = TRUE
            )
        """, user_id)
        
        await release_connection(conn)
        
        if not result:
            # إذا لم يكن المستخدم مسجلاً بشكل صحيح، نقوم بإلغاء تفعيله
            await deactivate_user(user_id)
        
        return bool(result)
        
    except Exception as e:
        logger.error(f"خطأ في التحقق من تسجيل المستخدم {user_id}: {e}")
        return False

async def verify_registration_code(user_id: int, code: str) -> bool:
    """
    التحقق من صحة رمز التسجيل وتفعيل المستخدم.
    يدعم الأكواد التي تحتوي على مسافات مثل الأسماء الكاملة.
    """
    try:
        conn = await get_connection()
        async with conn.transaction():
            # التحقق من وجود الكود وأنه غير مستخدم
            # نقوم بإزالة المسافات الزائدة من بداية ونهاية الكود مع الحفاظ على المسافات الداخلية
            formatted_code = code.strip()
            
            code_row = await conn.fetchrow("""
                SELECT * FROM registration_codes 
                WHERE LOWER(code) = LOWER($1) AND is_used = FALSE
            """, formatted_code)
            
            if not code_row:
                await release_connection(conn)
                return False

            # تحديث حالة المستخدم وتسجيل تاريخ التسجيل
            await conn.execute("""
                UPDATE users 
                SET is_registered = TRUE,
                    registration_date = $1
                WHERE user_id = $2
            """, datetime.utcnow(), user_id)

            # تحديث حالة الكود
            await conn.execute("""
                UPDATE registration_codes 
                SET is_used = TRUE,
                    user_id = $1
                WHERE LOWER(code) = LOWER($2)
            """, user_id, formatted_code)
            
        await release_connection(conn)
        return True
        
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من رمز التسجيل '{code}' للمستخدم {user_id}: {e}")
        return False

async def generate_registration_code(user_id: int) -> str:
    """
    توليد رمز تسجيل جديد للمستخدم.
    """
    import uuid
    code = str(uuid.uuid4()).split('-')[0]
    try:
        conn = await get_connection()
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO registration_codes (code, is_used)
                VALUES ($1, FALSE)
            """, code)
        await release_connection(conn)
        logger.info(f"✅ تم توليد رمز التسجيل {code} للمستخدم {user_id}")
        return code
    except Exception as e:
        logger.error(f"❌ خطأ في توليد رمز التسجيل للمستخدم {user_id}: {e}")
        return ""

def validate_number(value: str) -> bool:
    """التحقق من صحة القيمة العددية"""
    try:
        float_value = float(value)
        return float_value >= 0
    except ValueError:
        return False

def validate_setting_value(key: str, value: str) -> bool:
    """
    التحقق من صحة قيمة الإعداد
    """
    try:
        if key in ['MIN_WITHDRAWAL_USD', 'MAX_WITHDRAWAL_USD']:
            # التحقق من أن القيمة رقم موجب
            float_value = float(value)
            return float_value >= 0
        elif key == 'PERCENTAGE_COMMISSION_RATE':
            # التحقق من أن النسبة بين 0 و 1
            float_value = float(value)
            return 0 <= float_value <= 1
        return True
    except ValueError:
        return False  

async def update_max_withdrawal(value: str) -> bool:
    """تحديث الحد الأقصى للسحب"""
    if not validate_number(value):
        logger.error(f"❌ قيمة غير صالحة للحد الأقصى للسحب: {value}")
        return False
        
    await set_setting('MAX_WITHDRAWAL_USD', value)
    logger.info(f"✅ تم تحديث الحد الأقصى للسحب إلى {value}")
    return True

async def update_min_withdrawal(value: str) -> bool:
    """تحديث الحد الأدنى للسحب"""
    if not validate_number(value):
        logger.error(f"❌ قيمة غير صالحة للحد الأدنى للسحب: {value}")
        return False
        
    await set_setting('MIN_WITHDRAWAL_USD', value)
    logger.info(f"✅ تم تحديث الحد الأدنى للسحب إلى {value}")
    return True

async def update_commission_rate(value: str) -> bool:
    """تحديث نسبة العمولة"""
    try:
        float_value = float(value)
        if not 0 <= float_value <= 1:
            logger.error(f"❌ نسبة العمولة يجب أن تكون بين 0 و 1: {value}")
            return False
                
        await set_setting('PERCENTAGE_COMMISSION_RATE', str(float_value))
        logger.info(f"✅ تم تحديث نسبة العمولة إلى {float_value}")
        return True
    except ValueError:
        logger.error(f"❌ قيمة غير صالحة لنسبة العمولة: {value}")
        return False     

async def validate_registration_code(code: str) -> bool:
    """
    التحقق من صحة رمز التسجيل.
    """
    try:
        conn = await get_connection()
        row = await conn.fetchrow("""
            SELECT is_used FROM registration_codes WHERE code = $1
        """, code)
        is_valid = bool(row and not row['is_used'])
        await release_connection(conn)
        return is_valid
    except Exception as e:
        logger.error(f"❌ خطأ في التحقق من رمز التسجيل '{code}': {e}")
        return False

async def register_user(user_id: int, code: str):
    """
    تسجيل المستخدم وتحديث حالة رمز التسجيل.
    """
    try:
        conn = await get_connection()
        async with conn.transaction():
            row = await conn.fetchrow("SELECT is_used FROM registration_codes WHERE code = $1", code)
            if row and not row['is_used']:
                # تحديث حالة المستخدم
                await conn.execute("""
                    UPDATE users
                    SET is_registered = TRUE, registration_date = $1
                    WHERE user_id = $2
                """, datetime.utcnow(), user_id)
                
                # تحديث حالة الرمز
                await conn.execute("""
                    UPDATE registration_codes
                    SET is_used = TRUE, user_id = $1
                    WHERE code = $2
                """, user_id, code)
                
                logger.info(f"✅ تم تسجيل المستخدم {user_id} باستخدام رمز التسجيل '{code}'")
            else:
                logger.warning(f"⚠️ رمز التسجيل '{code}' غير صالح أو مستخدم للمستخدم {user_id}")
                raise ValueError("رمز التسجيل غير صالح أو مستخدم")
        await release_connection(conn)
    except Exception as e:
        logger.error(f"❌ خطأ في تسجيل المستخدم {user_id} باستخدام رمز التسجيل '{code}': {e}")
        raise

async def add_registration_code(code: str):
    """
    إضافة رمز تسجيل جديد مع دعم جميع أنواع علامات الاقتباس
    """
    try:
        # نفس منطق معالجة علامات الاقتباس
        quotes = ['"', "'", '«', '»']
        cleaned_code = code.strip()
        
        while any(cleaned_code.startswith(q) for q in quotes) and any(cleaned_code.endswith(q) for q in quotes):
            for quote in quotes:
                if cleaned_code.startswith(quote) and cleaned_code.endswith(quote):
                    cleaned_code = cleaned_code[len(quote):-len(quote)].strip()
                    break
        
        if not cleaned_code:
            raise ValueError("❌ الكود فارغ")
            
        if len(cleaned_code) < 2:
            raise ValueError("❌ الكود قصير جداً")

        logger.info(f"محاولة إضافة الكود: '{cleaned_code}'")
        
        conn = await get_connection()
        async with conn.transaction():
            # التحقق من وجود الكود
            existing_code = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM registration_codes 
                    WHERE code = $1
                )
            """, cleaned_code)

            if existing_code:
                raise ValueError(f"❌ الكود '{cleaned_code}' موجود مسبقاً")

            # إضافة الكود
            await conn.execute("""
                INSERT INTO registration_codes (code, is_used)
                VALUES ($1, FALSE)
            """, cleaned_code)
            
            logger.info(f"✅ تمت إضافة الكود '{cleaned_code}' بنجاح")
            return True
            
    except Exception as e:
        logger.error(f"خطأ في إضافة الكود: {e}")
        raise
    finally:
        if 'conn' in locals():
            await release_connection(conn)

async def delete_registration_code(code: str) -> Tuple[bool, str]:
    """
    حذف كود تسجيل من قاعدة البيانات مع دعم جميع أنواع علامات الاقتباس
    """
    try:
        # تنظيف النص من علامات الاقتباس الخارجية فقط
        quotes = ['"', "'", '«', '»']
        cleaned_code = code.strip()
        
        # إزالة علامات الاقتباس من البداية والنهاية إذا كانت موجودة
        if cleaned_code and cleaned_code[0] in quotes and cleaned_code[-1] in quotes:
            cleaned_code = cleaned_code[1:-1].strip()
        
        logger.info(f"محاولة حذف الكود بعد التنظيف: '{cleaned_code}'")
        
        conn = await get_connection()
        async with conn.transaction():
            # التحقق من وجود الكود
            code_data = await conn.fetchrow("""
                SELECT is_used, user_id 
                FROM registration_codes 
                WHERE code = $1
            """, cleaned_code)
            
            if not code_data:
                logger.info(f"لم يتم العثور على الكود: '{cleaned_code}'")
                return False, f"❌ الكود '{cleaned_code}' غير موجود"
            
            # حذف الكود
            await conn.execute("""
                DELETE FROM registration_codes 
                WHERE code = $1
            """, cleaned_code)
            
            msg = f"✅ تم حذف الكود '{cleaned_code}' بنجاح"
            if code_data['is_used']:
                msg += f"\n👤 كان مستخدماً من قبل المستخدم {code_data['user_id']}"
    
            logger.info(msg)
            return True, msg

    except Exception as e:
        logger.error(f"خطأ في حذف الكود: {e}")
        return False, f"❌ حدث خطأ: {str(e)}"
    finally:
        if 'conn' in locals():
            await release_connection(conn)

async def get_user_registration_code(user_id: int) -> str:
    """
    استرجاع رمز التسجيل الخاص بالمستخدم.
    يتحقق أيضاً من أن الكود مازال صالحاً وموجوداً في قاعدة البيانات.
    """
    try:
        conn = await get_connection()
        
        # التحقق من أن المستخدم مسجل وله كود صالح
        row = await conn.fetchrow("""
            SELECT rc.code 
            FROM registration_codes rc
            JOIN users u ON u.user_id = rc.user_id
            WHERE rc.user_id = $1 
            AND rc.is_used = TRUE
            AND u.is_registered = TRUE
        """, user_id)
        
        await release_connection(conn)
        
        if not row:
            # إذا لم يتم العثور على كود صالح، نقوم بإلغاء تسجيل المستخدم
            await deactivate_user(user_id)
            return None
            
        return row['code']
    except Exception as e:
        logger.error(f"❌ خطأ في استرجاع رمز التسجيل للمستخدم {user_id}: {e}")
        return None

async def deactivate_user(user_id: int):
    """
    إلغاء تفعيل المستخدم عندما لا يكون له كود تسجيل صالح
    """
    try:
        conn = await get_connection()
        async with conn.transaction():
            # تحديث حالة المستخدم
            await conn.execute("""
                UPDATE users 
                SET is_registered = FALSE 
                WHERE user_id = $1
            """, user_id)
            
            # إلغاء ربط أي أكواد تسجيل سابقة
            await conn.execute("""
                UPDATE registration_codes 
                SET is_used = FALSE, user_id = NULL 
                WHERE user_id = $1
            """, user_id)
            
        await release_connection(conn)
        logger.info(f"تم إلغاء تفعيل المستخدم {user_id}")
    except Exception as e:
        logger.error(f"خطأ في إلغاء تفعيل المستخدم {user_id}: {e}")
        raise

async def update_code_column_length():
    """تحديث طول عمود الكود في قاعدة البيانات"""
    try:
        conn = await get_connection()
        async with conn.transaction():
            await conn.execute("""
                ALTER TABLE registration_codes 
                ALTER COLUMN code TYPE VARCHAR(100)
            """)
        await release_connection(conn)
        logger.info("✅ تم تحديث طول عمود الكود بنجاح.")
    except Exception as e:
        logger.error(f"❌ خطأ في تحديث طول عمود الكود: {e}")
        raise

async def save_withdrawal(withdrawal_id: str, withdrawal_data: dict, retry_count: int = 0) -> bool:
    """حفظ طلب سحب جديد في قاعدة البيانات"""
    # إضافة عمود transfer_type إذا لم يكن موجوداً
    try:
        conn = await get_connection()
        async with conn.transaction():
            # التحقق من وجود العمود
            result = await conn.fetchrow("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public' 
                AND table_name = 'withdrawal_requests' 
                AND column_name = 'transfer_type'
            """)
            if not result:
                await conn.execute("""
                    ALTER TABLE withdrawal_requests 
                    ADD COLUMN transfer_type VARCHAR(50) DEFAULT 'name_transfer'
                """)
                logger.info("✅ تمت إضافة عمود transfer_type بنجاح.")
        await release_connection(conn)
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة عمود transfer_type: {e}")
        # نتابع التنفيذ حتى لو فشلت إضافة العمود
    """حفظ طلب السحب في قاعدة البيانات مع معالجة حالات التكرار
    
    Args:
        withdrawal_id: معرف الطلب
        withdrawal_data: بيانات الطلب
        retry_count: عدد محاولات إعادة المحاولة في حالة تكرار المعرف

    Returns:
        bool: True إذا نجحت العملية، False إذا فشلت
    """
    conn = None
    try:
        # التحقق من عدد المحاولات
        if retry_count >= 3:
            logger.error(f"❌ تجاوز الحد الأقصى لمحاولات حفظ الطلب {withdrawal_id}")
            return False

        # الحصول على اتصال بقاعدة البيانات
        conn = await get_connection()

        # التحقق من وجود طلب بنفس المعرف
        existing = await conn.fetchval("""
            SELECT withdrawal_id FROM withdrawal_requests 
            WHERE withdrawal_id = $1
        """, withdrawal_id)
        
        if existing:
            # إنشاء معرف جديد وإعادة المحاولة
            new_id = str(uuid.uuid4())
            logger.warning(f"⚠️ معرف الطلب {withdrawal_id} موجود بالفعل. محاولة مع معرف جديد {new_id}")
            return await save_withdrawal(new_id, withdrawal_data, retry_count + 1)

        # إدخال البيانات في قاعدة البيانات
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO withdrawal_requests (
                    withdrawal_id, user_id, crypto_currency, local_currency,
                    local_currency_name, local_amount, network_code, network_name,
                    crypto_amount, transfer_number, transfer_issuer, sender_name,
                    phone, wallet_address, net_amount, transfer_type
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            """,
            withdrawal_id,
            withdrawal_data['user_id'],
            withdrawal_data['crypto_currency'],
            withdrawal_data['local_currency'],
            withdrawal_data['local_currency_name'],
            withdrawal_data['local_amount'],
            withdrawal_data['network_code'],
            withdrawal_data['network_name'],
            withdrawal_data['crypto_amount'],
            withdrawal_data['transfer_number'],
            withdrawal_data['transfer_issuer'],
            withdrawal_data.get('sender_name', 'غير متوفر'),
            withdrawal_data.get('phone', 'غير متوفر'),
            withdrawal_data['wallet_address'],
            withdrawal_data['net_amount'],
            withdrawal_data.get('transfer_type', 'name_transfer')  # نوع التحويل الافتراضي هو التحويل عبر الاسم
            )
                
            logger.info(f"✅ تم حفظ عملية السحب {withdrawal_id} بنجاح")
            return True

    except asyncpg.UniqueViolationError:
        # في حالة حدوث تكرار في المعرف (حالة نادرة ولكن ممكنة)
        new_id = str(uuid.uuid4())
        logger.warning(f"⚠️ تكرار في معرف الطلب {withdrawal_id}. محاولة مع معرف جديد {new_id}")
        return await save_withdrawal(new_id, withdrawal_data, retry_count + 1)

    except Exception as e:
        logger.error(f"❌ خطأ في حفظ عملية السحب {withdrawal_id}: {str(e)}")
        logger.debug("بيانات السحب:", withdrawal_data)
        return False

    finally:
        # التأكد من إغلاق الاتصال في جميع الحالات
        if conn:
            await release_connection(conn)

def validate_withdrawal_data(withdrawal_data: dict) -> bool:
    """التحقق من اكتمال بيانات السحب"""
    required_fields = [
        'user_id',
        'crypto_currency',
        'local_currency',
        'local_currency_name',
        'local_amount',
        'network_code',
        'network_name',
        'crypto_amount',
        'transfer_number',
        'transfer_issuer',
        'wallet_address',
        'net_amount'
    ]
    
    # التحقق من وجود جميع الحقول المطلوبة
    for field in required_fields:
        if field not in withdrawal_data:
            logger.error(f"❌ الحقل المفقود: {field}")
            return False
            
    # التحقق من أن القيم ليست None
    for field in required_fields:
        if withdrawal_data[field] is None:
            logger.error(f"❌ قيمة {field} لا يمكن أن تكون None")
            return False
            
    return True

async def get_withdrawal(withdrawal_id: str) -> Optional[dict]:
    """
    استرجاع بيانات السحب.
    """
    try:
        conn = await get_connection()
        row = await conn.fetchrow("""
            SELECT * FROM withdrawal_requests WHERE withdrawal_id = $1
        """, withdrawal_id)
        result = dict(row) if row else None
        await release_connection(conn)
        return result
    except Exception as e:
        logger.error(f"❌ خطأ في استرجاع عملية السحب {withdrawal_id}: {e}")
        return None

async def update_withdrawal_status(
    withdrawal_id: str, 
    status: str, 
    reason: str = None, 
    executed_by: int = None, 
    failed_by: int = None, 
    processing_start: datetime = None,
    completion_time: datetime = None,
    tx_hash: str = None,
    failure_time: datetime = None
):
    """
    تحديث حالة السحب وسبب الإلغاء إن وجد
    
    Args:
        withdrawal_id (str): معرف السحب
        status (str): الحالة الجديدة (pending, completed, rejected, cancelled)
        reason (str, optional): سبب الإلغاء أو الرفض
        executed_by (int, optional): معرف المستخدم الذي نفذ العملية
        failed_by (int, optional): معرف المستخدم الذي رفض العملية
        processing_start (datetime, optional): وقت بدء المعالجة
        completion_time (datetime, optional): وقت اكتمال العملية
        tx_hash (str, optional): معرف المعاملة
        failure_time (datetime, optional): وقت الفشل
        
    Returns:
        bool: تم التحديث بنجاح أم لا
    """
    conn = None
    try:
        conn = await get_connection()
        
        def to_utc_naive(dt: datetime) -> datetime:
            """تحويل datetime إلى UTC وإزالة معلومات المنطقة الزمنية"""
            if dt is None:
                return None
            # إذا كان يحتوي على معلومات المنطقة الزمنية، نحوله إلى UTC
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            # إزالة معلومات المنطقة الزمنية
            return dt.replace(tzinfo=None)
        
        # تحويل جميع التواريخ إلى UTC naive
        processing_start = to_utc_naive(processing_start)
        completion_time = to_utc_naive(completion_time)
        failure_time = to_utc_naive(failure_time)
            
        # التحقق من الحالة الحالية قبل التحديث لمنع التحديثات غير المنطقية
        current_status = None
        async with conn.transaction():
            # استعلام عن الحالة الحالية
            current_status_row = await conn.fetchrow(
                "SELECT status FROM withdrawal_requests WHERE withdrawal_id = $1",
                withdrawal_id
            )
            
            if current_status_row:
                current_status = current_status_row['status']
                
                # منع التحديث من completed إلى failed
                if current_status == 'completed' and status == 'failed':
                    logger.warning(
                        f"⚠️ منع تحديث غير منطقي للطلب {withdrawal_id}: "
                        f"من {current_status} إلى {status}"
                    )
                    await release_connection(conn)
                    return False
                
                # منع التحديث من completed إلى rejected أو أي حالة غير منطقية أخرى
                if current_status == 'completed' and status in ['rejected', 'processing', 'pending']:
                    logger.warning(
                        f"⚠️ منع تحديث غير منطقي للطلب {withdrawal_id}: "
                        f"من {current_status} إلى {status}"
                    )
                    await release_connection(conn)
                    return False
                
                # تجنب التحديثات المتكررة لنفس الحالة
                if current_status == status:
                    logger.info(
                        f"ℹ️ تجاهل تحديث متكرر للطلب {withdrawal_id}: "
                        f"الحالة هي بالفعل {status}"
                    )
                    await release_connection(conn)
                    return True  # نعتبر هذا نجاحًا لأن الحالة هي المطلوبة بالفعل
                
                # استمر في التحديث فقط إذا كان التغيير منطقيًا
                if reason:
                    await conn.execute("""
                        UPDATE withdrawal_requests 
                        SET status = $1, cancellation_reason = $2,
                            executed_by = $4, failed_by = $5,
                            processing_start = $6, completion_time = $7,
                            tx_hash = $8, failure_time = $9,
                            updated_at = NOW()
                        WHERE withdrawal_id = $3
                    """, status, reason, withdrawal_id, executed_by, failed_by, 
                        processing_start, completion_time, tx_hash, failure_time)
                else:
                    await conn.execute("""
                        UPDATE withdrawal_requests 
                        SET status = $1,
                            executed_by = $3, failed_by = $4,
                            processing_start = $5, completion_time = $6,
                            tx_hash = $7, failure_time = $8,
                            updated_at = NOW()
                        WHERE withdrawal_id = $2
                    """, status, withdrawal_id, executed_by, failed_by,
                        processing_start, completion_time, tx_hash, failure_time)
                    
        logger.info(f"✅ تم تحديث حالة السحب {withdrawal_id} إلى {status}" + 
                  (f" (كانت {current_status})" if current_status else ""))
        
        # إطلاق الاتصال
        await release_connection(conn)
        return True  # تم التحديث بنجاح
        
    except Exception as e:
        logger.error(f"❌ خطأ في تحديث حالة السحب {withdrawal_id}: {str(e)}")
        # التأكد من إطلاق الاتصال في حالة الخطأ
        if conn:
            await release_connection(conn)
        return False  # فشل التحديث

async def get_setting(setting_key: str) -> Optional[str]:
    """
    استرجاع قيمة إعداد من قاعدة البيانات
    """
    try:
        conn = await get_connection()
        row = await conn.fetchrow("""
            SELECT setting_value FROM bot_settings WHERE setting_key = $1
        """, setting_key)
        
        await release_connection(conn)
        return row['setting_value'] if row else None
        
    except Exception as e:
        logger.error(f"❌ خطأ في استرجاع الإعداد '{setting_key}': {str(e)}")
        return None

async def set_setting(setting_key: str, setting_value: str):
    """
    تحديث أو إضافة إعداد في قاعدة البيانات
    """
    try:
        conn = await get_connection()
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO bot_settings (setting_key, setting_value)
                VALUES ($1, $2)
                ON CONFLICT (setting_key) 
                DO UPDATE SET setting_value = EXCLUDED.setting_value
            """, setting_key, str(setting_value))
            logger.info(f"✅ تم تحديث الإعداد '{setting_key}' إلى '{setting_value}'")
        
        # إطلاق الاتصال بعد انتهاء المعاملة
        await release_connection(conn)
        return True
            
    except Exception as e:
        logger.error(f"❌ خطأ في تحديث الإعداد '{setting_key}': {str(e)}")
        # محاولة إطلاق الاتصال في حالة الخطأ
        if conn:
            await release_connection(conn)
        raise

async def get_exchange_rates():
    """استرجاع أسعار الصرف من قاعدة البيانات"""
    try:
        conn = await get_connection()
        rates = await conn.fetch("""
            SELECT currency_code, rate, updated_at
            FROM exchange_rates
            ORDER BY currency_code
        """)
        await release_connection(conn)
        rate_dict = {row['currency_code']: float(row['rate']) for row in rates}
        
        # التأكد من أن USDT موجودة، إذا لم تكن موجودة، تعيين سعر صرفها إلى 1.0
        if 'USDT' not in rate_dict:
            rate_dict['USDT'] = 1.0
            logger.warning("سعر الصرف لـ USDT غير موجود. تم تعيينه إلى 1.0 تلقائياً.")
        
        return rate_dict
    except Exception as e:
        logger.error(f"خطأ في استرجاع أسعار الصرف: {e}")
        return {}

async def update_exchange_rate(currency_code: str, rate: str):
    """تحديث سعر صرف عملة معينة"""
    try:
        # معالجة مدخلات مختلفة مثل "USD=1" أو "USD 1"
        if '=' in currency_code:
            currency_code, rate = currency_code.split('=')
        
        currency_code = currency_code.strip().upper()
        rate = float(rate)
        
        conn = await get_connection()
        await conn.execute("""
            INSERT INTO exchange_rates (currency_code, rate)
            VALUES ($1, $2)
            ON CONFLICT (currency_code) 
            DO UPDATE SET rate = EXCLUDED.rate
        """, currency_code, rate)
        await release_connection(conn)
        return True
    except Exception as e:
        logger.error(f"خطأ في تحديث سعر الصرف: {e}")
        return False

async def delete_exchange_rate(currency_code: str):
    """حذف عملة من جدول أسعار الصرف"""
    try:
        conn = await get_connection()
        await conn.execute("""
            DELETE FROM exchange_rates
            WHERE currency_code = $1
        """, currency_code.upper())
        await release_connection(conn)
        return True
    except Exception as e:
        logger.error(f"خطأ في حذف سعر الصرف: {e}")
        return False

async def get_active_withdrawals():
    """
    استرجاع جميع عمليات السحب النشطة (pending)
    """
    try:
        conn = await get_connection()
        rows = await conn.fetch("""
            SELECT 
                withdrawal_id,
                user_id,
                crypto_currency,
                status,
                network_code,
                wallet_address,
                local_amount as net_amount
            FROM withdrawal_requests 
            WHERE status = 'pending'
            ORDER BY created_at DESC
        """)
        
        # تحويل النتائج إلى قائمة من القواميس
        withdrawals = [dict(row) for row in rows]
        
        await release_connection(conn)
        logger.debug(f"تم استرجاع {len(withdrawals)} عملية سحب نشطة")
        return withdrawals
        
    except Exception as e:
        logger.error(f"خطأ في استرجاع عمليات السحب النشطة: {str(e)}")
        return []

async def initialize_settings():
    """
    تهيئة الإعدادات الأولية.
    """
    try:
        conn = await get_connection()
        async with conn.transaction():
            settings = {
                'MIN_WITHDRAWAL_USD': '11.0',
                'MAX_WITHDRAWAL_USD': '3000.0',
                'COMMISSION_THRESHOLD_USD': '30.0',  # الحد الفاصل للعمولة
                'FIXED_COMMISSION_USD': '1.0',      # العمولة الثابتة للمبالغ الصغيرة
                'PERCENTAGE_COMMISSION_RATE': '0.03', # نسبة العمولة للمبالغ الكبيرة
                # إضافة إعدادات BEP20
                'BEP20_MIN_WITHDRAWAL_USD': '20.0',  # الحد الأدنى الافتراضي لـ BEP20
                'BEP20_MAX_WITHDRAWAL_USD': '5000.0'  # الحد الأقصى الافتراضي لـ BEP20
            }
            for key, value in settings.items():
                await conn.execute("""
                    INSERT INTO settings (key, value)
                    VALUES ($1, $2)
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value
                    WHERE settings.value IS NULL  -- يحافظ على القيم الموجودة               
                """, key, value)
        logger.info("✅ تم تهيئة الإعدادات بنجاح.")
        await release_connection(conn)
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة الإعدادات: {e}")
        raise

async def get_bep20_limits() -> tuple:
    """
    الحصول على حدود BEP20 الحالية
    Returns:
        tuple: (min_limit, max_limit)
    """
    try:
        min_limit = float(await get_setting('BEP20_MIN_WITHDRAWAL_USD') or 20.0)
        max_limit = float(await get_setting('BEP20_MAX_WITHDRAWAL_USD') or 5000.0)
        return min_limit, max_limit
    except Exception as e:
        logger.error(f"خطأ في الحصول على حدود BEP20: {e}")
        return 20.0, 5000.0  # القيم الافتراضية

async def update_bep20_limits(min_value: float = None, max_value: float = None) -> bool:
    """
    تحديث حدود BEP20
    """
    try:
        if min_value is not None:
            await set_setting('BEP20_MIN_WITHDRAWAL_USD', str(min_value))
        if max_value is not None:
            await set_setting('BEP20_MAX_WITHDRAWAL_USD', str(max_value))
        return True
    except Exception as e:
        logger.error(f"خطأ في تحديث حدود BEP20: {e}")
        return False
async def create_admin_actions_table():
    """إنشاء جدول إجراءات المشرفين"""
    conn = await get_connection()
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_actions (
            withdrawal_id TEXT PRIMARY KEY,
            admin_id BIGINT,
            action_type TEXT,
            message_id BIGINT,
            chat_id BIGINT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    finally:
        await release_connection(conn)
async def store_admin_action(withdrawal_id, admin_id, action_type, message_id, chat_id):
    """تخزين إجراء المشرف في قاعدة البيانات"""
    conn = await get_connection()
    try:
        await conn.execute("""
        INSERT INTO admin_actions (withdrawal_id, admin_id, action_type, message_id, chat_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (withdrawal_id)
        DO UPDATE SET
            admin_id = $2,
            action_type = $3,
            message_id = $4,
            chat_id = $5,
            started_at = CURRENT_TIMESTAMP
        """, withdrawal_id, admin_id, action_type, message_id, chat_id)
        return True
    except Exception as e:
        logger.error(f"خطأ في تخزين إجراء المشرف: {e}")
        return False
    finally:
        await release_connection(conn)
async def get_admin_action(withdrawal_id):
    """استرجاع إجراء المشرف من قاعدة البيانات"""
    conn = await get_connection()
    try:
        return await conn.fetchrow("""
        SELECT * FROM admin_actions WHERE withdrawal_id = $1
        """, withdrawal_id)
    finally:
        await release_connection(conn)

async def get_last_admin_action(admin_id, action_type):
    """استرجاع آخر إجراء للمشرف من نوع معين"""
    conn = await get_connection()
    try:
        return await conn.fetchrow("""
        SELECT * FROM admin_actions
        WHERE admin_id = $1 AND action_type = $2
        ORDER BY started_at DESC
        LIMIT 1
        """, admin_id, action_type)
    finally:
        await release_connection(conn)

async def cleanup_admin_actions():
    """تنظيف الإجراءات القديمة من قاعدة البيانات"""
    conn = await get_connection()
    try:
        await conn.execute("""
        DELETE FROM admin_actions
        WHERE started_at < NOW() - INTERVAL '24 hours'
        """)
    finally:
        await release_connection(conn)
__all__ = [
    'initialize_database',
    'add_user',
    'is_user_registered',
    'verify_registration_code',
    'generate_registration_code',
    'validate_registration_code',
    'add_registration_code',
    'register_user',
    'save_withdrawal',
    'get_withdrawal',
    'update_withdrawal_status',
    'get_setting',
    'set_setting',
    'initialize_settings',
    'create_pool',
    'close_pool',
    'get_connection',
    'release_connection',
    'get_active_withdrawals',
    'has_pending_request',
    'delete_registration_code',
    'get_exchange_rates',
    'update_exchange_rate',
    'delete_exchange_rate',
    'get_bep20_limits',
    'update_bep20_limits'
]
