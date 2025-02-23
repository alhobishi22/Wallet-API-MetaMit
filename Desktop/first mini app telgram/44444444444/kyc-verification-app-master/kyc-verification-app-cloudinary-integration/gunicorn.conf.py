import os

# تكوين المنفذ
port = int(os.environ.get('PORT', 51776))
bind = f'0.0.0.0:{port}'

# تكوين العمليات
workers = 1  # نستخدم عامل واحد فقط بسبب البوت
worker_class = 'sync'  # نستخدم عامل متزامن بسبب البوت
threads = 4

# تكوين التسجيل
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# تكوين التطبيق
preload_app = True
reload = True