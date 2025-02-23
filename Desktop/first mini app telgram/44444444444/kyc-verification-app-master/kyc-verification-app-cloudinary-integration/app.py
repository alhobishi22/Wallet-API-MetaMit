import os
import json
import uuid
import logging
import asyncio
import threading
import psycopg2
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from telegram_bot import (
    create_application, send_status_notification, 
    send_admin_notification, shutdown_bot, run_bot
)
from cloudinary_service import CloudinaryService

# تهيئة التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# إعدادات الجلسة
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-here')
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# تهيئة خدمة Cloudinary
try:
    cloudinary_service = CloudinaryService()
except Exception as e:
    logger.error(f"خطأ في تهيئة خدمة Cloudinary: {e}")
    cloudinary_service = None

# إعدادات قاعدة البيانات
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    """إنشاء اتصال بقاعدة البيانات"""
    try:
        if not DATABASE_URL:
            logger.error("خطأ: لم يتم تعيين DATABASE_URL")
            return None
            
        # تنظيف رابط قاعدة البيانات
        db_url = DATABASE_URL.strip('"').strip("'")
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
            
        conn = psycopg2.connect(db_url)
        logger.info("تم الاتصال بقاعدة البيانات بنجاح")
        return conn
    except psycopg2.Error as e:
        logger.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")
        return None

# تهيئة البوت
bot_app = None

def start_bot():
    """تشغيل البوت في thread منفصل"""
    try:
        global bot_app
        if bot_app is None:
            bot_app = create_application()
            if bot_app:
                # تشغيل البوت في thread منفصل
                def run_bot_async():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(run_bot(bot_app))
                    finally:
                        loop.close()

                bot_thread = threading.Thread(target=run_bot_async, daemon=True)
                bot_thread.start()
                logger.info("تم إنشاء تطبيق البوت بنجاح")
                return True
        return False
    except Exception as e:
        logger.error(f"خطأ في بدء البوت: {e}")
        return False

async def cleanup():
    """تنظيف الموارد عند إيقاف التطبيق"""
    try:
        if bot_app:
            await shutdown_bot()
    except Exception as e:
        logger.error(f"خطأ في تنظيف الموارد: {e}")

@app.teardown_appcontext
def shutdown_cleanup(exception=None):
    """تنظيف الموارد عند إيقاف التطبيق"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(cleanup())
        loop.close()
    except Exception as e:
        logger.error(f"خطأ في تنظيف الموارد: {e}")

@app.route('/')
def index():
    """الصفحة الرئيسية"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"خطأ في عرض الصفحة الرئيسية: {str(e)}")
        return "خطأ في تحميل الصفحة", 500

@app.route('/submit', methods=['POST'])
def submit_kyc():
    try:
        logger.info('استلام طلب جديد')
        
        # التحقق من وجود البيانات المطلوبة
        if 'full_name' not in request.form:
            return jsonify({'error': 'الاسم الكامل مطلوب'}), 400
        if 'id_number' not in request.form:
            return jsonify({'error': 'رقم الهوية مطلوب'}), 400
        if 'phone' not in request.form:
            return jsonify({'error': 'رقم الهاتف مطلوب'}), 400
        if 'address' not in request.form:
            return jsonify({'error': 'العنوان مطلوب'}), 400
        if 'id_photo' not in request.files:
            return jsonify({'error': 'صورة الهوية مطلوبة'}), 400
        if 'selfie_photo' not in request.files:
            return jsonify({'error': 'الصورة الشخصية مطلوبة'}), 400

        # استخراج البيانات
        full_name = request.form['full_name']
        id_number = request.form['id_number']
        phone = request.form['phone']
        address = request.form['address']
        id_photo = request.files['id_photo']
        selfie_photo = request.files['selfie_photo']

        # التحقق من امتدادات الملفات المسموح بها
        def allowed_file(filename):
            ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
            return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

        # التحقق من صحة الملفات
        if not id_photo or not id_photo.filename or not allowed_file(id_photo.filename):
            return jsonify({'error': 'صيغة ملف صورة الهوية غير مدعومة'}), 400
        if not selfie_photo or not selfie_photo.filename or not allowed_file(selfie_photo.filename):
            return jsonify({'error': 'صيغة ملف الصورة الشخصية غير مدعومة'}), 400

        try:
            if not cloudinary_service:
                return jsonify({'error': 'خدمة Cloudinary غير متوفرة'}), 500

            # إنشاء معرف فريد للطلب
            request_id = str(uuid.uuid4())
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_id = secure_filename(id_number)
            folder = f"kyc_verification/{safe_id}"
            
            # رفع صورة الهوية
            id_photo_public_id = f"{folder}/id_photo_{timestamp}"
            id_photo_result = cloudinary_service.upload_file(
                id_photo,
                folder=folder,
                public_id=id_photo_public_id
            )
            id_photo_path = id_photo_result['url']
            
            # رفع الصورة الشخصية
            selfie_photo_public_id = f"{folder}/selfie_photo_{timestamp}"
            selfie_photo_result = cloudinary_service.upload_file(
                selfie_photo,
                folder=folder,
                public_id=selfie_photo_public_id
            )
            selfie_photo_path = selfie_photo_result['url']
            
            logger.info(f"تم رفع الصور بنجاح لـ {safe_id}")

            # حفظ البيانات في قاعدة البيانات
            conn = get_db_connection()
            cur = conn.cursor()
            
            try:
                # الحصول على chat_id من Telegram WebApp
                chat_id = request.form.get('chat_id')
                if not chat_id:
                    logger.warning("لم يتم توفير chat_id")
                
                cur.execute('''
                    INSERT INTO requests (
                        id, full_name, id_number, phone, address,
                        id_photo_path, selfie_photo_path, status,
                        created_at, chat_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', (
                    request_id, full_name, id_number, phone, address,
                    id_photo_path, selfie_photo_path, 'pending',
                    datetime.now(), chat_id
                ))
                
                conn.commit()
                logger.info(f"تم حفظ الطلب بنجاح")
                
                # إنشاء حلقة أحداث جديدة
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # إرسال إشعار للأدمن
                    request_data = {
                        'id': request_id,
                        'full_name': full_name,
                        'id_number': id_number,
                        'phone': phone,
                        'address': address
                    }
                    loop.run_until_complete(send_admin_notification(request_data, 'new'))
                    logger.info("تم إرسال إشعار للأدمن بنجاح")

                    # إرسال إشعار للعميل
                    if chat_id:
                        success_message = (
                            "✅ *تم استلام طلبك بنجاح*\n\n"
                            f"🔍 معرف الطلب: `{request_id}`\n\n"
                            "سيتم مراجعة طلبك وإبلاغك بالنتيجة قريباً\\."
                        )
                        loop.run_until_complete(send_status_notification(chat_id, request_id, success_message))
                        logger.info(f"تم إرسال إشعار للعميل {chat_id}")
                    else:
                        logger.warning("لم يتم توفير chat_id للعميل")

                except Exception as e:
                    logger.error(f"خطأ في إرسال الإشعارات: {str(e)}")
                finally:
                    # إغلاق حلقة الأحداث
                    loop.close()
                
                return jsonify({
                    'status': 'success',
                    'message': 'تم استلام البيانات بنجاح',
                    'request_id': request_id
                })
                
            except Exception as e:
                conn.rollback()
                logger.error(f"خطأ في حفظ البيانات في قاعدة البيانات: {str(e)}")
                return jsonify({'error': 'حدث خطأ أثناء حفظ البيانات'}), 500
                
            finally:
                cur.close()
                conn.close()
                
        except Exception as e:
            logger.error(f"خطأ في رفع الملفات: {str(e)}")
            return jsonify({'error': 'حدث خطأ أثناء رفع الملفات'}), 500
        
    except Exception as e:
        logger.error(f"خطأ عام في معالجة الطلب: {str(e)}")
        return jsonify({'error': 'حدث خطأ أثناء معالجة الطلب'}), 500

# مسارات لوحة التحكم
@app.route('/admin')
def admin_redirect():
    """إعادة توجيه المشرف إلى لوحة التحكم"""
    return redirect(url_for('admin_login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """صفحة تسجيل دخول المشرف"""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # تحقق من صحة بيانات الدخول
        ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
        ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            session.permanent = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin/login.html', error='بيانات الدخول غير صحيحة')
            
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    """لوحة تحكم المشرف"""
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        if not conn:
            return "خطأ في الاتصال بقاعدة البيانات", 500

        cur = conn.cursor()
        
        # جلب جميع الطلبات
        cur.execute('''
            SELECT id, full_name, id_number, phone, address, 
                   id_photo_path, selfie_photo_path, status, created_at
            FROM requests 
            ORDER BY created_at DESC
        ''')
        
        requests = []
        for row in cur.fetchall():
            requests.append({
                'id': row[0],
                'full_name': row[1],
                'id_number': row[2],
                'phone': row[3],
                'address': row[4],
                'id_photo': row[5],
                'selfie_photo': row[6],
                'status': row[7],
                'created_at': row[8].strftime('%Y/%m/%d %I:%M %p') if row[8] else None
            })
        
        return render_template('admin/dashboard.html', requests=requests)
        
    except Exception as e:
        logger.error(f"خطأ في عرض لوحة التحكم: {str(e)}")
        return "حدث خطأ في عرض لوحة التحكم", 500
        
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/admin/logout')
def admin_logout():
    """تسجيل خروج المشرف"""
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/update-status', methods=['POST'])
def update_status():
    """تحديث حالة الطلب"""
    if not session.get('admin_logged_in'):
        return jsonify({'error': 'غير مصرح لك بهذا الإجراء'}), 401

    try:
        data = request.json
        request_id = data.get('request_id')
        new_status = data.get('status')
        verification_code = data.get('verificationCode')
        rejection_reason = data.get('rejectionReason')

        if not request_id or not new_status:
            return jsonify({'error': 'يجب توفير معرف الطلب والحالة الجديدة'}), 400

        # تحضير الرسالة المناسبة
        if new_status == 'approved' and verification_code:
            message = f"تم قبول طلبك. كود التحقق: {verification_code}"
        elif new_status == 'rejected' and rejection_reason:
            message = f"تم رفض طلبك. السبب: {rejection_reason}"
        else:
            message = f"تم تحديث حالة طلبك إلى: {new_status}"

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'خطأ في الاتصال بقاعدة البيانات'}), 500

        try:
            cur = conn.cursor()
            
            # تحديث حالة الطلب والرسالة
            cur.execute('''
                UPDATE requests 
                SET status = %s, 
                    message = %s, 
                    updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s
                RETURNING chat_id
            ''', (new_status, message, request_id))
            
            result = cur.fetchone()
            if not result:
                return jsonify({'error': 'لم يتم العثور على الطلب'}), 404
            
            conn.commit()
            
            chat_id = result[0]
            
            # إرسال إشعار للمستخدم
            if chat_id:
                try:
                    # إنشاء حلقة أحداث جديدة
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    try:
                        # تحضير الرسالة المناسبة
                        if new_status == 'approved' and verification_code:
                            message = f"✅ تم قبول طلبك!\n\n🔑 كود التحقق الخاص بك هو: {verification_code}"
                        elif new_status == 'rejected' and rejection_reason:
                            message = f"❌ تم رفض طلبك\n\nالسبب: {rejection_reason}"
                        else:
                            message = f"ℹ️ تم تحديث حالة طلبك إلى: {new_status}"

                        # تنظيف النص للتوافق مع MarkdownV2
                        clean_message = message.replace('.', '\\.').replace('-', '\\-').replace('_', '\\_')
                        
                        # إرسال الإشعار
                        loop.run_until_complete(send_status_notification(chat_id, request_id, clean_message))
                        logger.info(f"تم إرسال الإشعار للمستخدم {chat_id}")
                    except Exception as e:
                        logger.error(f"خطأ في إرسال الإشعار للمستخدم: {str(e)}")
                    
                finally:
                    # إغلاق حلقة الأحداث
                    loop.close()
            else:
                logger.warning(f"لم يتم العثور على chat_id للطلب {request_id}")
            
            return jsonify({
                'success': True,
                'message': 'تم تحديث الحالة بنجاح'
            })
            
        finally:
            cur.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"خطأ في تحديث الحالة: {str(e)}")
        return jsonify({
            'error': 'حدث خطأ في تحديث الحالة',
            'details': str(e)
        }), 500

# تشغيل البوت عند بدء التطبيق
try:
    from telegram_bot import ensure_bot_running
    if not ensure_bot_running():
        logger.error("فشل في بدء البوت")
except Exception as e:
    logger.error(f"خطأ في بدء البوت: {e}")

if __name__ == '__main__':
    try:
        # تشغيل التطبيق
        port = int(os.environ.get('PORT', 51776))
        logger.info(f"تشغيل التطبيق على المنفذ {port}")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"خطأ في تشغيل التطبيق: {e}")