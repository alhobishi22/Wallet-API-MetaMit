import os
import logging
import hashlib
import secrets
from dotenv import load_dotenv
import database

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# تحميل متغيرات البيئة
load_dotenv()

def generate_salt():
    """
    إنشاء salt عشوائي للتشفير
    """
    return secrets.token_hex(16)

def hash_password(password, salt=None):
    """
    تشفير كلمة المرور باستخدام SHA-256 مع salt
    """
    if salt is None:
        salt = generate_salt()
    
    # دمج كلمة المرور مع salt وتشفيرها
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    
    return password_hash, salt

def verify_password(password, stored_hash, salt):
    """
    التحقق من صحة كلمة المرور
    """
    # حساب التشفير باستخدام كلمة المرور المدخلة و salt المخزن
    calculated_hash, _ = hash_password(password, salt)
    
    # مقارنة التشفير المحسوب مع التشفير المخزن
    return calculated_hash == stored_hash

def register_user(username, password, email, full_name, registration_code=None):
    """
    تسجيل مستخدم جديد
    """
    try:
        # التحقق من أن اسم المستخدم غير مستخدم بالفعل
        if database.user_exists(username):
            return False, "اسم المستخدم مستخدم بالفعل"
        
        # تشفير كلمة المرور
        password_hash, salt = hash_password(password)
        
        # إنشاء بيانات المستخدم
        user_data = {
            'username': username,
            'password_hash': password_hash,
            'salt': salt,
            'email': email,
            'full_name': full_name,
            'registration_code': registration_code
        }
        
        # حفظ المستخدم في قاعدة البيانات
        success, message = database.save_user(user_data)
        
        if success:
            logger.info(f"تم تسجيل المستخدم بنجاح: {username}")
            return True, "تم تسجيل المستخدم بنجاح"
        else:
            logger.error(f"فشل في تسجيل المستخدم: {message}")
            return False, message
    
    except Exception as e:
        logger.error(f"خطأ في تسجيل المستخدم: {str(e)}")
        return False, f"حدث خطأ أثناء تسجيل المستخدم: {str(e)}"

def login_user(username, password):
    """
    تسجيل دخول المستخدم
    """
    try:
        # الحصول على بيانات المستخدم من قاعدة البيانات
        success, user_data = database.get_user(username)
        
        if not success:
            logger.warning(f"محاولة تسجيل دخول لمستخدم غير موجود: {username}")
            return False, "اسم المستخدم أو كلمة المرور غير صحيحة"
        
        # التحقق من كلمة المرور
        if verify_password(password, user_data['password_hash'], user_data['salt']):
            logger.info(f"تم تسجيل دخول المستخدم بنجاح: {username}")
            return True, user_data
        else:
            logger.warning(f"كلمة مرور خاطئة للمستخدم: {username}")
            return False, "اسم المستخدم أو كلمة المرور غير صحيحة"
    
    except Exception as e:
        logger.error(f"خطأ في تسجيل دخول المستخدم: {str(e)}")
        return False, f"حدث خطأ أثناء تسجيل الدخول: {str(e)}"

def verify_registration_code(registration_code):
    """
    التحقق من صحة رمز التسجيل
    """
    try:
        # التحقق من وجود رمز التسجيل في قاعدة البيانات
        success, application_data = database.get_application_by_code(registration_code)
        
        if success:
            logger.info(f"تم التحقق من رمز التسجيل بنجاح: {registration_code}")
            return True, application_data
        else:
            logger.warning(f"رمز تسجيل غير صالح: {registration_code}")
            return False, "رمز التسجيل غير صالح"
    
    except Exception as e:
        logger.error(f"خطأ في التحقق من رمز التسجيل: {str(e)}")
        return False, f"حدث خطأ أثناء التحقق من رمز التسجيل: {str(e)}"

def change_password(username, old_password, new_password):
    """
    تغيير كلمة مرور المستخدم
    """
    try:
        # التحقق من صحة بيانات تسجيل الدخول
        success, user_data = login_user(username, old_password)
        
        if not success:
            return False, "كلمة المرور الحالية غير صحيحة"
        
        # تشفير كلمة المرور الجديدة
        new_password_hash, new_salt = hash_password(new_password)
        
        # تحديث كلمة المرور في قاعدة البيانات
        update_success, message = database.update_user_password(username, new_password_hash, new_salt)
        
        if update_success:
            logger.info(f"تم تغيير كلمة مرور المستخدم بنجاح: {username}")
            return True, "تم تغيير كلمة المرور بنجاح"
        else:
            logger.error(f"فشل في تغيير كلمة مرور المستخدم: {message}")
            return False, message
    
    except Exception as e:
        logger.error(f"خطأ في تغيير كلمة مرور المستخدم: {str(e)}")
        return False, f"حدث خطأ أثناء تغيير كلمة المرور: {str(e)}"

def reset_password_request(email):
    """
    طلب إعادة تعيين كلمة المرور
    """
    try:
        # التحقق من وجود البريد الإلكتروني في قاعدة البيانات
        success, username = database.get_user_by_email(email)
        
        if not success:
            logger.warning(f"محاولة إعادة تعيين كلمة المرور لبريد إلكتروني غير موجود: {email}")
            return False, "البريد الإلكتروني غير مسجل"
        
        # إنشاء رمز إعادة تعيين كلمة المرور
        reset_token = secrets.token_hex(16)
        expiry_hours = 24  # صلاحية الرمز 24 ساعة
        
        # حفظ رمز إعادة التعيين في قاعدة البيانات
        token_success, message = database.save_reset_token(username, reset_token, expiry_hours)
        
        if token_success:
            logger.info(f"تم إنشاء رمز إعادة تعيين كلمة المرور للمستخدم: {username}")
            
            # هنا يمكن إضافة كود لإرسال بريد إلكتروني يحتوي على رابط إعادة التعيين
            # ...
            
            return True, reset_token
        else:
            logger.error(f"فشل في إنشاء رمز إعادة تعيين كلمة المرور: {message}")
            return False, message
    
    except Exception as e:
        logger.error(f"خطأ في طلب إعادة تعيين كلمة المرور: {str(e)}")
        return False, f"حدث خطأ أثناء طلب إعادة تعيين كلمة المرور: {str(e)}"

def reset_password_confirm(reset_token, new_password):
    """
    تأكيد إعادة تعيين كلمة المرور باستخدام الرمز
    """
    try:
        # التحقق من صحة رمز إعادة التعيين
        success, username = database.verify_reset_token(reset_token)
        
        if not success:
            logger.warning(f"محاولة استخدام رمز إعادة تعيين غير صالح: {reset_token}")
            return False, "رمز إعادة التعيين غير صالح أو منتهي الصلاحية"
        
        # تشفير كلمة المرور الجديدة
        new_password_hash, new_salt = hash_password(new_password)
        
        # تحديث كلمة المرور في قاعدة البيانات
        update_success, message = database.update_user_password(username, new_password_hash, new_salt)
        
        if update_success:
            # حذف رمز إعادة التعيين بعد استخدامه
            database.delete_reset_token(reset_token)
            
            logger.info(f"تم إعادة تعيين كلمة مرور المستخدم بنجاح: {username}")
            return True, "تم إعادة تعيين كلمة المرور بنجاح"
        else:
            logger.error(f"فشل في إعادة تعيين كلمة مرور المستخدم: {message}")
            return False, message
    
    except Exception as e:
        logger.error(f"خطأ في إعادة تعيين كلمة المرور: {str(e)}")
        return False, f"حدث خطأ أثناء إعادة تعيين كلمة المرور: {str(e)}"
