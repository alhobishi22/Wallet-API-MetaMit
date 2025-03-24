import psycopg2
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from psycopg2.extras import DictCursor

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class Database:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._init_db()

    def _init_db(self):
        """تهيئة قاعدة بيانات PostgreSQL والتحقق من وجود الجداول."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # التحقق من وجود الجداول
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'users'
                    );
                """)
                tables_exist = cursor.fetchone()[0]

                if not tables_exist:
                    # إنشاء جدول المستخدمين
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS users (
                            user_id BIGINT PRIMARY KEY,
                            registration_code TEXT,
                            registration_date TIMESTAMP,
                            status TEXT DEFAULT 'active',
                            last_activity TIMESTAMP
                        )
                    ''')

                    # إنشاء جدول أكواد التسجيل
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS registration_codes (
                            id SERIAL PRIMARY KEY,
                            code TEXT UNIQUE NOT NULL,
                            description TEXT NOT NULL,
                            status TEXT DEFAULT 'active',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            used_count INTEGER DEFAULT 0,
                            max_uses INTEGER DEFAULT -1
                        )
                    ''')

                    # إنشاء جدول التحويلات
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

                    # إنشاء جدول الإعدادات
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS settings (
                            key TEXT PRIMARY KEY,
                            value TEXT NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    # إنشاء جدول أسعار الصرف
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS exchange_rates (
                            currency TEXT PRIMARY KEY,
                            rate DOUBLE PRECISION NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    # إنشاء الفهارس لتحسين الأداء
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_transfers_user_id ON transfers(user_id)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_transfers_status ON transfers(status)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_transfers_created_at ON transfers(created_at)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_registration_codes_code ON registration_codes(code)')
                    cursor.execute('CREATE INDEX IF NOT EXISTS idx_registration_codes_status ON registration_codes(status)')

                    conn.commit()
                    logger.info("تم إنشاء جداول قاعدة البيانات بنجاح.")
                else:
                    logger.info("جداول قاعدة البيانات موجودة بالفعل.")
        except psycopg2.Error as e:
            logger.error(f"خطأ في تهيئة قاعدة البيانات: {e}")

    def save_transfer(self, transfer_data: Dict) -> bool:
        """حفظ بيانات التحويل في قاعدة البيانات."""
        try:
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
        """الحصول على تفاصيل تحويل معين بواسطة معرف التحويل."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                logger.debug(f"محاولة استرجاع التحويل بمعرف: {transfer_id}")
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
        """تحديث حالة التحويل."""
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

    def add_registration_code(self, code: str, description: str = "") -> bool:
        """إضافة كود تسجيل جديد."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO registration_codes (code, description, status)
                    VALUES (%s, %s, 'active')
                ''', (code, description))
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
        """التحقق من صلاحية كود التسجيل."""
        if not code:
            logger.warning("تم تمرير كود تسجيل فارغ.")
            return False

        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT status, used_count, max_uses FROM registration_codes
                    WHERE TRIM(code) = TRIM(%s) AND status = 'active'
                    AND status != 'deleted'
                ''', (code,))
                result = cursor.fetchone()
                if result:
                    status, used_count, max_uses = result
                    if max_uses != -1 and used_count >= max_uses:
                        logger.warning(f"كود التسجيل {code} تجاوز الحد الأقصى للاستخدام.")
                        return False
                    logger.info(f"كود التسجيل {code} صالح.")
                    return True
                else:
                    logger.warning(f"كود التسجيل {code} غير صالح أو غير نشط أو محذوف.")
                    return False
        except psycopg2.Error as e:
            logger.error(f"خطأ في التحقق من كود التسجيل {code}: {e}")
            return False

    def update_code_status(self, code: str, new_status: str) -> bool:
        """تحديث حالة كود التسجيل."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE registration_codes
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE code = %s
                ''', (new_status, code))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"تم تحديث حالة كود التسجيل {code} إلى {new_status}.")
                    return True
                else:
                    logger.warning(f"لم يتم العثور على كود التسجيل {code} لتحديث حالته.")
                    return False
        except psycopg2.Error as e:
            logger.error(f"خطأ في تحديث حالة كود التسجيل {code}: {e}")
            return False

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

    def add_user(self, user_id: int, registration_code: str) -> bool:
        """إضافة أو تحديث مستخدم في قاعدة البيانات."""
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                
                # التحقق من عدم وجود مستخدم آخر بنفس الكود
                cursor.execute('SELECT COUNT(*) FROM users WHERE registration_code = %s', (registration_code,))
                if cursor.fetchone()[0] > 0:
                    logger.warning(f"الكود {registration_code} مستخدم بالفعل.")
                    return False
                
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
        """الحصول على بيانات مستخدم معين."""
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

    def get_statistics(self) -> Dict:
        """الحصول على الإحصائيات العامة للبوت."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()

                # عدد المستخدمين
                cursor.execute('SELECT COUNT(*) FROM users')
                total_users = cursor.fetchone()[0]

                # عدد أكواد التسجيل
                cursor.execute('SELECT COUNT(*) FROM registration_codes')
                total_codes = cursor.fetchone()[0]

                # عمليات اليوم
                today = datetime.now().strftime('%Y-%m-%d')
                # استخدم created_at::date للمقارنة
                cursor.execute('''
                    SELECT COUNT(*) FROM transfers
                    WHERE created_at::date = %s
                ''', (today,))
                today_operations = cursor.fetchone()[0]

                # إحصائيات إضافية
                cursor.execute('''
                    SELECT 
                        COUNT(*) as total_transfers,
                        SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_transfers,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_transfers,
                        SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_transfers,
                        SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) as total_amount
                    FROM transfers
                ''')
                transfer_stats = cursor.fetchone()

                return {
                    'total_users': total_users,
                    'total_codes': total_codes,
                    'today_operations': today_operations,
                    'total_transfers': transfer_stats[0] or 0,
                    'completed_transfers': transfer_stats[1] or 0,
                    'pending_transfers': transfer_stats[2] or 0,
                    'rejected_transfers': transfer_stats[3] or 0,
                    'total_amount': float(transfer_stats[4] or 0)
                }
        except psycopg2.Error as e:
            logger.error(f"خطأ في الحصول على الإحصائيات: {e}")
            return {
                'total_users': 0,
                'total_codes': 0,
                'today_operations': 0,
                'total_transfers': 0,
                'completed_transfers': 0,
                'pending_transfers': 0,
                'rejected_transfers': 0,
                'total_amount': 0.0
            }

    def get_settings(self) -> Dict:
        """الحصول على إعدادات البوت."""
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
        """تحديث إعدادات البوت."""
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
        """الحصول على قائمة التحويلات مع دعم التصفية والتقسيم إلى صفحات."""
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
        """الحصول على تفاصيل تحويل معين."""
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
        """الحصول على جميع أكواد التسجيل."""
        try:
            with psycopg2.connect(self.db_url) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, code, description, status, created_at
                    FROM registration_codes
                    ORDER BY created_at DESC
                ''')
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                codes = [dict(zip(columns, row)) for row in rows]
                logger.info(f"تم جلب جميع أكواد التسجيل: {len(codes)} كود.")
                return codes
        except psycopg2.Error as e:
            logger.error(f"خطأ في جلب أكواد التسجيل: {e}")
            return []

    def check_transfer_exists(self, transfer_id: str) -> bool:
        """التحقق من وجود التحويل في قاعدة البيانات."""
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
        """في PostgreSQL لا حاجة لاستخدام PRAGMA، يمكن تجاهل هذه الوظيفة أو تعديلها."""
        logger.info("لا حاجة لإصلاح الهيكل بهذه الطريقة في PostgreSQL.")
