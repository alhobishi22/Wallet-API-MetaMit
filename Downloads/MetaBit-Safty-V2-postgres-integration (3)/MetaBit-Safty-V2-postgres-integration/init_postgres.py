from app import app, db, User
from werkzeug.security import generate_password_hash
from flask_migrate import upgrade
import traceback
import sys
import logging
from sqlalchemy import inspect, text

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_postgres_db():
    with app.app_context():
        try:
            # طباعة معلومات عن قاعدة البيانات
            logger.info(f"نوع قاعدة البيانات: {db.engine.name}")
            logger.info(f"رابط قاعدة البيانات: {str(db.engine.url).split('@')[0]}@***")
            
            # التحقق من الجداول الموجودة
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"الجداول الموجودة: {existing_tables}")
            
            # إنشاء الجداول إذا لم تكن موجودة
            logger.info("جاري إنشاء الجداول...")
            db.create_all()
            
            # التحقق مرة أخرى من الجداول
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"الجداول بعد الإنشاء: {existing_tables}")
            
            # التحقق من وجود جدول المستخدمين
            if 'users' not in existing_tables:
                logger.error("جدول المستخدمين غير موجود! محاولة إنشائه بشكل صريح...")
                try:
                    # محاولة إنشاء جدول المستخدمين بشكل صريح
                    with db.engine.connect() as conn:
                        conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS users (
                            id SERIAL PRIMARY KEY,
                            username VARCHAR(80) UNIQUE NOT NULL,
                            email VARCHAR(120) UNIQUE NOT NULL,
                            password_hash VARCHAR(128),
                            is_admin BOOLEAN DEFAULT FALSE
                        )
                        """))
                        conn.commit()
                    logger.info("تم إنشاء جدول المستخدمين يدويًا باستخدام SQL")
                except Exception as e:
                    logger.error(f"خطأ في إنشاء جدول المستخدمين باستخدام SQL: {str(e)}")
                    return False
            else:
                logger.info("تم إنشاء الجداول بنجاح")
            
            # التحقق من وجود مستخدم مشرف
            try:
                admin = User.query.filter_by(username='admin').first()
                
                if not admin:
                    # إنشاء مستخدم مشرف جديد
                    new_admin = User(
                        username='admin',
                        email='admin@metabit-safety.com',
                        is_admin=True
                    )
                    new_admin.set_password('admin123')
                    
                    db.session.add(new_admin)
                    db.session.commit()
                    logger.info("تم إنشاء مستخدم مشرف جديد:")
                    logger.info("اسم المستخدم: admin")
                    logger.info("كلمة المرور: admin123")
                    logger.info("البريد الإلكتروني: admin@metabit-safety.com")
                else:
                    logger.info("المستخدم المشرف موجود بالفعل")
                    # تحديث كلمة المرور للمستخدم المشرف
                    admin.set_password('admin123')
                    admin.is_admin = True
                    admin.email = 'admin@metabit-safety.com'
                    db.session.commit()
                    logger.info("تم تحديث بيانات المستخدم المشرف")
            except Exception as e:
                logger.error(f"خطأ في التحقق من المستخدم المشرف: {str(e)}")
                db.session.rollback()
                return False
                
            return True
        except Exception as e:
            logger.error(f"حدث خطأ أثناء تهيئة قاعدة البيانات: {str(e)}")
            traceback.print_exc(file=sys.stdout)
            return False

if __name__ == "__main__":
    logger.info("جاري تهيئة قاعدة بيانات PostgreSQL...")
    success = init_postgres_db()
    if success:
        logger.info("تم تهيئة قاعدة البيانات بنجاح!")
    else:
        logger.error("فشلت عملية تهيئة قاعدة البيانات!")
