#!/bin/bash
# تشغيل كلا العمليتين باستخدام honcho
echo "Starting services with honcho..."
echo "PORT=$PORT"
echo "PYTHONPATH=$PYTHONPATH"

# تأكد من تثبيت numpy أولاً بالإصدار المحدد
pip uninstall -y numpy pandas
pip install numpy==1.24.3
pip install pandas==2.0.3

# تأكد من تثبيت بقية المتطلبات
pip install -r requirements.txt

# عرض المكتبات المثبتة للتشخيص
pip list | grep -E 'numpy|pandas'

# تشغيل الخدمات
honcho start
