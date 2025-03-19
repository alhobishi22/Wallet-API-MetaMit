FROM python:3.10-slim

# تثبيت المكتبات الأساسية
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /data/uploads /data/config /data/logs
# نسخ ملفات المتطلبات أولاً لتحسين التخزين المؤقت
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn

# نسخ باقي الملفات
COPY . .

# تعيين متغيرات البيئة
ENV PORT=5000
ENV ALT_PORT=8080
ENV FASTAPI_PORT=8000
ENV ALT_FASTAPI_PORT=9000
ENV PYTHONUNBUFFERED=1

# تشغيل التطبيق
CMD ["python", "run_all.py"]
