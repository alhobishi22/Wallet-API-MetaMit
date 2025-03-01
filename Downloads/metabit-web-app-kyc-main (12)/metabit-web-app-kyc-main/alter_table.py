"""
سكريبت لتعديل جدول kyc_application وإضافة أعمدة لمعلومات الجهاز والموقع الجغرافي
"""
import os
import logging
import psycopg2
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# الحصول على رابط قاعدة البيانات من متغيرات البيئة
DATABASE_URL = os.getenv('DATABASE_URL')

def alter_table():
    """
    تعديل جدول kyc_application لإضافة أعمدة جديدة
    """
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # التحقق من وجود الأعمدة قبل إضافتها
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'kyc_application' 
            AND column_name IN ('device_info', 'ip_address', 'geo_location')
        """)
        existing_columns = [col[0] for col in cur.fetchall()]
        
        # إضافة عمود device_info إذا لم يكن موجودًا
        if 'device_info' not in existing_columns:
            cur.execute("""
                ALTER TABLE kyc_application 
                ADD COLUMN device_info JSONB
            """)
            logger.info("تم إضافة عمود device_info بنجاح")
        
        # إضافة عمود ip_address إذا لم يكن موجودًا
        if 'ip_address' not in existing_columns:
            cur.execute("""
                ALTER TABLE kyc_application 
                ADD COLUMN ip_address VARCHAR(50)
            """)
            logger.info("تم إضافة عمود ip_address بنجاح")
        
        # إضافة عمود geo_location إذا لم يكن موجودًا
        if 'geo_location' not in existing_columns:
            cur.execute("""
                ALTER TABLE kyc_application 
                ADD COLUMN geo_location JSONB
            """)
            logger.info("تم إضافة عمود geo_location بنجاح")
        
        conn.commit()
        cur.close()
        conn.close()
        
        logger.info("تم تعديل جدول kyc_application بنجاح")
        return True
    
    except Exception as e:
        logger.error(f"خطأ في تعديل جدول kyc_application: {str(e)}")
        return False

if __name__ == "__main__":
    alter_table()
