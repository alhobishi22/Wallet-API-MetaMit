import psycopg2
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from psycopg2.extras import DictCursor, RealDictCursor

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class Database:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._init_db()
        
    def get_user(self, user_id: int) -> Optional[Dict]:
        """الحصول على معلومات المستخدم من قاعدة البيانات"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor(cursor_factory=DictCursor)
                cursor.execute('''
                    SELECT * FROM users 
                    WHERE user_id = %s
                ''', (user_id,))
                user = cursor.fetchone()
                if user:
                    return dict(user)
                return None
        except Exception as e:
            logger.error(f"خطأ في الحصول على معلومات المستخدم {user_id}: {e}")
            return None

    def _connect(self):
        # إزالة timeout=30.0 واستبدالها مثلاً بـ connect_timeout=30
        # psycopg2.connect لا يدعم timeout بهذه الصيغة
        return psycopg2.connect(self.db_url, cursor_factory=DictCursor)

    def _init_db(self):
        try:
            conn = self._connect()
            cursor = conn.cursor()

            # جداول PostgreSQL كما في النسخة السابقة
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    registration_code TEXT,
                    registration_date TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    last_activity TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS registration_codes (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_count INTEGER DEFAULT 0,
                    max_uses INTEGER DEFAULT -1,
                    expiry_date TIMESTAMP,
                    created_by TEXT,
                    last_used_at TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transfers (
                    transfer_id TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    transfer_type TEXT NOT NULL,
                    local_currency TEXT,
                    amount DOUBLE PRECISION,
                    unique_amount DOUBLE PRECISION,
                    final_usdt_amount DOUBLE PRECISION,
                    local_amount DOUBLE PRECISION,
                    recipient_name TEXT,
                    recipient_number TEXT,
                    recipient_notes TEXT,
                    wallet_id INTEGER,
                    wallet_name TEXT,
                    account_number TEXT,
                    usdt_network TEXT,
                    tx_hash TEXT,
                    deposit_address TEXT,
                    status TEXT DEFAULT 'pending',
                    receipt_url TEXT,
                    rejection_reason TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS exchange_rates (
                    currency TEXT PRIMARY KEY,
                    rate DOUBLE PRECISION NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # إنشاء الفهارس
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_transfers_user_id ON transfers(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_transfers_status ON transfers(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_transfers_created_at ON transfers(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_registration_codes_code ON registration_codes(code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_registration_codes_status ON registration_codes(status)')

            conn.commit()
            cursor.close()
            conn.close()
            logger.info("تم تهيئة قاعدة بيانات PostgreSQL وإنشاء الجداول بنجاح.")
        except psycopg2.Error as e:
            logger.error(f"خطأ في تهيئة قاعدة البيانات: {e}")

    def save_transfer(self, transfer_data: Dict) -> bool:
        try:
            # إزالة timeout=30.0
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                sql_query = '''
                    INSERT INTO transfers (
                        transfer_id, user_id, transfer_type, local_currency,
                        amount, unique_amount, final_usdt_amount, local_amount,
                        recipient_name, recipient_number, recipient_notes,
                        wallet_id, wallet_name, account_number,
                        usdt_network, tx_hash, deposit_address,
                        status, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                '''
                values = [
                    transfer_data.get('transfer_id'),
                    transfer_data.get('user_id'),
                    transfer_data.get('transfer_type'),
                    transfer_data.get('local_currency'),
                    transfer_data.get('amount'),
                    transfer_data.get('unique_amount'),
                    transfer_data.get('final_usdt_amount'),
                    transfer_data.get('local_amount'),
                    transfer_data.get('recipient_name'),
                    transfer_data.get('recipient_number'),
                    transfer_data.get('recipient_notes'),
                    transfer_data.get('wallet_id'),
                    transfer_data.get('wallet_name'),
                    transfer_data.get('account_number'),
                    transfer_data.get('usdt_network'),
                    transfer_data.get('tx_hash'),
                    transfer_data.get('deposit_address'),
                    'pending',
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ]
                cursor.execute(sql_query, values)
                conn.commit()
                logger.info(f"تم حفظ التحويل بنجاح: {transfer_data.get('transfer_id')}")
                return True
        except psycopg2.IntegrityError as e:
            logger.error(f"خطأ في حفظ التحويل (ربما معرف التحويل مكرر): {e}")
            return False
        except psycopg2.Error as e:
            logger.error(f"خطأ في حفظ التحويل: {e}")
            return False

    def get_transfer(self, transfer_id: str) -> Optional[Dict]:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                # استبدال ؟ بـ %s
                cursor.execute('SELECT * FROM transfers WHERE transfer_id = %s', (transfer_id,))
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    transfer = dict(zip(columns, row))
                    logger.info(f"تم العثور على التحويل: {transfer_id}")
                    return transfer
                else:
                    logger.warning(f"لم يتم العثور على التحويل بمعرف: {transfer_id}")
                    return None
        except psycopg2.Error as e:
            logger.error(f"خطأ في استرجاع التحويل {transfer_id}: {e}")
            return None

    def update_transfer_status(self, transfer_id: str, status: str,
                               receipt_url: Optional[str] = None,
                               rejection_reason: Optional[str] = None,
                               transfer_info: Optional[str] = None) -> bool:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                update_fields = ['status = %s', 'updated_at = %s']
                params = [status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")]

                if receipt_url:
                    update_fields.append('receipt_url = %s')
                    params.append(receipt_url)

                if rejection_reason:
                    update_fields.append('rejection_reason = %s')
                    params.append(rejection_reason)
                    
                if transfer_info:
                    update_fields.append('recipient_notes = %s')
                    params.append(transfer_info)

                params.append(transfer_id)

                sql_query = f'''
                    UPDATE transfers 
                    SET {', '.join(update_fields)}
                    WHERE transfer_id = %s
                '''
                cursor.execute(sql_query, params)
                conn.commit()

                if cursor.rowcount > 0:
                    logger.info(f"تم تحديث حالة التحويل {transfer_id} إلى {status}.")
                    return True
                else:
                    logger.warning(f"لم يتم العثور على التحويل {transfer_id} لتحديث حالته.")
                    return False
        except psycopg2.Error as e:
            logger.error(f"خطأ في تحديث حالة التحويل {transfer_id}: {e}")
            return False

    def add_registration_code(self, code: str, description: str = '', status: str = 'active',
                           max_uses: int = -1, expiry_date: str = None) -> bool:
        """إضافة كود تسجيل جديد
        Args:
            code (str): كود التسجيل
            description (str, optional): وصف الكود. Defaults to ''.
            status (str, optional): حالة الكود. Defaults to 'active'.
            max_uses (int, optional): الحد الأقصى للاستخدام. Defaults to -1.
            expiry_date (str, optional): تاريخ انتهاء الصلاحية. Defaults to None.
        """
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # معالجة تاريخ انتهاء الصلاحية
                expiry_datetime = None
                if expiry_date:
                    try:
                        # تحويل النص إلى كائن datetime
                        expiry_datetime = datetime.fromisoformat(expiry_date.replace('Z', '+00:00'))
                    except ValueError as e:
                        logger.error(f"تنسيق تاريخ انتهاء الصلاحية غير صحيح: {e}")
                        return False
                
                cursor.execute('''
                    INSERT INTO registration_codes 
                    (code, description, status, max_uses, expiry_date, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    code,
                    description,
                    status,
                    max_uses,
                    expiry_datetime,
                    datetime.now(),
                    datetime.now()
                ))
                conn.commit()
                logger.info(f"تم إضافة كود التسجيل: {code}")
                return True
                
        except psycopg2.IntegrityError:
            logger.warning(f"كود التسجيل {code} موجود بالفعل.")
            return False
        except psycopg2.Error as e:
            logger.error(f"خطأ في إضافة كود التسجيل {code}: {e}")
            return False

    def verify_registration_code(self, code: str) -> bool:
        if not code:
            logger.warning("تم تمرير كود تسجيل فارغ.")
            return False

        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                # تحسين استعلام التحقق من الكود
                cursor.execute('''
                    SELECT rc.status, rc.used_count, rc.max_uses, rc.description 
                    FROM registration_codes rc
                    WHERE TRIM(LOWER(rc.code)) = TRIM(LOWER(%s))
                    AND rc.status = 'active'
                ''', (code,))
                result = cursor.fetchone()
                
                if result:
                    status, used_count, max_uses, description = result
                    # التحقق من حد الاستخدام
                    if max_uses != -1 and used_count >= max_uses:
                        logger.warning(f"كود التسجيل {code} تجاوز الحد الأقصى للاستخدام.")
                        return False
                        
                    # تحديث عدد مرات الاستخدام
                    cursor.execute('''
                        UPDATE registration_codes 
                        SET used_count = used_count + 1 
                        WHERE TRIM(LOWER(code)) = TRIM(LOWER(%s))
                    ''', (code,))
                    conn.commit()
                    
                    logger.info(f"كود التسجيل {description} صالح.")
                    return True
                else:
                    logger.warning(f"كود التسجيل {code} غير صالح أو غير نشط.")
                    return False
                    
        except psycopg2.Error as e:
            logger.error(f"خطأ في التحقق من كود التسجيل {code}: {e}")
            return False

    def update_registration_code(self, code: str, update_data: Dict) -> bool:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # بناء استعلام التحديث ديناميكياً
                update_fields = []
                params = []
                for key, value in update_data.items():
                    update_fields.append(f"{key} = %s")
                    params.append(value)
                
                # إضافة معيار WHERE
                params.append(code)
                
                query = f'''
                    UPDATE registration_codes
                    SET {', '.join(update_fields)}
                    WHERE code = %s
                '''
                
                cursor.execute(query, params)
                conn.commit()
                
                if cursor.rowcount > 0:
                    logger.info(f"تم تحديث كود التسجيل {code}")
                    return True
                else:
                    logger.warning(f"لم يتم العثور على كود التسجيل {code}")
                    return False
                    
        except psycopg2.Error as e:
            logger.error(f"خطأ في تحديث كود التسجيل {code}: {e}")
            return False
            
    def get_code_details(self, code: str) -> Optional[Dict]:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor(cursor_factory=DictCursor)
                cursor.execute('''
                    SELECT 
                        rc.*,
                        COUNT(u.user_id) as active_users,
                        ARRAY_AGG(DISTINCT u.user_id) FILTER (WHERE u.user_id IS NOT NULL) as user_ids,
                        (
                            SELECT COUNT(*)
                            FROM transfers t
                            JOIN users u2 ON u2.user_id = t.user_id
                            WHERE u2.registration_code = rc.code
                        ) as total_transfers
                    FROM registration_codes rc
                    LEFT JOIN users u ON u.registration_code = rc.code
                    WHERE rc.code = %s
                    GROUP BY rc.id
                ''', (code,))
                
                result = cursor.fetchone()
                if result:
                    return dict(result)
                return None
                
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على تفاصيل الكود {code}: {e}")
            return None

    def delete_registration_code(self, code: str) -> bool:
        """حذف كود التسجيل."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                # تحقق من وجود الكود أولاً
                cursor.execute('SELECT status FROM registration_codes WHERE code = %s', (code,))
                result = cursor.fetchone()
                if not result:
                    logger.warning(f"لم يتم العثور على الكود {code} للحذف.")
                    return False

                # حذف الكود
                cursor.execute('DELETE FROM registration_codes WHERE code = %s', (code,))
                conn.commit()
                logger.info(f"تم حذف كود التسجيل {code} بنجاح.")
                return True
        except psycopg2.Error as e:
            logger.error(f"خطأ في حذف كود التسجيل {code}: {e}")
            return False

    def update_user_code(self, user_id: int, new_code: str) -> bool:
        """تحديث كود التسجيل للمستخدم"""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # التحقق من وجود الكود الجديد وأنه نشط
                cursor.execute('''
                    SELECT status, used_count, max_uses 
                    FROM registration_codes 
                    WHERE code = %s AND status = 'active'
                ''', (new_code,))
                code_info = cursor.fetchone()
                
                if not code_info:
                    logger.warning(f"الكود الجديد {new_code} غير صالح أو غير نشط.")
                    return False
                    
                status, used_count, max_uses = code_info
                if max_uses != -1 and used_count >= max_uses:
                    logger.warning(f"الكود {new_code} تجاوز الحد الأقصى للاستخدام.")
                    return False
                
                # تحديث كود المستخدم
                cursor.execute('''
                    UPDATE users 
                    SET registration_code = %s,
                        last_activity = %s
                    WHERE user_id = %s
                ''', (new_code, now, user_id))
                
                # تحديث عدد مرات استخدام الكود الجديد
                cursor.execute('''
                    UPDATE registration_codes 
                    SET used_count = used_count + 1 
                    WHERE code = %s
                ''', (new_code,))
                
                conn.commit()
                logger.info(f"تم تحديث كود التسجيل للمستخدم {user_id} إلى {new_code}.")
                return True
                
        except psycopg2.Error as e:
            logger.error(f"خطأ في تحديث كود التسجيل للمستخدم {user_id}: {e}")
            return False

    def add_user(self, user_id: int, registration_code: str) -> bool:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # التحقق من عدم وجود مستخدم آخر بنفس الكود
                cursor.execute('SELECT COUNT(*) FROM users WHERE registration_code = %s', (registration_code,))
                if cursor.fetchone()[0] > 0:
                    logger.warning(f"الكود {registration_code} مستخدم بالفعل.")
                    return False
                
                # إضافة المستخدم
                # ملاحظة: PostgreSQL يستخدم ON CONFLICT المستخدم_id.
                cursor.execute('''
                    INSERT INTO users (user_id, registration_code, registration_date)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        registration_code = EXCLUDED.registration_code,
                        registration_date = EXCLUDED.registration_date,
                        status = 'active',
                        last_activity = EXCLUDED.registration_date
                ''', (user_id, registration_code, now))
                
                # تحديث عدد مرات استخدام الكود
                cursor.execute('''
                    UPDATE registration_codes 
                    SET used_count = used_count + 1 
                    WHERE code = %s
                ''', (registration_code,))
                
                conn.commit()
                logger.info(f"تم إضافة/تحديث المستخدم {user_id} مع كود التسجيل {registration_code}.")
                return True
        except psycopg2.Error as e:
            logger.error(f"خطأ في إضافة/تحديث المستخدم {user_id}: {e}")
            return False

    def get_user(self, user_id: int) -> Optional[Dict]:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    user = dict(zip(columns, row))
                    logger.info(f"تم العثور على بيانات المستخدم {user_id}.")
                    return user
                else:
                    logger.warning(f"لم يتم العثور على المستخدم {user_id}.")
                    return None
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على بيانات المستخدم {user_id}: {e}")
            return None

    def get_exchange_rate(self, currency: str) -> float:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT rate FROM exchange_rates WHERE currency = %s', (currency.upper(),))
                result = cursor.fetchone()
                if result:
                    return float(result[0])
                else:
                    logger.warning(f"لم يتم العثور على سعر صرف للعملة {currency}")
                    return 1.0
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على سعر الصرف للعملة {currency}: {e}")
            return 1.0

    def get_statistics(self) -> Dict:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor(cursor_factory=DictCursor)
                
                # إحصائيات المستخدمين
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_users,
                        COUNT(*) FILTER (WHERE status = 'active') as active_users,
                        COUNT(*) FILTER (WHERE DATE(registration_date) = CURRENT_DATE) as new_users_today,
                        COUNT(*) FILTER (WHERE DATE(last_activity) = CURRENT_DATE) as active_users_today
                    FROM users
                ''')
                user_stats = cursor.fetchone()
                
                # إحصائيات الأكواد
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_codes,
                        COUNT(*) FILTER (WHERE status = 'active') as active_codes,
                        COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) as new_codes_today,
                        SUM(used_count) as total_uses
                    FROM registration_codes
                ''')
                code_stats = cursor.fetchone()
                
                # إحصائيات التحويلات
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_transfers,
                        COUNT(*) FILTER (WHERE status = 'completed') as completed_transfers,
                        COUNT(*) FILTER (WHERE status = 'pending') as pending_transfers,
                        COUNT(*) FILTER (WHERE status = 'rejected') as rejected_transfers,
                        COUNT(*) FILTER (WHERE DATE(created_at) = CURRENT_DATE) as today_operations,
                        COUNT(*) FILTER (WHERE status = 'completed' AND DATE(completed_at) = CURRENT_DATE) as completed_today,
                        COALESCE(SUM(amount) FILTER (WHERE status = 'completed'), 0) as total_amount,
                        COALESCE(SUM(amount) FILTER (WHERE status = 'completed' AND DATE(completed_at) = CURRENT_DATE), 0) as today_amount,
                        COALESCE(AVG(amount) FILTER (WHERE status = 'completed'), 0) as avg_amount
                    FROM transfers
                ''')
                transfer_stats = cursor.fetchone()
                
                # إحصائيات حسب العملات
                cursor.execute('''
                    SELECT 
                        local_currency,
                        COUNT(*) as total_transfers,
                        COALESCE(SUM(amount), 0) as total_amount
                    FROM transfers 
                    WHERE status = 'completed' 
                    AND local_currency IS NOT NULL 
                    AND local_currency != ''
                    GROUP BY local_currency
                ''')
                currency_stats = cursor.fetchall()
                
                return {
                    # إحصائيات المستخدمين
                    'total_users': user_stats['total_users'],
                    'active_users': user_stats['active_users'],
                    'new_users_today': user_stats['new_users_today'],
                    'active_users_today': user_stats['active_users_today'],
                    
                    # إحصائيات الأكواد
                    'total_codes': code_stats['total_codes'],
                    'active_codes': code_stats['active_codes'],
                    'new_codes_today': code_stats['new_codes_today'],
                    'total_code_uses': code_stats['total_uses'] or 0,
                    
                    # إحصائيات التحويلات
                    'total_transfers': transfer_stats['total_transfers'],
                    'completed_transfers': transfer_stats['completed_transfers'],
                    'pending_transfers': transfer_stats['pending_transfers'],
                    'rejected_transfers': transfer_stats['rejected_transfers'],
                    'today_operations': transfer_stats['today_operations'],
                    'completed_today': transfer_stats['completed_today'],
                    'total_amount': float(transfer_stats['total_amount']),
                    'today_amount': float(transfer_stats['today_amount']),
                    'avg_amount': float(transfer_stats['avg_amount']),
                    
                    # إحصائيات العملات
                    'currency_stats': [
                        {
                            'currency': stat['local_currency'],
                            'total_transfers': stat['total_transfers'],
                            'total_amount': float(stat['total_amount'])
                        }
                        for stat in currency_stats
                    ]
                }
                
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على الإحصائيات: {e}", exc_info=True)
            return {
                'total_users': 0,
                'active_users': 0,
                'new_users_today': 0,
                'active_users_today': 0,
                'total_codes': 0,
                'active_codes': 0,
                'new_codes_today': 0,
                'total_code_uses': 0,
                'total_transfers': 0,
                'completed_transfers': 0,
                'pending_transfers': 0,
                'rejected_transfers': 0,
                'today_operations': 0,
                'completed_today': 0,
                'total_amount': 0,
                'today_amount': 0,
                'avg_amount': 0,
                'currency_stats': [],
                'total_transfers': 0,
                'completed_transfers': 0,
                'pending_transfers': 0,
                'rejected_transfers': 0,
                'total_amount': 0.0
            }

    def get_settings(self) -> Dict:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT key, value FROM settings')
                settings = {}
                for key, value in cursor.fetchall():
                    try:
                        settings[key] = float(value)
                    except ValueError:
                        settings[key] = value

                default_settings = {
                    'fixed_fee_threshold': 20,
                    'fixed_fee_amount': 1,
                    'percentage_fee': 0.05,
                    'min_withdrawal': 10,
                    'max_withdrawal': 1000
                }

                for dk, dv in default_settings.items():
                    if dk not in settings:
                        settings[dk] = dv

                return settings
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على الإعدادات: {e}")
            return {}

    def update_settings(self, settings: Dict) -> bool:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                for key, value in settings.items():
                    cursor.execute('''
                        INSERT INTO settings (key, value, updated_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(key) DO UPDATE SET
                            value = EXCLUDED.value,
                            updated_at = EXCLUDED.updated_at
                    ''', (key, str(value), now))
                
                conn.commit()
                logger.info("تم تحديث الإعدادات بنجاح.")
                return True
        except psycopg2.Error as e:
            logger.error(f"خطأ في تحديث الإعدادات: {e}")
            return False

    def get_transfers(self, page: int = 1, per_page: int = 10, status: Optional[str] = None) -> Dict:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()

                query = '''
                    SELECT 
                        t.*,
                        u.registration_code AS user_code
                    FROM transfers t
                    LEFT JOIN users u ON t.user_id = u.user_id
                    WHERE 1=1
                '''
                params = []

                if status:
                    query += ' AND t.status = %s'
                    params.append(status)

                # الحصول على العدد الإجمالي
                count_query = f"SELECT COUNT(*) FROM ({query}) AS sub"
                cursor.execute(count_query, params)
                total_count = cursor.fetchone()[0]

                query += ' ORDER BY t.created_at DESC LIMIT %s OFFSET %s'
                params.extend([per_page, (page - 1) * per_page])

                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                transfers = [dict(zip(columns, row)) for row in cursor.fetchall()]

                total_pages = (total_count + per_page - 1) // per_page

                logger.info(f"تم جلب التحويلات: الصفحة {page} من {total_pages}, حالة: {status}")

                return {
                    'transfers': transfers,
                    'total': total_count,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': total_pages
                }
        except psycopg2.Error as e:
            logger.error(f"خطأ في جلب التحويلات: {e}")
            return {
                'transfers': [],
                'total': 0,
                'page': page,
                'per_page': per_page,
                'total_pages': 0
            }

    def get_transfer_details(self, transfer_id: str) -> Optional[Dict]:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                query = '''
                    SELECT 
                        t.*,
                        u.registration_code as user_code,
                        u.registration_date as user_registration_date
                    FROM transfers t
                    LEFT JOIN users u ON t.user_id = u.user_id
                    WHERE t.transfer_id = %s
                '''
                cursor.execute(query, (transfer_id,))
                row = cursor.fetchone()
                if row:
                    columns = [desc[0] for desc in cursor.description]
                    transfer_details = dict(zip(columns, row))
                    logger.info(f"تم العثور على تفاصيل التحويل: {transfer_id}")
                    return transfer_details
                else:
                    logger.warning(f"لم يتم العثور على تفاصيل التحويل: {transfer_id}")
                    return None
        except psycopg2.Error as e:
            logger.error(f"خطأ في جلب تفاصيل التحويل {transfer_id}: {e}")
            return None

    def get_all_codes(self) -> List[Dict]:
        """الحصول على جميع الأكواد مع إحصائياتها"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT 
                        c.*,
                        COUNT(t.transfer_id) as used_count,
                        COALESCE(SUM(t.amount), 0) as total_amount,
                        COALESCE(SUM(t.final_usdt_amount), 0) as total_usdt
                    FROM registration_codes c
                    LEFT JOIN users u ON u.registration_code = c.code
                    LEFT JOIN transfers t ON t.user_id = u.user_id AND t.status = 'completed'
                    GROUP BY c.code, c.id, c.description, c.status, c.max_uses, c.created_at
                    ORDER BY c.created_at DESC
                ''')
                codes = cursor.fetchall()
                return codes
        except Exception as e:
            logger.error(f"خطأ في الحصول على قائمة الأكواد: {e}")
            return []

    def check_transfer_exists(self, transfer_id: str) -> bool:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM transfers WHERE transfer_id = %s', (transfer_id,))
                exists = cursor.fetchone() is not None
                if exists:
                    logger.debug(f"التحويل {transfer_id} موجود في قاعدة البيانات.")
                else:
                    logger.debug(f"التحويل {transfer_id} غير موجود في قاعدة البيانات.")
                return exists
        except psycopg2.Error as e:
            logger.error(f"خطأ في التحقق من وجود التحويل {transfer_id}: {e}")
            return False

    def repair_table_structure(self):
        """إصلاح هيكل قاعدة البيانات وإضافة الأعمدة المفقودة"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # التحقق من وجود عمود expiry_date وإضافته إذا كان مفقوداً
                cursor.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'registration_codes' 
                    AND column_name = 'expiry_date'
                """)
                if not cursor.fetchone():
                    cursor.execute("""
                        ALTER TABLE registration_codes 
                        ADD COLUMN expiry_date TIMESTAMP
                    """)
                    conn.commit()
                    logger.info("تم إضافة عمود expiry_date بنجاح")
                
                return True
        except Exception as e:
            logger.error(f"خطأ في إصلاح هيكل قاعدة البيانات: {e}")
            return False

    def get_exchange_rates(self) -> Dict:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT currency, rate, updated_at FROM exchange_rates')
                rates = {}
                for row in cursor.fetchall():
                    rates[row[0]] = {
                        'rate': row[1],
                        'updated_at': row[2]
                    }
                return rates
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على أسعار الصرف: {e}")
            return {}

    def update_exchange_rate(self, currency: str, rate: float) -> bool:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute('''
                    INSERT INTO exchange_rates (currency, rate, updated_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(currency) DO UPDATE SET
                        rate = EXCLUDED.rate,
                        updated_at = EXCLUDED.updated_at
                ''', (currency.upper(), rate, now))
                conn.commit()
                logger.info(f"تم تحديث سعر الصرف للعملة {currency}: {rate}")
                return True
        except psycopg2.Error as e:
            logger.error(f"خطأ في تحديث سعر الصرف للعملة {currency}: {e}")
            return False

    def delete_exchange_rate(self, currency: str) -> bool:
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM exchange_rates WHERE currency = %s', (currency.upper(),))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"تم حذف سعر الصرف للعملة {currency}")
                    return True
                else:
                    logger.warning(f"لم يتم العثور على سعر صرف للعملة {currency}")
                    return False
        except psycopg2.Error as e:
            logger.error(f"خطأ في حذف سعر الصرف للعملة {currency}: {e}")
            return False

    def export_codes_to_excel(self) -> List[Dict]:
        """تصدير جميع الأكواد إلى تنسيق مناسب للإكسل"""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
                cursor.execute('''
                    SELECT 
                        rc.code,
                        rc.description,
                        rc.status,
                        rc.used_count,
                        rc.max_uses,
                        rc.created_at,
                        rc.expiry_date,
                        rc.created_by
                    FROM registration_codes rc
                    ORDER BY rc.created_at DESC
                ''')
                codes = cursor.fetchall()
                logger.info(f"تم استخراج {len(codes)} كود من قاعدة البيانات")
                return codes
        except Exception as e:
            logger.error(f"خطأ في تصدير الأكواد: {e}")
            return []

    def import_codes_from_excel(self, codes_data: List[Dict]) -> Tuple[int, int, List[str]]:
        """استيراد الأكواد من بيانات الإكسل
        Returns:
            Tuple[int, int, List[str]]: (عدد الأكواد المضافة, عدد الأكواد المرفوضة, قائمة الأخطاء)
        """
        success_count = 0
        failed_count = 0
        errors = []

        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                for row in codes_data:
                    try:
                        # التحقق من وجود الحقول الإلزامية
                        if not row.get('code'):
                            raise ValueError("الكود مطلوب")

                        cursor.execute('''
                            INSERT INTO registration_codes 
                            (code, description, status, max_uses, expiry_date, created_by)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (code) DO NOTHING
                        ''', (
                            row.get('code'),
                            row.get('description', ''),
                            row.get('status', 'active'),
                            int(row.get('max_uses', -1)),
                            row.get('expiry_date'),
                            row.get('created_by', 'import')
                        ))
                        
                        if cursor.rowcount > 0:
                            success_count += 1
                        else:
                            failed_count += 1
                            errors.append(f"الكود {row.get('code')} موجود مسبقاً")
                            
                    except Exception as e:
                        failed_count += 1
                        errors.append(f"خطأ في استيراد الكود {row.get('code', 'unknown')}: {str(e)}")
                
                conn.commit()
                return success_count, failed_count, errors
                
        except Exception as e:
            logger.error(f"خطأ في استيراد الأكواد: {e}")
            return 0, len(codes_data), [str(e)]

    def add_test_codes(self):
        """إضافة بعض الأكواد للاختبار"""
        test_codes = [
            {
                'code': 'TEST001',
                'description': 'كود اختبار 1',
                'status': 'active',
                'max_uses': 10
            },
            {
                'code': 'TEST002',
                'description': 'كود اختبار 2',
                'status': 'inactive',
                'max_uses': -1
            },
            {
                'code': 'TEST003',
                'description': 'كود اختبار 3',
                'status': 'active',
                'max_uses': 5,
                'expiry_date': (datetime.now().replace(year=datetime.now().year + 1)).strftime('%Y-%m-%d %H:%M:%S')
            }
        ]
        
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                try:
                    for code_data in test_codes:
                        cursor.execute('''
                            INSERT INTO registration_codes 
                            (code, description, status, max_uses, expiry_date, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (code) DO NOTHING
                        ''', (
                            code_data['code'],
                            code_data['description'],
                            code_data['status'],
                            code_data['max_uses'],
                            code_data.get('expiry_date'),
                            datetime.now(),
                            datetime.now()
                        ))
                    conn.commit()
                    logger.info("تم إضافة أكواد الاختبار بنجاح")
                    return True
                except Exception as e:
                    conn.rollback()
                    logger.error(f"خطأ في إضافة أكواد الاختبار: {e}")
                    return False
        except Exception as e:
            logger.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")
            return False

    def check_duplicate_txid(self, tx_hash: str) -> bool:
        """
        التحقق من وجود رمز معاملة مكرر في قاعدة البيانات
        
        Args:
            tx_hash (str): رمز المعاملة للتحقق منه
            
        Returns:
            bool: True إذا كان رمز المعاملة موجودًا بالفعل، False إذا لم يكن موجودًا
        """
        if not tx_hash:
            logger.warning("تم تمرير رمز معاملة فارغ للتحقق.")
            return False
            
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) 
                    FROM transfers 
                    WHERE tx_hash = %s
                ''', (tx_hash.strip(),))
                
                count = cursor.fetchone()[0]
                
                if count > 0:
                    logger.warning(f"رمز المعاملة {tx_hash} موجود بالفعل في قاعدة البيانات.")
                    return True
                else:
                    logger.info(f"رمز المعاملة {tx_hash} غير موجود في قاعدة البيانات.")
                    return False
                    
        except psycopg2.Error as e:
            logger.error(f"خطأ في التحقق من تكرار رمز المعاملة {tx_hash}: {e}")
            return False
