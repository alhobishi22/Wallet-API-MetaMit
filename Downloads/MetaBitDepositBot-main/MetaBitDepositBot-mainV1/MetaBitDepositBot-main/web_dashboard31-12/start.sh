#!/bin/bash

# تثبيت المتطلبات
echo "جاري تثبيت المتطلبات..."
pip install -r requirements.txt

# تشغيل لوحة التحكم
echo "جاري بدء لوحة التحكم..."
python app.py