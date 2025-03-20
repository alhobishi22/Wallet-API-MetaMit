# نظام MetaBit Safety لإدارة البلاغات

نظام متكامل لإدارة بلاغات الاحتيال والمديونية مع دعم للبحث المتقدم وتتبع المحتالين.

## المميزات

- تسجيل بلاغات الاحتيال والمديونية
- دعم للحقول المخصصة
- بحث متقدم في البلاغات
- لوحة تحكم للمشرفين
- تصدير واستيراد البيانات بصيغة Excel
- دعم لرفع الملفات والصور
- بوت تيليجرام للإشعارات والتحكم عن بعد
- واجهة مستخدم بالعربية سهلة الاستخدام
- معالجة خاصة لقيم "nan" وإخفائها من واجهة المستخدم

## متطلبات النظام

- Python 3.11 أو أحدث
- قاعدة بيانات PostgreSQL
- متطلبات Python المذكورة في ملف requirements.txt

## الإعداد المحلي

1. قم بتثبيت المتطلبات:
   ```
   pip install -r requirements.txt
   ```

2. قم بإعداد ملف `.env` بالمتغيرات البيئية:
   ```
   SECRET_KEY=your-secret-key-here
   DATABASE_URL=postgresql://username:password@localhost/dbname
   TELEGRAM_BOT_TOKEN=your-telegram-bot-token
   FLASK_APP=app.py
   FLASK_ENV=development
   DEBUG=True
   ```

3. قم بإنشاء قاعدة البيانات:
   ```
   python init_postgres.py
   ```

4. قم بتشغيل التطبيق:
   ```
   python run_both.py
   ```

## النشر على Render

1. قم بإنشاء قاعدة بيانات PostgreSQL على Render

2. قم بتعديل ملف `.env` ليستخدم رابط قاعدة البيانات على Render:
   ```
   DATABASE_URL=postgresql://username:password@host/dbname
   ```

3. قم بتعديل ملف `render.yaml` ليستخدم رابط قاعدة البيانات الصحيح

4. قم بنشر التطبيق على Render باستخدام Git

## المساهمة

نرحب بالمساهمات والاقتراحات لتحسين النظام. يرجى إرسال طلبات السحب أو فتح مشكلة جديدة للمناقشة.

## الترخيص

جميع الحقوق محفوظة © MetaBit Safety 2025
