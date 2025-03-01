"""
ملف قاعدة البيانات - يحتوي على جميع الوظائف المتعلقة بقاعدة البيانات
"""
import os
import logging
import psycopg2
import psycopg2.extras
from psycopg2 import sql
from dotenv import load_dotenv
from datetime import datetime, timedelta

# تحميل متغيرات البيئة
load_dotenv()

# إعداد التسجيل
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# الحصول على رابط قاعدة البيانات من متغيرات البيئة
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    """
    إنشاء اتصال بقاعدة البيانات
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        logger.error(f"خطأ في الاتصال بقاعدة البيانات: {str(e)}")
        raise

def create_tables():
    """
    إنشاء جداول قاعدة البيانات
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # حذف الجداول إذا كانت موجودة
        cur.execute("DROP TABLE IF EXISTS password_reset_tokens CASCADE")
        cur.execute("DROP TABLE IF EXISTS users CASCADE")
        cur.execute("DROP TABLE IF EXISTS kyc_application CASCADE")
        
        # إنشاء جدول طلبات التحقق من الهوية
        cur.execute("""
            CREATE TABLE kyc_application (
                id SERIAL PRIMARY KEY,
                application_id VARCHAR(50) UNIQUE NOT NULL,
                full_name VARCHAR(100) NOT NULL,
                phone_number VARCHAR(20) NOT NULL,
                address VARCHAR(200) NOT NULL,
                id_photo_url VARCHAR(200) NOT NULL,
                selfie_photo_url VARCHAR(200) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                registration_code VARCHAR(50),
                rejection_reason TEXT,
                telegram_chat_id VARCHAR(50),
                welcome_message_id INTEGER,
                device_info JSONB,
                ip_address VARCHAR(50),
                geo_location JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # إنشاء جدول المستخدمين
        cur.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(100) NOT NULL,
                salt VARCHAR(50) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                full_name VARCHAR(100) NOT NULL,
                registration_code VARCHAR(50),
                is_admin BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # إنشاء جدول رموز إعادة تعيين كلمة المرور
        cur.execute("""
            CREATE TABLE password_reset_tokens (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) NOT NULL,
                reset_token VARCHAR(100) UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username) REFERENCES users(username) ON DELETE CASCADE
            )
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info("تم إنشاء جداول قاعدة البيانات بنجاح")
        return True
    except Exception as e:
        logger.error(f"خطأ في إنشاء جداول قاعدة البيانات: {str(e)}")
        return False

def get_photo_url(request_id, is_id_photo=True):
    """
    الحصول على رابط صورة من طلب التحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # تحديد نوع الصورة المطلوبة
        photo_field = "id_photo_url" if is_id_photo else "selfie_photo_url"
        
        # استعلام للحصول على رابط الصورة
        query = f"""
        SELECT {photo_field}
        FROM kyc_application
        WHERE application_id = %s
        """
        
        cur.execute(query, (request_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            return True, result[0]
        else:
            return False, "لم يتم العثور على الطلب"
    
    except Exception as e:
        logger.error(f"خطأ في الحصول على رابط الصورة: {str(e)}")
        return False, str(e)

def get_user_telegram_id(request_id):
    """
    الحصول على معرف تلغرام للمستخدم من طلب التحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # استعلام للحصول على معرف تلغرام
        query = """
        SELECT telegram_chat_id
        FROM kyc_application
        WHERE application_id = %s
        """
        
        cur.execute(query, (request_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result and result[0]:
            return result[0]
        else:
            return None
    
    except Exception as e:
        logger.error(f"خطأ في الحصول على معرف تلغرام للمستخدم: {str(e)}")
        return None

def update_welcome_message_id(telegram_chat_id, message_id):
    """
    تحديث معرف رسالة الترحيب للمستخدم
    
    :param telegram_chat_id: معرف دردشة المستخدم في تلغرام
    :param message_id: معرف رسالة الترحيب
    :return: True إذا تم التحديث بنجاح، False في حالة الفشل
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # التحقق من وجود عمود welcome_message_id في الجدول
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'kyc_application' 
            AND column_name = 'welcome_message_id'
        """)
        has_welcome_message_column = cur.fetchone() is not None
        
        if not has_welcome_message_column:
            logger.warning("عمود welcome_message_id غير موجود في جدول kyc_application. تم تجاهل تحديث معرف رسالة الترحيب.")
            # نعتبر العملية ناجحة حتى لا تتوقف سير العمل
            cur.close()
            conn.close()
            return True
        
        # تحديث معرف رسالة الترحيب للمستخدم
        update_query = """
        UPDATE kyc_application
        SET welcome_message_id = %s
        WHERE telegram_chat_id = %s
        """
        
        cur.execute(update_query, (message_id, telegram_chat_id))
        
        # التحقق من عدد الصفوف المتأثرة
        affected_rows = cur.rowcount
        
        conn.commit()
        cur.close()
        conn.close()
        
        if affected_rows > 0:
            logger.info(f"تم تحديث معرف رسالة الترحيب للمستخدم {telegram_chat_id} بنجاح")
            return True
        else:
            logger.warning(f"لم يتم العثور على مستخدم بمعرف دردشة {telegram_chat_id}")
            return False
        
    except Exception as e:
        logger.error(f"خطأ في تحديث معرف رسالة الترحيب: {str(e)}")
        return False

def get_welcome_message_id(telegram_chat_id):
    """
    الحصول على معرف رسالة الترحيب للمستخدم
    
    :param telegram_chat_id: معرف دردشة المستخدم في تلغرام
    :return: معرف رسالة الترحيب أو None في حالة عدم وجوده
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # التحقق من وجود عمود welcome_message_id في الجدول
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'kyc_application' 
            AND column_name = 'welcome_message_id'
        """)
        has_welcome_message_column = cur.fetchone() is not None
        
        if not has_welcome_message_column:
            logger.warning("عمود welcome_message_id غير موجود في جدول kyc_application. تم إرجاع None.")
            cur.close()
            conn.close()
            return None
        
        # الحصول على معرف رسالة الترحيب للمستخدم
        select_query = """
        SELECT welcome_message_id
        FROM kyc_application
        WHERE telegram_chat_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """
        
        cur.execute(select_query, (telegram_chat_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result and result[0]:
            return result[0]
        else:
            return None
        
    except Exception as e:
        logger.error(f"خطأ في الحصول على معرف رسالة الترحيب: {str(e)}")
        return None

def user_exists(username):
    """
    التحقق من وجود المستخدم في قاعدة البيانات
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT COUNT(*)
        FROM users
        WHERE username = %s
        """
        
        cur.execute(query, (username,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        return result[0] > 0
    
    except Exception as e:
        logger.error(f"خطأ في التحقق من وجود المستخدم: {str(e)}")
        return False

def save_user(user_data):
    """
    حفظ مستخدم جديد في قاعدة البيانات
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # التحقق من وجود رمز التسجيل إذا تم تقديمه
        if 'registration_code' in user_data and user_data['registration_code']:
            # التحقق من صحة رمز التسجيل
            check_query = """
            SELECT COUNT(*)
            FROM kyc_application
            WHERE registration_code = %s AND status = 'approved'
            """
            
            cur.execute(check_query, (user_data['registration_code'],))
            result = cur.fetchone()
            
            if result[0] == 0:
                cur.close()
                conn.close()
                return False, "رمز التسجيل غير صالح"
        
        # إدراج المستخدم الجديد
        insert_query = """
        INSERT INTO users (username, password_hash, salt, email, full_name, registration_code)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """
        
        cur.execute(insert_query, (
            user_data['username'],
            user_data['password_hash'],
            user_data['salt'],
            user_data['email'],
            user_data['full_name'],
            user_data.get('registration_code')
        ))
        
        user_id = cur.fetchone()[0]
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم حفظ المستخدم الجديد بنجاح: {user_data['username']}")
        return True, user_id
    
    except Exception as e:
        logger.error(f"خطأ في حفظ المستخدم الجديد: {str(e)}")
        return False, str(e)

def get_user(username):
    """
    الحصول على بيانات المستخدم من قاعدة البيانات
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT id, username, password_hash, salt, email, full_name, 
               registration_code, is_admin, is_active, created_at
        FROM users
        WHERE username = %s
        """
        
        cur.execute(query, (username,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            user_data = {
                'id': result[0],
                'username': result[1],
                'password_hash': result[2],
                'salt': result[3],
                'email': result[4],
                'full_name': result[5],
                'registration_code': result[6],
                'is_admin': result[7],
                'is_active': result[8],
                'created_at': result[9]
            }
            return True, user_data
        else:
            return False, "المستخدم غير موجود"
    
    except Exception as e:
        logger.error(f"خطأ في الحصول على بيانات المستخدم: {str(e)}")
        return False, str(e)

def get_user_by_email(email):
    """
    الحصول على اسم المستخدم باستخدام البريد الإلكتروني
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT username
        FROM users
        WHERE email = %s
        """
        
        cur.execute(query, (email,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            return True, result[0]
        else:
            return False, "البريد الإلكتروني غير مسجل"
    
    except Exception as e:
        logger.error(f"خطأ في الحصول على اسم المستخدم بواسطة البريد الإلكتروني: {str(e)}")
        return False, str(e)

def update_user_password(username, password_hash, salt):
    """
    تحديث كلمة مرور المستخدم
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        update_query = """
        UPDATE users
        SET password_hash = %s, salt = %s, updated_at = NOW()
        WHERE username = %s
        """
        
        cur.execute(update_query, (password_hash, salt, username))
        
        # التحقق من نجاح التحديث
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return False, "المستخدم غير موجود"
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم تحديث كلمة مرور المستخدم بنجاح: {username}")
        return True, "تم تحديث كلمة المرور بنجاح"
    
    except Exception as e:
        logger.error(f"خطأ في تحديث كلمة مرور المستخدم: {str(e)}")
        return False, str(e)

def save_reset_token(username, reset_token, expiry_hours=24):
    """
    حفظ رمز إعادة تعيين كلمة المرور
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # حذف أي رموز سابقة لنفس المستخدم
        delete_query = """
        DELETE FROM password_reset_tokens
        WHERE username = %s
        """
        
        cur.execute(delete_query, (username,))
        
        # حساب وقت انتهاء الصلاحية
        expires_at = datetime.now() + timedelta(hours=expiry_hours)
        
        # إدراج الرمز الجديد
        insert_query = """
        INSERT INTO password_reset_tokens (username, reset_token, expires_at)
        VALUES (%s, %s, %s)
        """
        
        cur.execute(insert_query, (username, reset_token, expires_at))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم حفظ رمز إعادة تعيين كلمة المرور للمستخدم: {username}")
        return True, "تم إنشاء رمز إعادة التعيين بنجاح"
    
    except Exception as e:
        logger.error(f"خطأ في حفظ رمز إعادة تعيين كلمة المرور: {str(e)}")
        return False, str(e)

def verify_reset_token(reset_token):
    """
    التحقق من صحة رمز إعادة تعيين كلمة المرور
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT username, expires_at
        FROM password_reset_tokens
        WHERE reset_token = %s
        """
        
        cur.execute(query, (reset_token,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not result:
            return False, "رمز إعادة التعيين غير صالح"
        
        username, expires_at = result
        
        # التحقق من انتهاء صلاحية الرمز
        if expires_at < datetime.now():
            return False, "انتهت صلاحية رمز إعادة التعيين"
        
        return True, username
    
    except Exception as e:
        logger.error(f"خطأ في التحقق من صحة رمز إعادة تعيين كلمة المرور: {str(e)}")
        return False, str(e)

def delete_reset_token(reset_token):
    """
    حذف رمز إعادة تعيين كلمة المرور بعد استخدامه
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        delete_query = """
        DELETE FROM password_reset_tokens
        WHERE reset_token = %s
        """
        
        cur.execute(delete_query, (reset_token,))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم حذف رمز إعادة تعيين كلمة المرور بنجاح")
        return True
    
    except Exception as e:
        logger.error(f"خطأ في حذف رمز إعادة تعيين كلمة المرور: {str(e)}")
        return False

def get_application_by_code(registration_code):
    """
    الحصول على بيانات طلب التحقق من الهوية باستخدام رمز التسجيل
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT application_id, full_name, phone_number, address, status
        FROM kyc_application
        WHERE registration_code = %s AND status = 'approved'
        """
        
        cur.execute(query, (registration_code,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            application_data = {
                'application_id': result[0],
                'full_name': result[1],
                'phone_number': result[2],
                'address': result[3],
                'status': result[4]
            }
            return True, application_data
        else:
            return False, "رمز التسجيل غير صالح أو الطلب غير مقبول"
    
    except Exception as e:
        logger.error(f"خطأ في الحصول على بيانات الطلب بواسطة رمز التسجيل: {str(e)}")
        return False, str(e)

def update_telegram_user(user_id, user_name):
    """
    تحديث معلومات مستخدم تلغرام في قاعدة البيانات
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        update_query = """
        INSERT INTO telegram_users (user_id, username, created_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (user_id) 
        DO UPDATE SET username = EXCLUDED.username, updated_at = NOW()
        """
        
        cur.execute(update_query, (user_id, user_name))
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم تحديث معلومات المستخدم {user_name} بنجاح")
        return True
    except Exception as e:
        logger.error(f"خطأ في تحديث معلومات المستخدم: {str(e)}")
        return False

def get_kyc_application(request_id):
    """
    الحصول على معلومات طلب التحقق من الهوية بواسطة رقم الطلب
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = sql.SQL("""
        SELECT * FROM kyc_application
        WHERE application_id = %s
        """)
        
        cur.execute(query, (request_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            # تحويل النتيجة إلى قاموس
            columns = ['id', 'application_id', 'full_name', 'phone_number', 'address', 
                      'id_photo_url', 'selfie_photo_url', 'status', 'registration_code', 
                      'rejection_reason', 'telegram_chat_id', 'welcome_message_id', 'created_at', 'updated_at',
                      'device_info', 'ip_address', 'geo_location']
            
            application_data = dict(zip(columns, result))
            return application_data
        else:
            return None
    except Exception as e:
        logger.error(f"خطأ في الحصول على معلومات الطلب: {str(e)}")
        return None

def approve_application(request_id, admin_full_name, registration_code):
    """
    الموافقة على طلب التحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # التحقق من وجود الطلب
        query = sql.SQL("""
        SELECT * FROM kyc_application
        WHERE application_id = %s
        """)
        
        cur.execute(query, (request_id,))
        result = cur.fetchone()
        
        if not result:
            cur.close()
            conn.close()
            return False, "لم يتم العثور على الطلب"
        
        # تحديث حالة الطلب
        update_query = sql.SQL("""
        UPDATE kyc_application
        SET 
            status = 'approved',
            registration_code = %s,
            rejection_reason = NULL,
            updated_at = NOW()
        WHERE application_id = %s
        """)
        
        cur.execute(update_query, (registration_code, request_id))
        conn.commit()
        
        cur.close()
        conn.close()
        
        logger.info(f"تمت الموافقة على الطلب {request_id} بواسطة {admin_full_name}")
        return True, "تمت الموافقة على الطلب بنجاح"
    except Exception as e:
        logger.error(f"خطأ في الموافقة على الطلب: {str(e)}")
        return False, str(e)

def reject_application(request_id, admin_full_name, reason):
    """
    رفض طلب التحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # التحقق من وجود الطلب
        query = sql.SQL("""
        SELECT * FROM kyc_application
        WHERE application_id = %s
        """)
        
        cur.execute(query, (request_id,))
        result = cur.fetchone()
        
        if not result:
            cur.close()
            conn.close()
            return False, "لم يتم العثور على الطلب"
        
        # تحديث حالة الطلب
        update_query = sql.SQL("""
        UPDATE kyc_application
        SET 
            status = 'rejected',
            rejection_reason = %s,
            registration_code = NULL,
            updated_at = NOW()
        WHERE application_id = %s
        """)
        
        cur.execute(update_query, (reason, request_id))
        conn.commit()
        
        cur.close()
        conn.close()
        
        logger.info(f"تم رفض الطلب {request_id} بواسطة {admin_full_name}")
        return True, "تم رفض الطلب بنجاح"
    except Exception as e:
        logger.error(f"خطأ في رفض الطلب: {str(e)}")
        return False, str(e)

def update_telegram_chat_id(application_id, telegram_chat_id):
    """
    تحديث معرف محادثة تلغرام لطلب التحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        update_query = """
        UPDATE kyc_application
        SET telegram_chat_id = %s, updated_at = NOW()
        WHERE application_id = %s
        """
        
        cur.execute(update_query, (telegram_chat_id, application_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم تحديث معرف محادثة تلغرام للطلب {application_id}")
        return True
    except Exception as e:
        logger.error(f"خطأ في تحديث معرف محادثة تلغرام: {str(e)}")
        return False

def save_kyc_application(application_data):
    """
    حفظ طلب جديد للتحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # إنشاء رقم طلب فريد
        application_id = f"KYC-{datetime.now().strftime('%Y%m%d')}-{application_data['id_suffix']}"
        
        # التحقق من وجود عمود welcome_message_id في الجدول
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'kyc_application' 
            AND column_name = 'welcome_message_id'
        """)
        has_welcome_message_column = cur.fetchone() is not None
        
        # إدراج البيانات في قاعدة البيانات مع مراعاة وجود العمود
        if has_welcome_message_column:
            insert_query = """
            INSERT INTO kyc_application (
                application_id, full_name, phone_number, address, 
                id_photo_url, selfie_photo_url, telegram_chat_id, welcome_message_id,
                device_info, ip_address, geo_location
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING application_id
            """
            
            cur.execute(insert_query, (
                application_id,
                application_data['full_name'],
                application_data['phone_number'],
                application_data['address'],
                application_data['id_photo_url'],
                application_data['selfie_photo_url'],
                application_data.get('telegram_chat_id'),
                application_data.get('welcome_message_id'),
                psycopg2.extras.Json(application_data.get('device_info')) if application_data.get('device_info') else None,
                application_data.get('ip_address'),
                psycopg2.extras.Json(application_data.get('geo_location')) if application_data.get('geo_location') else None
            ))
        else:
            # استعلام بدون عمود welcome_message_id
            insert_query = """
            INSERT INTO kyc_application (
                application_id, full_name, phone_number, address, 
                id_photo_url, selfie_photo_url, telegram_chat_id,
                device_info, ip_address, geo_location
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING application_id
            """
            
            cur.execute(insert_query, (
                application_id,
                application_data['full_name'],
                application_data['phone_number'],
                application_data['address'],
                application_data['id_photo_url'],
                application_data['selfie_photo_url'],
                application_data.get('telegram_chat_id'),
                psycopg2.extras.Json(application_data.get('device_info')) if application_data.get('device_info') else None,
                application_data.get('ip_address'),
                psycopg2.extras.Json(application_data.get('geo_location')) if application_data.get('geo_location') else None
            ))
            
            logger.warning("عمود welcome_message_id غير موجود في جدول kyc_application. تم تجاهله في الإدراج.")
        
        # الحصول على رقم الطلب المُنشأ
        result = cur.fetchone()
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info(f"تم حفظ طلب التحقق من الهوية برقم {result[0]}")
        return True, result[0]
    except Exception as e:
        logger.error(f"خطأ في حفظ طلب التحقق من الهوية: {str(e)}")
        return False, str(e)

def check_application_status(application_id):
    """
    التحقق من حالة طلب التحقق من الهوية
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT status, registration_code, rejection_reason, created_at
        FROM kyc_application
        WHERE application_id = %s
        """
        
        cur.execute(query, (application_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            status_data = {
                'status': result[0],
                'registration_code': result[1],
                'rejection_reason': result[2],
                'created_at': result[3]
            }
            return True, status_data
        else:
            return False, "لم يتم العثور على الطلب"
    except Exception as e:
        logger.error(f"خطأ في التحقق من حالة الطلب: {str(e)}")
        return False, str(e)

def get_user_application_status(telegram_chat_id):
    """
    التحقق من حالة طلب المستخدم باستخدام معرف تلغرام
    
    :param telegram_chat_id: معرف دردشة المستخدم في تلغرام
    :return: (success, data) حيث data إما معلومات الطلب أو رسالة خطأ
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        query = """
        SELECT application_id, status, registration_code, rejection_reason, created_at
        FROM kyc_application
        WHERE telegram_chat_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """
        
        cur.execute(query, (telegram_chat_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            status_data = {
                'application_id': result[0],
                'status': result[1],
                'registration_code': result[2],
                'rejection_reason': result[3],
                'created_at': result[4]
            }
            return True, status_data
        else:
            return False, "لم يتم العثور على طلب لهذا المستخدم"
    except Exception as e:
        logger.error(f"خطأ في التحقق من حالة طلب المستخدم: {str(e)}")
        return False, str(e)

async def get_application_info(application_id):
    """
    الحصول على معلومات طلب KYC
    """
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # استعلام للحصول على معلومات الطلب
        query = """
        SELECT application_id, full_name, phone_number, telegram_chat_id, status, registration_code, rejection_reason, 
               device_info, ip_address, geo_location
        FROM kyc_application
        WHERE application_id = %s
        """
        
        cur.execute(query, (application_id,))
        result = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if result:
            # تحويل النتيجة إلى قاموس
            app_info = {
                "application_id": result[0],
                "full_name": result[1],
                "phone_number": result[2],
                "telegram_chat_id": result[3],
                "status": result[4],
                "registration_code": result[5],
                "rejection_reason": result[6],
                "device_info": result[7] if result[7] else {},
                "ip_address": result[8] if result[8] else "غير متاح",
                "geo_location": result[9] if result[9] else {}
            }
            return app_info
        else:
            return None
    
    except Exception as e:
        logger.error(f"خطأ في الحصول على معلومات الطلب: {str(e)}")
        return None

async def get_application_by_telegram_id(telegram_chat_id):
    """
    البحث عن طلب بناءً على معرف تلغرام
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        query = """
        SELECT application_id, full_name, phone_number, telegram_chat_id, status, 
               registration_code, rejection_reason, device_info, ip_address, geo_location,
               to_char(created_at, 'YYYY-MM-DD HH24:MI:SS') as created_at
        FROM kyc_application
        WHERE telegram_chat_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """
        
        cur.execute(query, (telegram_chat_id,))
        application = cur.fetchone()
        
        return application
    except Exception as e:
        logger.error(f"خطأ في البحث عن طلب بناءً على معرف تلغرام: {str(e)}")
        return None
    finally:
        if conn:
            conn.close()

# إذا تم تشغيل الملف مباشرة
if __name__ == '__main__':
    create_tables()
