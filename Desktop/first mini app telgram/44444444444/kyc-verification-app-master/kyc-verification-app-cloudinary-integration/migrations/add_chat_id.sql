-- إضافة عمود chat_id إلى جدول requests
ALTER TABLE requests ADD COLUMN IF NOT EXISTS chat_id BIGINT;