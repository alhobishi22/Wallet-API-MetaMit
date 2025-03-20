import os
import sqlite3
import string
import random
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import csv
from io import StringIO
from flask import Response

# Create a Blueprint for telegram code management
telegram_codes_bp = Blueprint('telegram_codes', __name__)

# Function to generate a random code
def generate_random_code(length=8, include_arabic=True):
    """Generate a random alphanumeric code with optional Arabic characters"""
    # English alphanumeric characters
    english_chars = string.ascii_letters + string.digits
    
    if include_arabic:
        # Arabic characters (basic set)
        arabic_chars = 'أبتثجحخدذرزسشصضطظعغفقكلمنهوي'
        # Combined character set
        all_chars = english_chars + arabic_chars
    else:
        all_chars = english_chars
    
    # Generate a code with the selected character set
    return ''.join(random.choice(all_chars) for _ in range(length))

# Clean and normalize code for comparison
def normalize_code(code):
    # Remove whitespace and normalize
    return re.sub(r'\s+', '', code).strip().lower()

# Function to get all registration codes
def get_all_codes():
    conn = sqlite3.connect('instance/telegram_codes.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id, c.code, c.is_used, c.created_at, 
               u.user_id, u.username, u.registered_at
        FROM registration_codes c
        LEFT JOIN registered_users u ON c.code = u.code
        ORDER BY c.created_at DESC
    """)
    codes = cursor.fetchall()
    conn.close()
    return codes

# Function to get all registered users
def get_registered_users():
    conn = sqlite3.connect('instance/telegram_codes.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM registered_users
        ORDER BY registered_at DESC
    """)
    users = cursor.fetchall()
    conn.close()
    return users

# Routes for telegram code management
@telegram_codes_bp.route('/admin/telegram-codes')
@login_required
def telegram_codes():
    if not current_user.is_admin:
        flash('يجب أن تكون مسؤولاً للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('index'))
    
    # Ensure database exists
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registration_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        is_used INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS registered_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        code TEXT NOT NULL,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()
    
    codes = get_all_codes()
    users = get_registered_users()
    
    return render_template('admin_telegram_codes.html', codes=codes, users=users)

@telegram_codes_bp.route('/admin/telegram-codes/generate', methods=['POST'])
@login_required
def generate_code():
    if not current_user.is_admin:
        flash('يجب أن تكون مسؤولاً للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('index'))
    
    num_codes = int(request.form.get('num_codes', 1))
    code_length = int(request.form.get('code_length', 8))
    include_arabic = request.form.get('include_arabic') == 'on'
    
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    
    for _ in range(num_codes):
        # Generate a unique code
        while True:
            code = generate_random_code(code_length, include_arabic)
            cursor.execute("SELECT code FROM registration_codes WHERE code = ?", (code,))
            if not cursor.fetchone():
                break
        
        cursor.execute("INSERT INTO registration_codes (code) VALUES (?)", (code,))
    
    conn.commit()
    conn.close()
    
    flash(f'تم إنشاء {num_codes} كود تسجيل بنجاح', 'success')
    return redirect(url_for('telegram_codes.telegram_codes'))

@telegram_codes_bp.route('/admin/telegram-codes/delete/<int:code_id>', methods=['POST'])
@login_required
def delete_code(code_id):
    if not current_user.is_admin:
        flash('يجب أن تكون مسؤولاً للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('index'))
    
    conn = sqlite3.connect('instance/telegram_codes.db')
    cursor = conn.cursor()
    
    # Get the code to check if it's used
    cursor.execute("SELECT code, is_used FROM registration_codes WHERE id = ?", (code_id,))
    code_data = cursor.fetchone()
    
    if code_data:
        code, is_used = code_data
        
        # Delete the code
        cursor.execute("DELETE FROM registration_codes WHERE id = ?", (code_id,))
        
        # If the code was used, also delete the user registration
        if is_used:
            cursor.execute("DELETE FROM registered_users WHERE code = ?", (code,))
        
        conn.commit()
        flash('تم حذف كود التسجيل بنجاح', 'success')
    else:
        flash('لم يتم العثور على كود التسجيل', 'danger')
    
    conn.close()
    return redirect(url_for('telegram_codes.telegram_codes'))

@telegram_codes_bp.route('/admin/telegram-codes/export', methods=['GET'])
@login_required
def export_codes():
    if not current_user.is_admin:
        flash('يجب أن تكون مسؤولاً للوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('index'))
    
    codes = get_all_codes()
    
    # Create CSV file
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Code', 'Used', 'Created At', 'User ID', 'Username', 'Registered At'])
    
    for code in codes:
        cw.writerow([
            code['id'], 
            code['code'], 
            'Yes' if code['is_used'] else 'No', 
            code['created_at'],
            code['user_id'] if code['user_id'] else '',
            code['username'] if code['username'] else '',
            code['registered_at'] if code['registered_at'] else ''
        ])
    
    output = si.getvalue()
    
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=telegram_codes.csv"}
    )
