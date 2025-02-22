import os
import json
import uuid
import logging
import asyncio
import threading
import psycopg2
from datetime import datetime
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from telegram_bot import create_application, send_status_notification, shutdown_bot, run_bot

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
app.secret_key = 'your-secret-key-here'  # مفتاح سري للجلسة

# إنشاء مجلد uploads إذا لم يكن موجوداً
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# إعدادات قاعدة البيانات
DATABASE_URL = os.environ.get('DATABASE_URL', 'postgresql://metabit_kyc_user:o8X1GbhjuT7fDGHrH8gfn0OiXRm9MykO@dpg-cul0mt23esus73b1r0a0-a.singapore-postgres.render.com/metabit_kyc')

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

def init_db():
    """تهيئة قاعدة البيانات وإنشاء الجداول"""
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        
        # إنشاء جدول الطلبات إذا لم يكن موجوداً
        cur.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id UUID PRIMARY KEY,
                full_name VARCHAR(100) NOT NULL,
                id_number VARCHAR(50) NOT NULL,
                phone VARCHAR(20) NOT NULL,
                address TEXT NOT NULL,
                id_photo_path VARCHAR(255),
                selfie_photo_path VARCHAR(255),
                status VARCHAR(50) NOT NULL DEFAULT 'pending',
                message TEXT,
                chat_id BIGINT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP
            )
        ''')
        
        # التحقق من وجود عمود chat_id وإضافته إذا لم يكن موجوداً
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'requests' AND column_name = 'chat_id'
        """)
        if not cur.fetchone():
            cur.execute('ALTER TABLE requests ADD COLUMN chat_id BIGINT')
        
        conn.commit()
        logger.info("تم تهيئة قاعدة البيانات بنجاح")
        
    except Exception as e:
        logger.error(f"خطأ في تهيئة قاعدة البيانات: {str(e)}")
        
    finally:
        cur.close()
        conn.close()

# تهيئة قاعدة البيانات عند بدء التطبيق
try:
    with app.app_context():
        init_db()
except Exception as e:
    print(f"خطأ في تهيئة التطبيق: {e}", file=sys.stderr)

# تهيئة ngrok
def init_ngrok():
    """إنشاء نفق ngrok"""
    try:
        # تجاهل إنشاء النفق إذا لم يكن هناك authtoken
        if not os.environ.get('NGROK_AUTH_TOKEN'):
            logger.warning("لم يتم تعيين NGROK_AUTH_TOKEN. سيتم تجاهل إنشاء نفق ngrok.")
            return None
            
        # إنشاء نفق HTTPS
        public_url = ngrok.connect(5000, bind_tls=True)
        logger.info(f"تم إنشاء نفق ngrok: {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"خطأ في إنشاء نفق ngrok: {str(e)}")
        return None

def get_public_url():
    """إنشاء رابط عام باستخدام cloudflared"""
    try:
        # تشغيل cloudflared tunnel
        process = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', 'http://localhost:5000'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        # انتظار حتى نحصل على الرابط العام
        for line in process.stderr:
            if 'https://' in line:
                url = re.search('https://[^\s]+', line).group()
                return url.strip()
        
        return None
    except Exception as e:
        print(f"خطأ في إنشاء النفق: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # تحقق بسيط من بيانات الدخول - يجب تحسين هذا في الإنتاج
        if username == 'admin' and password == 'admin123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin_login.html', error='بيانات الدخول غير صحيحة')
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    """لوحة تحكم المشرف"""
    try:
        conn = get_db_connection()
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
            # تحويل مسارات الصور إلى URLs نسبية
            id_photo_path = row[5].replace(app.root_path, '').replace('\\', '/').lstrip('/') if row[5] else None
            selfie_photo_path = row[6].replace(app.root_path, '').replace('\\', '/').lstrip('/') if row[6] else None
            
            requests.append({
                'id': row[0],
                'full_name': row[1],
                'id_number': row[2],
                'phone': row[3],
                'address': row[4],
                'id_photo': id_photo_path,
                'selfie_photo': selfie_photo_path,
                'status': row[7],
                'created_at': row[8].strftime('%Y/%m/%d %I:%M %p') if row[8] else None
            })
        
        return render_template('admin/dashboard.html', requests=requests)
        
    except Exception as e:
        app.logger.error(f"خطأ في عرض لوحة التحكم: {str(e)}")
        return "حدث خطأ في عرض لوحة التحكم", 500
        
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """عرض الصور المحفوظة"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

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

        # إنشاء مجلد للمستخدم
        user_folder = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(id_number))
        if not os.path.exists(user_folder):
            os.makedirs(user_folder)

        # حفظ الصور
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        id_photo_filename = f'id_photo_{timestamp}.jpg'
        id_photo_path = os.path.join(user_folder, id_photo_filename)
        id_photo.save(id_photo_path)
        
        selfie_photo_filename = f'selfie_photo_{timestamp}.jpg'
        selfie_photo_path = os.path.join(user_folder, selfie_photo_filename)
        selfie_photo.save(selfie_photo_path)

        # حفظ البيانات في قاعدة البيانات
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            cur.execute('''
                INSERT INTO requests (
                    id, full_name, id_number, phone, address,
                    id_photo_path, selfie_photo_path, status,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                str(uuid.uuid4()), full_name, id_number, phone, address,
                id_photo_path, selfie_photo_path, 'pending',
                datetime.now()
            ))
            
            conn.commit()
            logger.info(f"تم حفظ الطلب بنجاح")
            
            return jsonify({
                'status': 'success',
                'message': 'تم استلام البيانات بنجاح'
            })
            
        except Exception as e:
            conn.rollback()
            logger.error(f"خطأ في حفظ البيانات في قاعدة البيانات: {str(e)}")
            return jsonify({'error': 'حدث خطأ أثناء حفظ البيانات'}), 500
            
        finally:
            cur.close()
            conn.close()
        
    except Exception as e:
        logger.error(f"خطأ عام في معالجة الطلب: {str(e)}")
        return jsonify({'error': 'حدث خطأ أثناء معالجة الطلب'}), 500

@app.route('/request/<request_id>')
def request_status(request_id):
    """عرض صفحة حالة الطلب"""
    return render_template('status.html', request_id=request_id)

@app.route('/api/status/<request_id>')
def get_request_status(request_id):
    """الحصول على حالة الطلب"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute('''
            SELECT status, message, created_at
            FROM requests 
            WHERE id = %s
        ''', (request_id,))
        
        result = cur.fetchone()
        
        if result:
            status, message, created_at = result
            return jsonify({
                'status': status,
                'message': message,
                'created_at': created_at.isoformat() if created_at else None
            })
        else:
            return jsonify({'error': 'الطلب غير موجود'}), 404
            
    except Exception as e:
        app.logger.error(f"خطأ في جلب حالة الطلب: {str(e)}")
        return jsonify({'error': 'حدث خطأ أثناء جلب حالة الطلب'}), 500
        
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

@app.route('/check-status/<request_id>')
def check_status(request_id):
    """التحقق من حالة الطلب في قاعدة البيانات"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM requests WHERE id = %s', (request_id,))
    request = cur.fetchone()
    cur.close()
    conn.close()

    if request:
        return jsonify({
            'status': 'found',
            'data': {
                'full_name': request[1],
                'id_number': request[2],
                'phone': request[3],
                'address': request[4]
            }
        })
    else:
        return jsonify({'status': 'not_found', 'message': 'لم يتم العثور على الطلب'}), 404

@app.route('/handle_request/<request_id>/<action>', methods=['POST'])
def handle_request(request_id, action):
    """معالجة طلبات القبول والرفض"""
    if 'admin_logged_in' not in session:
        return jsonify({'success': False, 'message': 'غير مصرح لك بهذا الإجراء'}), 401
    
    if action not in ['approve', 'reject']:
        return jsonify({'success': False, 'message': 'إجراء غير صالح'}), 400
    
    data = request.get_json()
    status = 'مقبول' if action == 'approve' else 'مرفوض'
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        if action == 'approve':
            verification_code = data.get('verificationCode')
            if not verification_code:
                return jsonify({'success': False, 'message': 'يجب إدخال كود التحقق'}), 400
            
            # تحديث حالة الطلب وكود التحقق
            cur.execute('''
                UPDATE requests 
                SET status = %s,
                    processed_at = CURRENT_TIMESTAMP,
                    notes = %s
                WHERE id = %s 
                RETURNING telegram_chat_id
            ''', (status, f'تم القبول مع كود التحقق: {verification_code}', request_id))
            
        else:  # reject
            rejection_reason = data.get('rejectionReason')
            if not rejection_reason:
                return jsonify({'success': False, 'message': 'يجب إدخال سبب الرفض'}), 400
            
            # تحديث حالة الطلب وسبب الرفض
            cur.execute('''
                UPDATE requests 
                SET status = %s,
                    processed_at = CURRENT_TIMESTAMP,
                    notes = %s
                WHERE id = %s 
                RETURNING telegram_chat_id
            ''', (status, f'سبب الرفض: {rejection_reason}', request_id))
        
        result = cur.fetchone()
        conn.commit()
        
        # إرسال إشعار للمستخدم عبر التلجرام
        if result and result[0]:  # إذا كان هناك معرف تلجرام
            chat_id = result[0]
            message = f"تم {status} طلبك"
            if action == 'approve':
                message += f"\nكود التحقق الخاص بك هو: {verification_code}"
            elif action == 'reject':
                message += f"\nالسبب: {rejection_reason}"
                
            threading.Thread(target=lambda: asyncio.run(
                send_status_notification(chat_id, request_id, message)
            )).start()
        
        return jsonify({
            'success': True,
            'message': f'تم {status} الطلب بنجاح'
        })
        
    except Exception as e:
        conn.rollback()
        logger.error(f"خطأ في معالجة الطلب: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'حدث خطأ في معالجة الطلب'
        }), 500
        
    finally:
        cur.close()
        conn.close()

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/update-status', methods=['POST'])
def update_status():
    data = request.json
    request_id = data.get('request_id')
    new_status = data.get('status')
    message = data.get('message')

    if not request_id or not new_status:
        return jsonify({'error': 'يجب توفير معرف الطلب والحالة الجديدة'}), 400

    try:
        with get_db() as conn:
            cur = conn.cursor()
            
            # تحديث حالة الطلب والرسالة
            cur.execute('''
                UPDATE requests 
                SET status = %s, message = %s, updated_at = CURRENT_TIMESTAMP 
                WHERE id = %s
                RETURNING chat_id
            ''', (new_status, message, request_id))
            
            result = cur.fetchone()
            if not result:
                return jsonify({'error': 'لم يتم العثور على الطلب'}), 404
            
            chat_id = result[0]
            if chat_id:
                # تشغيل في thread منفصل لتجنب تأخير الاستجابة
                Thread(target=lambda: asyncio.run(send_status_notification(chat_id, new_status, message))).start()
            else:
                logger.warning(f"لم يتم العثور على chat_id للطلب {request_id}")
            
            conn.commit()
            return jsonify({'success': True, 'message': 'تم تحديث حالة الطلب بنجاح'})
            
    except Exception as e:
        print(f"Error updating status: {e}")
        return jsonify({'error': 'حدث خطأ أثناء تحديث حالة الطلب'}), 500

@app.route('/admin/delete-request', methods=['POST'])
def delete_request():
    """حذف طلب"""
    try:
        data = request.get_json()
        request_id = data.get('request_id')
        
        if not request_id:
            return jsonify({'error': 'معرف الطلب مطلوب'}), 400
            
        conn = get_db_connection()
        cur = conn.cursor()
        
        # حذف الصور أولاً
        cur.execute('SELECT id_photo_path, selfie_photo_path FROM requests WHERE id = %s', (request_id,))
        result = cur.fetchone()
        
        if result:
            id_photo_path, selfie_photo_path = result
            
            # حذف الملفات إذا كانت موجودة
            if id_photo_path and os.path.exists(id_photo_path):
                os.remove(id_photo_path)
            if selfie_photo_path and os.path.exists(selfie_photo_path):
                os.remove(selfie_photo_path)
        
        # حذف السجل من قاعدة البيانات
        cur.execute('DELETE FROM requests WHERE id = %s', (request_id,))
        conn.commit()
        
        return jsonify({'success': True, 'message': 'تم حذف الطلب بنجاح'})
        
    except Exception as e:
        app.logger.error(f"خطأ في حذف الطلب: {str(e)}")
        return jsonify({'error': 'حدث خطأ أثناء حذف الطلب'}), 500
        
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# متغير عام للبوت
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
                    except Exception as e:
                        logger.error(f"خطأ في تشغيل البوت: {e}")
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

if __name__ == '__main__':
    try:
        # تشغيل البوت
        if start_bot():
            # تشغيل التطبيق
            port = int(os.environ.get('PORT', 51776))  # استخدام المنفذ المخصص
            app.run(host='0.0.0.0', port=port, ssl_context=None)
        else:
            logger.error("فشل في بدء البوت")
    except Exception as e:
        logger.error(f"خطأ في تشغيل التطبيق: {e}")
        # محاولة تنظيف الموارد في حالة الخطأ
        asyncio.run(cleanup())
