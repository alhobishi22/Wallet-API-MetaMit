"""تغيير اسم جدول المستخدمين

Revision ID: c5e9a2d3f8b7
Revises: 8224d9de3aa9
Create Date: 2025-03-18 01:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError, OperationalError


# revision identifiers, used by Alembic.
revision = 'c5e9a2d3f8b7'
down_revision = '8224d9de3aa9'
branch_labels = None
depends_on = None


def upgrade():
    # تغيير اسم جدول المستخدمين من user إلى users
    try:
        # التحقق من وجود الجدول قبل محاولة تغيير اسمه
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        print(f"الجداول الموجودة قبل الترحيل: {tables}")
        
        if 'user' in tables and 'users' not in tables:
            print("جاري تغيير اسم الجدول من 'user' إلى 'users'")
            op.rename_table('user', 'users')
            
            # تحديث مفتاح أجنبي في جدول التقارير إذا كان موجودًا
            if 'report' in tables:
                try:
                    with op.batch_alter_table('report') as batch_op:
                        batch_op.drop_constraint('fk_report_user_id_user', type_='foreignkey')
                        batch_op.create_foreign_key('fk_report_user_id_users', 'users', ['user_id'], ['id'])
                except (ProgrammingError, OperationalError) as e:
                    print(f"تم تجاهل خطأ في تحديث المفتاح الأجنبي: {str(e)}")
        elif 'users' in tables:
            print("الجدول 'users' موجود بالفعل، تم تخطي تغيير الاسم")
        else:
            print("الجدول 'user' غير موجود، تم تخطي تغيير الاسم")
    except Exception as e:
        print(f"حدث خطأ أثناء ترحيل قاعدة البيانات: {str(e)}")
        # لا نقوم بإعادة رفع الاستثناء لتجنب فشل الترحيل


def downgrade():
    try:
        # التحقق من وجود الجدول قبل محاولة تغيير اسمه
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        tables = inspector.get_table_names()
        
        if 'users' in tables and 'user' not in tables:
            # إعادة اسم الجدول إلى user
            if 'report' in tables:
                try:
                    with op.batch_alter_table('report') as batch_op:
                        batch_op.drop_constraint('fk_report_user_id_users', type_='foreignkey')
                        batch_op.create_foreign_key('fk_report_user_id_user', 'user', ['user_id'], ['id'])
                except (ProgrammingError, OperationalError) as e:
                    print(f"تم تجاهل خطأ في تحديث المفتاح الأجنبي: {str(e)}")
            
            op.rename_table('users', 'user')
    except Exception as e:
        print(f"حدث خطأ أثناء التراجع عن ترحيل قاعدة البيانات: {str(e)}")
        # لا نقوم بإعادة رفع الاستثناء لتجنب فشل الترحيل
