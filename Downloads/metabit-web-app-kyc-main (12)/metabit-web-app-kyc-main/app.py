import os
from flask import Flask, render_template, request, jsonify, redirect, url_for
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import base64
import asyncio
import random
import string
import database
from telegram_notifier import send_admin_notification
import time
from functools import wraps
import logging
import sys
from logging.handlers import RotatingFileHandler

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# إعداد السجلات
if not os.path.exists('logs'):
    os.makedirs('logs')

# إعداد مسجل الملف
file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
file_handler.setLevel(logging.INFO)
app.logger.addHandler(file_handler)

# إعداد مسجل وحدة التحكم
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
console_handler.setLevel(logging.INFO)
app.logger.addHandler(console_handler)

app.logger.setLevel(logging.INFO)
app.logger.info('تم بدء تشغيل تطبيق MetaBit KYC')

# تخزين مؤقت لتتبع عدد الطلبات من كل عنوان IP
request_tracker = {}

# وظيفة للتحقق من عدد الطلبات من نفس عنوان IP
def check_rate_limit(ip_address, max_requests=5, time_window=60):
    """
    التحقق من عدد الطلبات من نفس عنوان IP خلال فترة زمنية محددة
    
    :param ip_address: عنوان IP
    :param max_requests: الحد الأقصى لعدد الطلبات المسموح بها
    :param time_window: الفترة الزمنية بالثواني
    :return: True إذا تجاوز الحد، False إذا لم يتجاوز
    """
    current_time = time.time()
    
    # إزالة السجلات القديمة
    for ip in list(request_tracker.keys()):
        request_tracker[ip] = [timestamp for timestamp in request_tracker[ip] if current_time - timestamp < time_window]
        if not request_tracker[ip]:
            del request_tracker[ip]
    
    # إضافة الطلب الحالي
    if ip_address not in request_tracker:
        request_tracker[ip_address] = []
    
    request_tracker[ip_address].append(current_time)
    
    # التحقق من عدد الطلبات
    return len(request_tracker[ip_address]) > max_requests

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
if app.config['SQLALCHEMY_DATABASE_URI'].startswith('postgres://'):
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config['SQLALCHEMY_DATABASE_URI'].replace('postgres://', 'postgresql://', 1)

# Initialize extensions
db = SQLAlchemy(app)
CORS(app)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET')
)

# Create tables
with app.app_context():
    db.create_all()

# Define models
class KYCApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    id_photo_url = db.Column(db.String(200), nullable=False)
    selfie_photo_url = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='pending')
    registration_code = db.Column(db.String(50), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    telegram_chat_id = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def upload_base64_to_cloudinary(base64_image):
    """
    رفع صورة بتنسيق Base64 إلى Cloudinary
    
    :param base64_image: صورة بتنسيق Base64
    :return: رابط الصورة المرفوعة أو None في حالة الفشل
    """
    max_retries = 3
    retry_delay = 2  # ثواني
    
    for attempt in range(max_retries):
        try:
            # التحقق من صحة الصورة
            if not base64_image:
                app.logger.error("خطأ في رفع الصورة: الصورة فارغة")
                return None
                
            # إزالة بداية سلسلة Base64 إذا كانت موجودة
            if 'base64,' in base64_image:
                base64_image = base64_image.split('base64,')[1]
                
            # التحقق من طول الصورة
            if len(base64_image) > 10 * 1024 * 1024:  # 10 ميجابايت كحد أقصى
                app.logger.error("خطأ في رفع الصورة: حجم الصورة كبير جدًا")
                return None
                
            # التحقق من صحة تنسيق Base64
            try:
                # محاولة فك ترميز Base64 للتأكد من صحته
                base64.b64decode(base64_image)
            except Exception as e:
                app.logger.error(f"خطأ في رفع الصورة: تنسيق Base64 غير صالح - {str(e)}")
                return None
            
            # رفع الصورة إلى Cloudinary
            app.logger.info(f"جاري رفع الصورة إلى Cloudinary... (محاولة {attempt+1}/{max_retries})")
            result = cloudinary.uploader.upload(
                f"data:image/jpeg;base64,{base64_image}",
                folder="kyc_photos",  # مجلد لتنظيم الصور
                resource_type="image",
                timeout=30  # زيادة مهلة الانتظار
            )
            app.logger.info(f"تم رفع الصورة بنجاح: {result['public_id']}")
            return result['secure_url']
        except cloudinary.exceptions.Error as e:
            app.logger.error(f"خطأ في Cloudinary (محاولة {attempt+1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                app.logger.info(f"إعادة المحاولة بعد {retry_delay} ثواني...")
                time.sleep(retry_delay)
                retry_delay *= 2  # زيادة وقت الانتظار بين المحاولات
            else:
                app.logger.error("فشلت جميع محاولات رفع الصورة")
                return None
        except Exception as e:
            app.logger.error(f"خطأ غير متوقع في رفع الصورة (محاولة {attempt+1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                app.logger.info(f"إعادة المحاولة بعد {retry_delay} ثواني...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                app.logger.error("فشلت جميع محاولات رفع الصورة")
                return None
    
    return None  # في حالة فشل جميع المحاولات

def generate_application_id():
    """إنشاء رقم طلب فريد"""
    date_str = datetime.now().strftime('%Y%m%d')
    random_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"KYC-{date_str}-{random_str}"

@app.route('/')
def index():
    """
    الصفحة الرئيسية للتطبيق
    """
    # استخراج معرف المستخدم من معلمات عنوان URL
    telegram_chat_id = request.args.get('telegram_chat_id')
    
    # البحث عن طلب موجود بناءً على معرف تلغرام
    application_data = None
    has_application = False
    status_arabic = "قيد المراجعة"
    created_at = None
    
    if telegram_chat_id:
        try:
            # البحث عن طلب بناءً على معرف تلغرام
            application_info = asyncio.run(database.get_application_by_telegram_id(telegram_chat_id))
            
            if application_info:
                has_application = True
                application_data = application_info
                
                # تحويل الحالة إلى العربية
                status = application_info.get('status', 'pending')
                if status == 'approved':
                    status_arabic = "مقبول"
                elif status == 'rejected':
                    status_arabic = "مرفوض"
                else:
                    status_arabic = "قيد المراجعة"
                
                # تنسيق تاريخ الإنشاء
                created_at = application_info.get('created_at', '')
                if created_at:
                    # تحويل التاريخ إلى تنسيق أكثر قراءة
                    created_at_dt = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
                    created_at = created_at_dt.strftime('%Y-%m-%d %H:%M:%S')
                
                # التحقق من وجود معلمة resubmit في عنوان URL
                resubmit = request.args.get('resubmit')
                if resubmit == 'true' and status == 'rejected':
                    # إذا كان المستخدم يريد إعادة تقديم الطلب المرفوض، نعيد تعيين has_application إلى False
                    has_application = False
        except Exception as e:
            logger.error(f"خطأ في استرجاع معلومات الطلب: {str(e)}")
    
    return render_template('index.html', 
                           has_application=has_application, 
                           application_data=application_data,
                           status_arabic=status_arabic,
                           created_at=created_at)

@app.route('/api/submit_kyc', methods=['POST'])
def submit_kyc():
    """
    واجهة برمجة التطبيقات لتقديم طلب التحقق من الهوية
    """
    try:
        # تسجيل معلومات الطلب
        client_ip = request.remote_addr
        user_agent = request.headers.get('User-Agent', 'Unknown')
        request_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=16))
        
        logger = app.logger
        logger.info(f"[API] طلب جديد لـ /api/submit_kyc - IP: {client_ip}, RequestID: {request_id}")
        
        # التحقق من عدد الطلبات من نفس عنوان IP
        if check_rate_limit(client_ip):
            logger.warning(f"[API] تجاوز الحد الأقصى لعدد الطلبات من نفس عنوان IP - IP: {client_ip}, RequestID: {request_id}")
            return jsonify({
                'success': False,
                'message': 'تجاوز الحد الأقصى لعدد الطلبات من نفس عنوان IP'
            }), 429
        
        # التأكد من أن البيانات بتنسيق JSON
        if not request.is_json:
            logger.warning(f"[API] طلب غير صالح (ليس JSON) - IP: {client_ip}, RequestID: {request_id}")
            return jsonify({
                'success': False,
                'message': 'يجب إرسال البيانات بتنسيق JSON'
            }), 400

        data = request.get_json()
        
        # التحقق من البيانات المطلوبة
        required_fields = ['fullName', 'phoneNumber', 'address', 'idPhoto', 'selfiePhoto']
        for field in required_fields:
            if field not in data:
                logger.warning(f"[API] طلب غير صالح (حقل {field} مفقود) - IP: {client_ip}, RequestID: {request_id}")
                return jsonify({
                    'success': False,
                    'message': f'حقل {field} مطلوب'
                }), 400
        
        # التحقق من صحة البيانات المرسلة
        # التحقق من الاسم الكامل
        if not isinstance(data['fullName'], str) or len(data['fullName']) < 3 or len(data['fullName']) > 100:
            logger.warning(f"[API] طلب غير صالح (الاسم الكامل غير صالح) - IP: {client_ip}, RequestID: {request_id}")
            return jsonify({
                'success': False,
                'message': 'الاسم الكامل غير صالح'
            }), 400
            
        # التحقق من رقم الهاتف
        if not isinstance(data['phoneNumber'], str) or len(data['phoneNumber']) < 8 or len(data['phoneNumber']) > 20:
            logger.warning(f"[API] طلب غير صالح (رقم الهاتف غير صالح) - IP: {client_ip}, RequestID: {request_id}")
            return jsonify({
                'success': False,
                'message': 'رقم الهاتف غير صالح'
            }), 400
            
        # التحقق من العنوان
        if not isinstance(data['address'], str) or len(data['address']) < 5 or len(data['address']) > 200:
            logger.warning(f"[API] طلب غير صالح (العنوان غير صالح) - IP: {client_ip}, RequestID: {request_id}")
            return jsonify({
                'success': False,
                'message': 'العنوان غير صالح'
            }), 400
            
        # التحقق من صور الهوية والسيلفي
        for photo_field in ['idPhoto', 'selfiePhoto']:
            if not isinstance(data[photo_field], str) or not data[photo_field].startswith('data:image/'):
                logger.warning(f"[API] طلب غير صالح (صورة {photo_field} غير صالحة) - IP: {client_ip}, RequestID: {request_id}")
                return jsonify({
                    'success': False,
                    'message': f'صورة {photo_field} غير صالحة'
                }), 400

        # الحصول على معرف المستخدم في تلغرام إذا كان متاحًا
        telegram_chat_id = data.get('telegramChatId')
        
        # الحصول على معلومات الجهاز إذا كانت متاحة
        device_info = data.get('deviceInfo')
        
        # الحصول على عنوان IP للمستخدم
        ip_address = request.remote_addr
        
        # محاولة الحصول على معلومات الموقع الجغرافي من عنوان IP
        geo_location = None
        try:
            import requests
            geo_response = requests.get(f'https://ipinfo.io/{ip_address}/json')
            if geo_response.status_code == 200:
                geo_location = geo_response.json()
        except Exception as e:
            app.logger.warning(f"فشل في الحصول على معلومات الموقع الجغرافي: {str(e)}")
        
        # رفع الصور إلى Cloudinary
        id_photo_url = upload_base64_to_cloudinary(data['idPhoto'])
        selfie_photo_url = upload_base64_to_cloudinary(data['selfiePhoto'])
        
        if not id_photo_url or not selfie_photo_url:
            logger.error(f"[API] فشل في رفع الصور - IP: {client_ip}, RequestID: {request_id}")
            return jsonify({
                'success': False,
                'message': 'فشل في رفع الصور'
            }), 500

        # إنشاء رقم طلب فريد
        id_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # تجهيز بيانات الطلب
        application_data = {
            'full_name': data['fullName'],
            'phone_number': data['phoneNumber'],
            'address': data['address'],
            'id_photo_url': id_photo_url,
            'selfie_photo_url': selfie_photo_url,
            'id_suffix': id_suffix,
            'telegram_chat_id': telegram_chat_id,
            'device_info': device_info,
            'ip_address': ip_address,
            'geo_location': geo_location
        }
        
        # حفظ البيانات في قاعدة البيانات
        success, application_id = database.save_kyc_application(application_data)
        
        if not success:
            logger.error(f"[API] فشل في حفظ الطلب - IP: {client_ip}, RequestID: {request_id}, Error: {application_id}")
            return jsonify({
                'success': False,
                'message': f'فشل في حفظ الطلب: {application_id}'  # في هذه الحالة application_id يحتوي على رسالة الخطأ
            }), 500
            
        # إرسال إشعار للمشرفين
        asyncio.run(send_admin_notification({
            'application_id': application_id,
            'full_name': data['fullName'],
            'phone_number': data['phoneNumber'],
            'address': data['address'],
            'id_photo_url': id_photo_url,
            'selfie_photo_url': selfie_photo_url,
            'device_info': device_info,
            'ip_address': ip_address,
            'geo_location': geo_location,
            'telegram_chat_id': telegram_chat_id
        }))
        
        logger.info(f"[API] تم إرسال طلب التوثيق بنجاح - IP: {client_ip}, RequestID: {request_id}, ApplicationID: {application_id}")
        return jsonify({
            'success': True,
            'message': 'تم إرسال طلب التوثيق بنجاح',
            'application_id': application_id
        })
        
    except Exception as e:
        logger.error(f"[API] خطأ في معالجة الطلب - IP: {request.remote_addr}, RequestID: {request_id}, Error: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'حدث خطأ أثناء معالجة الطلب: {str(e)}'
        }), 500

@app.route('/api/check_status/<application_id>')
def api_check_status(application_id):
    try:
        # التحقق من حالة الطلب
        success, status_data = database.check_application_status(application_id)
        
        if not success:
            return jsonify({
                'success': False,
                'message': status_data  # في هذه الحالة status_data يحتوي على رسالة الخطأ
            }), 404
        
        # تحويل التاريخ إلى نص
        if 'created_at' in status_data and status_data['created_at']:
            status_data['created_at'] = status_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        # تحويل حالة الطلب إلى العربية
        status_arabic = "قيد المراجعة"
        if status_data['status'] == 'approved':
            status_arabic = "مقبول"
        elif status_data['status'] == 'rejected':
            status_arabic = "مرفوض"
        
        return jsonify({
            'success': True,
            'status': status_arabic,
            'registration_code': status_data['registration_code'],
            'rejection_reason': status_data['rejection_reason'],
            'created_at': status_data['created_at']
        })
        
    except Exception as e:
        print(f"خطأ في التحقق من حالة الطلب: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'حدث خطأ أثناء التحقق من حالة الطلب: {str(e)}'
        }), 500

@app.route('/check_status/<application_id>')
def check_status(application_id):
    try:
        # التحقق من حالة الطلب
        success, status_data = database.check_application_status(application_id)
        
        if not success:
            return jsonify({
                'success': False,
                'message': status_data  # في هذه الحالة status_data يحتوي على رسالة الخطأ
            }), 404
        
        # تحويل التاريخ إلى نص
        if 'created_at' in status_data and status_data['created_at']:
            status_data['created_at'] = status_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        return jsonify({
            'success': True,
            'status': status_data['status'],
            'registration_code': status_data['registration_code'],
            'rejection_reason': status_data['rejection_reason'],
            'created_at': status_data['created_at']
        })
        
    except Exception as e:
        print(f"خطأ في التحقق من حالة الطلب: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'حدث خطأ أثناء التحقق من حالة الطلب: {str(e)}'
        }), 500

@app.route('/status/<application_id>')
def status_page(application_id):
    """
    عرض صفحة حالة الطلب
    """
    try:
        # التحقق من حالة الطلب
        success, status_data = database.check_application_status(application_id)
        
        if not success:
            return render_template('error.html', message="لم يتم العثور على الطلب")
        
        # تحويل التاريخ إلى نص
        if 'created_at' in status_data and status_data['created_at']:
            status_data['created_at'] = status_data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        return render_template('status.html', 
                              application_id=application_id,
                              status=status_data['status'],
                              registration_code=status_data['registration_code'],
                              rejection_reason=status_data['rejection_reason'],
                              created_at=status_data['created_at'])
        
    except Exception as e:
        print(f"خطأ في عرض صفحة حالة الطلب: {str(e)}")
        return render_template('error.html', message=f"حدث خطأ أثناء عرض حالة الطلب: {str(e)}")

if __name__ == '__main__':
    # Set up the database connection
    with app.app_context():
        db.create_all()
    
    # Get the port from environment variable or use default
    port = int(os.environ.get('PORT', 10000))
    
    # Run the Flask application
    print(f"Starting Flask application on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=True)
