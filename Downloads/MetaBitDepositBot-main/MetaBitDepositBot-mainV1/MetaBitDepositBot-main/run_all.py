import asyncio
import sys
import logging
import multiprocessing
import os
import signal
from main import main as run_bot
sys.path.append("web_dashboard31-12")
from app import app as flask_app
from dashboard_api import app as fastapi_app
import uvicorn
from threading import Thread, Event
from dotenv import load_dotenv
from services.monitoring_service import monitoring_service
import psutil
from functools import partial
import socket

# تحميل المتغيرات البيئية
load_dotenv()

# تكوين التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("unified.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# إنشاء حدث للإيقاف
stop_event = Event()

def signal_handler(signum, frame):
    """معالج إشارات التوقف"""
    logger.info(f"تم استلام إشارة الإيقاف {signum}")
    stop_event.set()

def is_port_in_use(port: int) -> bool:
    """التحقق مما إذا كان المنفذ مستخدماً"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('0.0.0.0', port))
            return False
        except OSError:
            return True

def find_available_port(start_port: int, max_attempts: int = 10) -> int:
    """البحث عن منفذ متاح"""
    for port in range(start_port, start_port + max_attempts):
        if not is_port_in_use(port):
            return port
    raise RuntimeError(f"لم يتم العثور على منفذ متاح بعد {max_attempts} محاولات")

def run_flask_app(stop_event):
    """تشغيل تطبيق Flask"""
    try:
        base_port = int(os.environ.get('PORT', 10000))
        port = find_available_port(base_port)
        logger.info(f"بدء تشغيل لوحة التحكم Flask على المنفذ {port}")
        
        # تعيين وقت التوقف للخادم
        flask_app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # ساعة واحدة
        flask_app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 300   # 5 دقائق
        
        # تشغيل التطبيق مع إمكانية الإيقاف
        flask_app.run(
            host='0.0.0.0',
            port=port,
            use_reloader=False,
            threaded=True
        )
        
    except Exception as e:
        logger.error(f"خطأ في تشغيل Flask: {e}")
        stop_event.set()

def run_fastapi(stop_event):
    """تشغيل تطبيق FastAPI"""
    try:
        base_port = int(os.environ.get('FASTAPI_PORT', 8000))
        port = find_available_port(base_port)
        logger.info(f"بدء تشغيل واجهة FastAPI على المنفذ {port}")
        
        config = uvicorn.Config(
            fastapi_app,
            host="0.0.0.0",
            port=port,
            log_level="info",
            timeout_keep_alive=30,
            limit_concurrency=100,
            loop="asyncio"
        )
        server = uvicorn.Server(config)
        server.run()
        
    except Exception as e:
        logger.error(f"خطأ في تشغيل FastAPI: {e}")
        stop_event.set()

async def monitor_services(stop_event):
    """مراقبة الخدمات وإعادة تشغيلها إذا لزم الأمر"""
    try:
        while not stop_event.is_set():
            # مراقبة استخدام الموارد
            memory_usage = monitoring_service.get_memory_usage()
            cpu_usage = monitoring_service.get_cpu_usage()
            disk_usage = monitoring_service.get_disk_usage()
            
            # تسجيل معلومات النظام
            logger.info(
                f"معلومات النظام - "
                f"الذاكرة: {memory_usage:.1f}MB, "
                f"المعالج: {cpu_usage:.1f}%, "
                f"القرص: {disk_usage['percent']}% مستخدم"
            )
            
            # التحقق من حالة الخدمات
            if memory_usage > 1000:  # أكثر من 1GB
                logger.warning("⚠️ استخدام الذاكرة مرتفع جداً")
            
            if cpu_usage > 80:
                logger.warning("⚠️ استخدام المعالج مرتفع جداً")
            
            if disk_usage['percent'] > 90:
                logger.warning("⚠️ مساحة القرص منخفضة جداً")
            
            await asyncio.sleep(30)  # فحص كل 30 ثانية
            
    except Exception as e:
        logger.error(f"خطأ في مراقبة الخدمات: {e}")
        stop_event.set()

async def run_all():
    """تشغيل جميع الخدمات"""
    try:
        # تسجيل معالجات الإشارات
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # تشغيل البوت في مهمة منفصلة
        bot_task = asyncio.create_task(run_bot())
        logger.info("✅ تم بدء تشغيل البوت")

        # تشغيل تطبيق Flask في thread منفصل
        flask_thread = Thread(target=run_flask_app, args=(stop_event,))
        flask_thread.daemon = True
        flask_thread.start()
        logger.info("✅ تم بدء تشغيل لوحة التحكم Flask")

        # تشغيل FastAPI في thread منفصل
        fastapi_thread = Thread(target=run_fastapi, args=(stop_event,))
        fastapi_thread.daemon = True
        fastapi_thread.start()
        logger.info("✅ تم بدء تشغيل واجهة FastAPI")

        # بدء مهمة المراقبة
        monitor_task = asyncio.create_task(monitor_services(stop_event))
        logger.info("✅ تم بدء خدمة المراقبة")

        # انتظار حتى يتم إيقاف البرنامج
        try:
            while not stop_event.is_set():
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("تم استلام إشارة الإيقاف")
        finally:
            # إيقاف جميع المهام
            stop_event.set()
            tasks = [bot_task, monitor_task]
            for task in tasks:
                if not task.done():
                    task.cancel()
            
            # انتظار انتهاء جميع المهام
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("✅ تم إيقاف جميع الخدمات بنجاح")

    except Exception as e:
        logger.error(f"❌ حدث خطأ: {str(e)}")
        stop_event.set()
        sys.exit(1)

if __name__ == '__main__':
    try:
        # تعيين سياسة الحلقة لنظام Windows
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
        # تشغيل البرنامج
        multiprocessing.freeze_support()  # مطلوب لـ Windows
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logger.info("تم إيقاف البرنامج بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ حدث خطأ غير متوقع: {str(e)}")
        sys.exit(1)