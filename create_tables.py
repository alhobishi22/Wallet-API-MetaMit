"""
سكريبت لإنشاء جداول قاعدة البيانات وإضافة مستخدم مشرف افتراضي
"""
from flask import Flask
from models import db, User
from werkzeug.security import generate_password_hash
import os
from sqlalchemy import text

app = Flask(__name__)
app.config.from_object('config')

db.init_app(app)

def create_tables_and_admin():
    """إنشاء جداول قاعدة البيانات وإضافة مستخدم مشرف افتراضي"""
    with app.app_context():
        # حذف وإعادة إنشاء جدول المستخدمين
        print("إعادة إنشاء جداول قاعدة البيانات...")
        try:
            db.session.execute(text("DROP TABLE IF EXISTS users CASCADE"))
            db.session.commit()
            print("تم حذف جدول المستخدمين بنجاح (إذا كان موجوداً)")
        except Exception as e:
            db.session.rollback()
            print(f"خطأ أثناء حذف جدول المستخدمين: {e}")
        
        # إنشاء جدول المستخدمين يدوياً
        try:
            db.session.execute(text("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(64) UNIQUE NOT NULL,
                email VARCHAR(120) UNIQUE NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                is_admin BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                last_login TIMESTAMP NULL
            )
            """))
            db.session.commit()
            print("تم إنشاء جدول المستخدمين بنجاح")
        except Exception as e:
            db.session.rollback()
            print(f"خطأ أثناء إنشاء جدول المستخدمين: {e}")
            return
        
        # إضافة مستخدم مشرف افتراضي
        try:
            db.session.execute(
                text("""
                INSERT INTO users (username, email, password_hash, is_admin)
                VALUES (:username, :email, :password_hash, :is_admin)
                """),
                {
                    "username": "admin",
                    "email": "admin@metabit.com",
                    "password_hash": generate_password_hash("MetaBit@2025"),
                    "is_admin": True
                }
            )
            db.session.commit()
            print("تم إنشاء مستخدم مشرف افتراضي:")
            print("اسم المستخدم: admin")
            print("كلمة المرور: MetaBit@2025")
            print("يرجى تغيير كلمة المرور بعد تسجيل الدخول.")
        except Exception as e:
            db.session.rollback()
            print(f"خطأ أثناء إنشاء مستخدم مشرف افتراضي: {e}")

if __name__ == "__main__":
    create_tables_and_admin()
