import asyncio
import aiosqlite
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE = 'bot_database.db'

async def add_transfer_issuer_column():
    """إضافة عمود جهة إصدار الحوالة"""
    try:
        db = await aiosqlite.connect(DATABASE)
        await db.execute("""
            ALTER TABLE withdrawal_requests 
            ADD COLUMN transfer_issuer TEXT
        """)
        await db.commit()
        await db.close()
        logger.info("✅ تم إضافة عمود جهة إصدار الحوالة بنجاح")
    except Exception as e:
        if "duplicate column name" not in str(e):
            logger.error(f"❌ خطأ في إضافة العمود: {e}")
            raise
        else:
            logger.info("العمود موجود مسبقاً")

if __name__ == "__main__":
    asyncio.run(add_transfer_issuer_column())