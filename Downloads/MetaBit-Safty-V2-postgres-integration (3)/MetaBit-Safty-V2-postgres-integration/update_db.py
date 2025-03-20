from app import app, db, User, Report
from sqlalchemy import text

def update_database():
    with app.app_context():
        # إضافة عمود custom_fields إلى جدول report
        try:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE report ADD COLUMN custom_fields TEXT'))
                conn.commit()
            print("تم إضافة عمود custom_fields إلى جدول report بنجاح")
        except Exception as e:
            print(f"حدث خطأ أثناء إضافة عمود custom_fields: {str(e)}")
        
        # إضافة عمود is_admin إلى جدول user (إذا لم يكن موجودًا بالفعل)
        try:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0'))
                conn.commit()
            print("تم إضافة عمود is_admin إلى جدول user بنجاح")
        except Exception as e:
            print(f"قد يكون عمود is_admin موجودًا بالفعل: {str(e)}")
        
        # ترقية المستخدم الأول ليصبح مشرفًا (إذا لم يكن مشرفًا بالفعل)
        first_user = User.query.first()
        if first_user:
            if not first_user.is_admin:
                first_user.is_admin = True
                db.session.commit()
                print(f"تم ترقية المستخدم '{first_user.username}' ليصبح مشرفًا")
            else:
                print(f"المستخدم '{first_user.username}' مشرف بالفعل")
        else:
            print("لم يتم العثور على أي مستخدمين في قاعدة البيانات")

if __name__ == "__main__":
    update_database()
