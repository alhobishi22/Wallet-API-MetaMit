from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from psycopg2.extras import DictCursor
import uuid
import os
import asyncio
from telegram_bot import send_status_notification, run_bot, set_webapp_url
import threading
import subprocess
import time
import json
import requests
import psycopg2
from datetime import datetime
import socket
import re

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # مفتاح سري للجلسة - يجب تغييره في الإنتاج

# تكوين قاعدة البيانات
DATABASE_URL = "postgresql://metabit_kyc_user:o8X1GbhjuT7fDGHrH8gfn0OiXRm9MykO@dpg-cul0mt23esus73b1r0a0-a.singapore-postgres.render.com/metabit_kyc"

# تكوين المجلد للملفات المرفوعة
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # إنشاء جدول الطلبات إذا لم يكن موجوداً
    cur.execute('''
        CREATE TABLE IF NOT EXISTS requests (
            id VARCHAR(36) PRIMARY KEY,
            full_name VARCHAR(100) NOT NULL,
            id_number VARCHAR(20) NOT NULL,
            phone VARCHAR(20) NOT NULL,
            id_photo VARCHAR(255) NOT NULL,
            selfie_photo VARCHAR(255) NOT NULL,
            status VARCHAR(20) DEFAULT 'قيد المراجعة',
            telegram_chat_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            registration_code VARCHAR(50),
            rejection_reason TEXT
        )
    ''')
    
    # محاولة إضافة عمود telegram_chat_id إذا لم يكن موجوداً
    try:
        cur.execute('''
            ALTER TABLE requests 
            ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT
        ''')
        conn.commit()
    except Exception as e:
        print(f"Error adding telegram_chat_id column: {str(e)}")
        conn.rollback()
    
    conn.commit()
    cur.close()
    conn.close()

# تهيئة قاعدة البيانات عند بدء التطبيق
with app.app_context():
    init_db()

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
    if 'admin_logged_in' not in session:
        return redirect(url_for('admin_login'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute('SELECT * FROM requests ORDER BY created_at DESC')
    requests = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('admin_dashboard.html', requests=requests)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/api/upload-photo', methods=['POST'])
def upload_photo():
    if 'photo' not in request.files:
        return jsonify({'error': 'لم يتم تحميل أي صورة'}), 400
        
    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({'error': 'لم يتم اختيار أي صورة'}), 400
        
    # إنشاء اسم فريد للملف
    filename = str(uuid.uuid4()) + os.path.splitext(photo.filename)[1]
    photo.save(os.path.join(UPLOAD_FOLDER, filename))
    
    return jsonify({'filename': filename})

@app.route('/api/submit-kyc', methods=['POST'])
def submit_kyc():
    data = request.json
    request_id = str(uuid.uuid4())
    
    # الحصول على معرف المستخدم في التلجرام
    telegram_data = data.get('telegram_data', {})
    chat_id = telegram_data.get('chat_id')
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute('''
            INSERT INTO requests (id, full_name, id_number, phone, id_photo, selfie_photo, status, telegram_chat_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            request_id,
            data['fullName'],
            data['idNumber'],
            data['phone'],
            data['idPhoto'],
            data['selfiePhoto'],
            'قيد المراجعة',
            chat_id
        ))
        
        conn.commit()
        
        # إرسال إشعار للمستخدم
        if chat_id:
            threading.Thread(target=lambda: asyncio.run(
                send_status_notification(chat_id, request_id, 'قيد المراجعة')
            )).start()
            
        return jsonify({'request_id': request_id})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        cur.close()
        conn.close()

@app.route('/check-status/<request_id>')
def check_status(request_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute('SELECT * FROM requests WHERE id = %s', (request_id,))
    request_data = cur.fetchone()
    cur.close()
    conn.close()
    
    if request_data:
        # تحويل البيانات إلى قاموس
        request_dict = dict(request_data)
        
        # التأكد من أن الحالة بالعربية
        if request_dict['status'] == 'pending':
            request_dict['status'] = 'قيد المراجعة'
        elif request_dict['status'] == 'approved':
            request_dict['status'] = 'مقبول'
        elif request_dict['status'] == 'rejected':
            request_dict['status'] = 'مرفوض'
            
        return render_template('status.html', request=request_dict)
    else:
        return render_template('status.html', error='لم يتم العثور على الطلب')

@app.route('/handle_request/<request_id>/<action>', methods=['POST'])
def handle_request(request_id, action):
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
                SET status = %s, registration_code = %s 
                WHERE id = %s 
                RETURNING telegram_chat_id
            ''', (status, verification_code, request_id))
            
        else:  # reject
            rejection_reason = data.get('rejectionReason')
            if not rejection_reason:
                return jsonify({'success': False, 'message': 'يجب إدخال سبب الرفض'}), 400
            
            # تحديث حالة الطلب وسبب الرفض
            cur.execute('''
                UPDATE requests 
                SET status = %s, rejection_reason = %s 
                WHERE id = %s 
                RETURNING telegram_chat_id
            ''', (status, rejection_reason, request_id))
        
        result = cur.fetchone()
        conn.commit()
        
        # إرسال إشعار للمستخدم إذا كان لديه معرف تلجرام
        if result and result[0]:
            chat_id = result[0]
            
            # إرسال رسالة مخصصة حسب الإجراء
            message = {
                'approve': f'تم قبول طلبك!\nكود التسجيل الخاص بك هو: {verification_code}',
                'reject': f'عذراً، تم رفض طلبك.\nالسبب: {rejection_reason}'
            }[action]
            
            threading.Thread(target=lambda: asyncio.run(
                send_status_notification(chat_id, request_id, status, message)
            )).start()
            
        return jsonify({'success': True})
        
    except Exception as e:
        conn.rollback()
        print(f"Error updating request: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500
        
    finally:
        cur.close()
        conn.close()

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    
    # تعيين رابط التطبيق للبوت
    app_url = os.environ.get('APP_URL', 'https://kyc-verification-app-teon.onrender.com')
    set_webapp_url(app_url)
    print(f"* تم تعيين رابط التطبيق: {app_url}")
    
    # تشغيل بوت التلجرام في thread منفصل
    telegram_thread = threading.Thread(target=run_bot)
    telegram_thread.daemon = True
    telegram_thread.start()
    print("* تم بدء تشغيل بوت التلجرام")
    
    # تشغيل التطبيق
    app.run(host='0.0.0.0', port=port)
