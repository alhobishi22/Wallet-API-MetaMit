from app import db, app
import database
import logging
import os

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def init_db():
    """
    تهيئة قاعدة البيانات وإنشاء الجداول
    """
    # أولاً استخدام SQLAlchemy لإنشاء الجداول
    with app.app_context():
        # حذف جميع الجداول الموجودة
        db.drop_all()
        
        # إنشاء جميع الجداول
        db.create_all()
        
        logger.info("تم تهيئة قاعدة بيانات SQLAlchemy بنجاح!")
    
    # الآن إنشاء جداول قاعدة البيانات باستخدام وظائف database.py
    success = database.create_tables()
    
    if success:
        logger.info("تم تهيئة جداول قاعدة البيانات بنجاح!")
    else:
        logger.error("فشل في تهيئة جداول قاعدة البيانات")

if __name__ == '__main__':
    init_db()
