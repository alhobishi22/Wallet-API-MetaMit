import os
import sys
import subprocess
import threading
import time
import signal
import psutil
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# إعداد السجلات
def setup_logging():
    """إعداد نظام السجلات للتطبيق"""
    # إنشاء مجلد السجلات إذا لم يكن موجودًا
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # إعداد مسجل الجذر
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # تنسيق السجلات
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # مسجل الملف
    file_handler = RotatingFileHandler(
        'logs/system.log',
        maxBytes=10240,
        backupCount=10
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # مسجل وحدة التحكم
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # إضافة المسجلات إلى مسجل الجذر
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# إعداد السجلات
logger = setup_logging()

def run_process(command, process_name):
    """Run a process with the given command and name."""
    logger.info(f"Starting {process_name}...")
    
    try:
        # Use shell=True for Windows to properly handle Python interpreter
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Print output in real-time with process name prefix
        for line in process.stdout:
            line_stripped = line.strip()
            if line_stripped:  # تجنب طباعة الأسطر الفارغة
                logger.info(f"[{process_name}] {line_stripped}")
        
        # التحقق من حالة الخروج
        return_code = process.wait()
        if return_code != 0:
            logger.error(f"{process_name} exited with code {return_code}")
        
        return process
    except Exception as e:
        logger.error(f"Error starting {process_name}: {str(e)}")
        return None

def start_app():
    """Start the Flask web application."""
    return run_process("python app.py", "Flask App")

def start_bot():
    """Start the Telegram bot and FastAPI server."""
    return run_process("python main.py", "Telegram Bot")

def kill_process_and_children(pid):
    """Kill a process and all its children."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        for child in children:
            try:
                child.terminate()
                logger.info(f"Terminated child process: {child.pid}")
            except Exception as e:
                logger.error(f"Error terminating child process {child.pid}: {str(e)}")
        
        parent.terminate()
        logger.info(f"Terminated parent process: {pid}")
    except Exception as e:
        logger.error(f"Error terminating process {pid}: {str(e)}")

def main():
    """Run both the Flask app and Telegram bot concurrently."""
    logger.info("=== Starting MetaBit KYC System ===")
    
    # Start processes in separate threads
    app_thread = threading.Thread(target=start_app)
    bot_thread = threading.Thread(target=start_bot)
    
    app_thread.daemon = True
    bot_thread.daemon = True
    
    app_thread.start()
    time.sleep(2)  # Small delay to avoid output mixing
    bot_thread.start()
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n=== Shutting down all services... ===")
        
        # Find and kill all python processes started by this script
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] == 'python.exe' and proc.pid != current_pid:
                    cmdline = ' '.join(proc.info['cmdline'])
                    if 'app.py' in cmdline or 'main.py' in cmdline:
                        logger.info(f"Terminating process: {proc.pid} ({cmdline})")
                        kill_process_and_children(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        
        logger.info("=== All services stopped ===")

if __name__ == "__main__":
    main()
