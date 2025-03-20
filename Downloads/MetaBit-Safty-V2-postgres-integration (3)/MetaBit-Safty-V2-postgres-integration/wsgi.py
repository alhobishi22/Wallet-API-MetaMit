import os
import sys
import logging
import traceback
from sqlalchemy import inspect, text
from app import app, db, User

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def initialize_database():
    with app.app_context():
        try:
            # التحقق من نوع قاعدة البيانات
            logger.info(f"Database type: {db.engine.name}")
            
            # التحقق من الجداول الموجودة
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"Existing tables: {existing_tables}")
            
            # التحقق من وجود جدول المستخدمين
            if 'users' not in existing_tables:
                logger.warning("Users table does not exist. Creating tables...")
                # إنشاء جميع الجداول
                db.create_all()
                
                # التحقق مرة أخرى
                inspector = inspect(db.engine)
                existing_tables = inspector.get_table_names()
                logger.info(f"Tables after creation: {existing_tables}")
                
                if 'users' not in existing_tables:
                    logger.error("Failed to create users table! Trying explicit creation...")
                    try:
                        # محاولة إنشاء جدول المستخدمين بشكل صريح
                        with db.engine.connect() as conn:
                            if db.engine.name == 'postgresql':
                                conn.execute(text("""
                                CREATE TABLE IF NOT EXISTS users (
                                    id SERIAL PRIMARY KEY,
                                    username VARCHAR(80) UNIQUE NOT NULL,
                                    email VARCHAR(120) UNIQUE NOT NULL,
                                    password_hash VARCHAR(128),
                                    is_admin BOOLEAN DEFAULT FALSE
                                )
                                """))
                            else:
                                conn.execute(text("""
                                CREATE TABLE IF NOT EXISTS users (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    username VARCHAR(80) UNIQUE NOT NULL,
                                    email VARCHAR(120) UNIQUE NOT NULL,
                                    password_hash VARCHAR(128),
                                    is_admin BOOLEAN DEFAULT FALSE
                                )
                                """))
                            conn.commit()
                        logger.info("Created users table manually with SQL")
                    except Exception as e:
                        logger.error(f"Error creating users table with SQL: {str(e)}")
                        return False
            
            # التحقق من وجود مستخدم مشرف
            try:
                admin = User.query.filter_by(username='admin').first()
                if not admin:
                    logger.warning("Admin user does not exist. Creating admin user...")
                    # استدعاء سكريبت إنشاء المستخدم المشرف
                    from create_admin import create_admin
                    success = create_admin()
                    if not success:
                        logger.error("Failed to create admin user!")
                        return False
            except Exception as e:
                logger.error(f"Error checking for admin user: {str(e)}")
                db.session.rollback()
                return False
            
            return True
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            traceback.print_exc(file=sys.stdout)
            return False

# تهيئة قاعدة البيانات عند بدء التشغيل
initialize_database()

# تصدير التطبيق
application = app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
