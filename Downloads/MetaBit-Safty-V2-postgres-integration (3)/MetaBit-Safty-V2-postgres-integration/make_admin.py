from app import app, db, User
import sys

def make_admin(username):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            print(f"خطأ: المستخدم '{username}' غير موجود")
            return False
        
        user.is_admin = True
        db.session.commit()
        print(f"تم ترقية المستخدم '{username}' إلى مشرف بنجاح")
        return True

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("الاستخدام: python make_admin.py [اسم_المستخدم]")
        sys.exit(1)
    
    username = sys.argv[1]
    if not make_admin(username):
        sys.exit(1)
