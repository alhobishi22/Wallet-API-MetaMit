import os
import sys
import traceback
import logging
from sqlalchemy import inspect, text, MetaData
from app import app, db, User

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def reset_database():
    with app.app_context():
        try:
            # طباعة معلومات عن متغيرات البيئة
            logger.info(f"DATABASE_URL exists: {os.environ.get('DATABASE_URL') is not None}")
            database_url = os.environ.get('DATABASE_URL', '')
            if database_url:
                # إخفاء المعلومات الحساسة
                masked_url = database_url.split('@')[0] + '@***' if '@' in database_url else database_url
                logger.info(f"DATABASE_URL: {masked_url}")
            
            # التحقق من نوع قاعدة البيانات
            logger.info(f"Database type: {db.engine.name}")
            
            # التحقق من الجداول الموجودة
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"Existing tables before reset: {existing_tables}")
            
            # حذف جميع الجداول
            logger.info("Dropping all tables...")
            
            # استخدام طريقة مختلفة اعتمادًا على نوع قاعدة البيانات
            if db.engine.name == 'postgresql':
                # لـ PostgreSQL، يمكننا استخدام CASCADE
                with db.engine.connect() as conn:
                    conn.execute(text("DROP SCHEMA public CASCADE"))
                    conn.execute(text("CREATE SCHEMA public"))
                    conn.execute(text("GRANT ALL ON SCHEMA public TO postgres"))
                    conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
                logger.info("Dropped and recreated public schema in PostgreSQL")
            else:
                # لقواعد البيانات الأخرى، نستخدم الطريقة العادية
                try:
                    metadata = MetaData()
                    metadata.reflect(bind=db.engine)
                    metadata.drop_all(db.engine)
                except Exception as e:
                    logger.error(f"Error dropping tables with metadata: {str(e)}")
                    # محاولة أخرى باستخدام drop_all
                    db.drop_all()
            
            # التحقق من الجداول بعد الحذف
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"Existing tables after drop: {existing_tables}")
            
            # إنشاء جميع الجداول من جديد
            logger.info("Creating all tables...")
            try:
                # إنشاء الجداول باستخدام SQLAlchemy
                db.create_all()
                
                # تحديث المفتش وإعادة التحقق من الجداول
                inspector = inspect(db.engine)
                existing_tables = inspector.get_table_names()
                logger.info(f"Existing tables after creation: {existing_tables}")
                
                # إذا لم يتم إنشاء جدول المستخدمين، قم بإنشائه بشكل صريح
                if 'users' not in existing_tables:
                    logger.error("Users table was not created! Attempting to create it explicitly...")
                    
                    # إنشاء جدول المستخدمين بشكل صريح
                    User.__table__.create(db.engine, checkfirst=True)
                    
                    # تحديث المفتش وإعادة التحقق
                    inspector = inspect(db.engine)
                    existing_tables = inspector.get_table_names()
                    logger.info(f"Tables after explicit creation: {existing_tables}")
            except Exception as e:
                logger.error(f"Error creating tables: {str(e)}")
                
            # تحديث المفتش وإعادة التحقق مرة أخرى
            inspector = inspect(db.engine)
            existing_tables = inspector.get_table_names()
            logger.info(f"Final tables list: {existing_tables}")
            
            # إنشاء مستخدم مشرف
            logger.info("Creating admin user...")
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
                logger.info("Admin user created successfully")
                logger.info("Username: admin")
                logger.info("Password: admin123")
                logger.info("Email: admin@metabit-safety.com")
            else:
                logger.info("Admin user already exists")
            
            logger.info("Database reset and initialization completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error during database reset: {str(e)}")
            traceback.print_exc(file=sys.stdout)
            return False

if __name__ == "__main__":
    logger.info("Starting database reset...")
    success = reset_database()
    if success:
        logger.info("Database reset completed successfully")
    else:
        logger.error("Database reset failed")
