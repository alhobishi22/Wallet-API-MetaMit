#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
مخطط لترقية قاعدة البيانات
يقوم بإضافة عمود updated_at إلى جدول withdrawal_requests
لدعم تحسينات تتبع الحالة ومنع حالات التسابق
"""

import asyncio
import asyncpg
import logging
import os
import sys
import ssl
import socket

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("database_upgrade")

async def get_connection():
    """الحصول على اتصال بقاعدة البيانات"""
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
    
    try:
        # اختبار حل اسم النطاق
        ip = socket.gethostbyname(connection_params['host'])
        logger.info(f"تم حل اسم النطاق بنجاح: {ip}")
        
        # إنشاء اتصال مباشر
        conn = await asyncpg.connect(**connection_params)
        logger.info("✅ تم الاتصال بقاعدة البيانات بنجاح")
        return conn
    except Exception as e:
        logger.error(f"❌ خطأ في الاتصال بقاعدة البيانات: {str(e)}")
        raise

async def release_connection(conn):
    """إغلاق الاتصال بقاعدة البيانات"""
    if conn:
        await conn.close()

async def add_updated_at_column():
    """إضافة عمود updated_at إلى جدول withdrawal_requests"""
    conn = None
    try:
        conn = await get_connection()
        
        # التحقق من وجود العمود
        column_exists = await conn.fetchval("""
            SELECT EXISTS (
                SELECT 1 
                FROM information_schema.columns 
                WHERE table_name = 'withdrawal_requests' 
                AND column_name = 'updated_at'
            )
        """)
        
        if column_exists:
            logger.info("✅ عمود updated_at موجود بالفعل في جدول withdrawal_requests")
            return
        
        # إضافة العمود إذا لم يكن موجودًا
        await conn.execute("""
            ALTER TABLE withdrawal_requests
            ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        """)
        
        # تحديث قيم العمود الجديد لتساوي created_at للسجلات الحالية
        await conn.execute("""
            UPDATE withdrawal_requests
            SET updated_at = created_at
            WHERE updated_at IS NULL
        """)
        
        logger.info("✅ تمت إضافة عمود updated_at إلى جدول withdrawal_requests بنجاح")
        
    except Exception as e:
        logger.error(f"❌ خطأ في إضافة عمود updated_at: {str(e)}")
        raise
    finally:
        if conn:
            await release_connection(conn)

async def main():
    """الوظيفة الرئيسية لترقية قاعدة البيانات"""
    logger.info("🔄 بدء ترقية قاعدة البيانات...")
    await add_updated_at_column()
    logger.info("✅ اكتملت ترقية قاعدة البيانات بنجاح")

if __name__ == "__main__":
    asyncio.run(main())
