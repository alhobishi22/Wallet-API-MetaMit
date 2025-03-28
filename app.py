from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_bootstrap import Bootstrap
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import datetime
import json
import os
import re
import pytz
from babel.dates import format_datetime
from flask_cors import CORS
import pandas as pd
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from models import db, Transaction, User
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from functools import wraps

# Initialize Flask Application
app = Flask(__name__)
app.config.from_object('config')
app.secret_key = 'wallet_sms_analyzer_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# Flask-Login Configuration
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يرجى تسجيل الدخول للوصول إلى هذه الصفحة'
login_manager.login_message_category = 'info'

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://metabit_safty_db_user:i7jQbcMMM2sg7k12PwweDO1koIUd3ppF@dpg-cvc9e8bv2p9s73ad9g5g-a.singapore-postgres.render.com/metabit_safty_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize Extensions
db.init_app(app)
migrate = Migrate(app, db)
Bootstrap(app)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Constants
API_KEY = "MetaBit_API_Key_24X7"
WALLET_TYPES = ['Jaib', 'Jawali', 'Cash', 'KuraimiIMB', 'ONE Cash']
YEMEN_TIMEZONE = pytz.timezone('Asia/Aden')
CURRENCIES = {'ر.ي': 'YER', 'ر.س': 'SAR', 'د.أ': 'USD'}

# Helper Functions
def format_yemen_datetime(dt_str=None):
    """Format datetime in Yemen timezone"""
    if dt_str:
        try:
            dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            dt = pytz.utc.localize(dt).astimezone(YEMEN_TIMEZONE)
        except:
            return dt_str
    else:
        dt = datetime.now(YEMEN_TIMEZONE)
    return format_datetime(dt, format='dd/MM/yyyy hh:mm:ss a', locale='ar_YE')

@app.template_filter('yemen_time')
def yemen_time_filter(dt_str):
    """Convert to 12-hour Yemen time format"""
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        dt = dt.replace(tzinfo=pytz.UTC).astimezone(YEMEN_TIMEZONE)
        return dt.strftime('%I:%M:%S %p %d/%m/%Y')
    except:
        return dt_str

# SMS Parsing Functions
def parse_jaib_sms(message):
    """Parse Jaib wallet SMS messages"""
    transaction = {}
    if 'اضيف' in message:
        transaction['type'] = 'credit'
        amount_pattern = r'اضيف (\d+(?:\.\d+)?)([^م]+)'
    elif 'خصم' in message:
        transaction['type'] = 'debit'
        amount_pattern = r'خصم (\d+(?:\.\d+)?)([^م]+)'
    else:
        return None

    amount_match = re.search(amount_pattern, message)
    if amount_match:
        transaction['amount'] = float(amount_match.group(1))
        transaction['currency'] = CURRENCIES.get(amount_match.group(2).strip(), 'YER')

    balance_match = re.search(r'رص:(\d+(?:\.\d+)?)([^م]+)', message)
    if balance_match:
        transaction['balance'] = float(balance_match.group(1))
        transaction['balance_currency'] = CURRENCIES.get(balance_match.group(2).strip(), 'YER')

    if 'مقابل' in message:
        details_match = re.search(r'مقابل ([^ر]+)', message)
        if details_match:
            transaction['details'] = details_match.group(1).strip()

    return transaction

def parse_jawali_sms(message):
    """Parse Jawali wallet SMS messages"""
    transaction = {}
    if 'استلمت مبلغ' in message:
        transaction['type'] = 'credit'
        amount_match = re.search(r'استلمت مبلغ (\d+(?:\.\d+)?) ([A-Z]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1))
            transaction['currency'] = amount_match.group(2)

        balance_match = re.search(r'رصيدك هو (\d+(?:\.\d+)?)', message)
        if balance_match:
            transaction['balance'] = float(balance_match.group(1))
            transaction['balance_currency'] = 'YER'

    return transaction

def parse_cash_sms(message):
    """Parse Cash wallet SMS messages"""
    transaction = {}
    if 'إضافة' in message:
        transaction['type'] = 'credit'
        amount_match = re.search(r'إضافة(\d+(?:\.\d+)?) ([A-Z]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1))
            transaction['currency'] = amount_match.group(2)

        balance_match = re.search(r'رصيدك(\d+(?:\.\d+)?)([A-Z]+)', message)
        if balance_match:
            transaction['balance'] = float(balance_match.group(1))
            transaction['balance_currency'] = amount_match.group(2)

    elif 'سحب' in message:
        transaction['type'] = 'debit'
        amount_match = re.search(r'سحب (\d+(?:\.\d+)?) ([A-Z]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1))
            transaction['currency'] = amount_match.group(2)

    return transaction

def parse_kuraimi_sms(message):
    """Parse Kuraimi IMB SMS messages"""
    transaction = {}
    if 'أودع' in message:
        transaction['type'] = 'credit'
        amount_match = re.search(r'لحسابك(\d+(?:[\.\,]\d+)?) ([A-Z]+)', message)
        if amount_match:
            amount_str = amount_match.group(1).replace('٫', '.')
            transaction['amount'] = float(amount_str)
            transaction['currency'] = amount_match.group(2)

        balance_match = re.search(r'رصيدك(\d+(?:[\.٫\,]\d+)?)([A-Z]+)', message)
        if balance_match:
            balance_str = balance_match.group(1).replace('٫', '.')
            transaction['balance'] = float(balance_str)
            transaction['balance_currency'] = balance_match.group(2)

    return transaction

def parse_onecash_sms(message):
    """Parse ONE Cash wallet SMS messages"""
    transaction = {}
    if 'استلمت' in message:
        transaction['type'] = 'credit'
        amount_match = re.search(r'استلمت ([0-9,.]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1).replace(',', ''))
            transaction['currency'] = 'YER'

        balance_match = re.search(r'رصيدك([0-9,.]+) (ر\.ي)', message)
        if balance_match:
            transaction['balance'] = float(balance_match.group(1).replace(',', ''))
            transaction['balance_currency'] = 'YER'

    elif 'حولت' in message:
        transaction['type'] = 'debit'
        amount_match = re.search(r'حولت([0-9,.]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1).replace(',', ''))
            transaction['currency'] = 'YER'

    return transaction

def parse_sms(sms_text):
    """Main SMS parsing function"""
    transactions = []
    sms_messages = re.split(r'\n\s*\n', sms_text)
    
    for message in sms_messages:
        wallet_match = re.search(r'From: ([^\n]+)', message)
        if not wallet_match:
            continue
            
        wallet_name = wallet_match.group(1).strip()
        message_body = message.replace(wallet_match.group(0), '').strip()
        transaction = None
        
        # Determine parser based on wallet type
        if wallet_name == 'Jaib':
            transaction = parse_jaib_sms(message_body)
        elif wallet_name == 'Jawali':
            transaction = parse_jawali_sms(message_body)
        elif wallet_name == 'Cash':
            transaction = parse_cash_sms(message_body)
        elif wallet_name == 'KuraimiIMB':
            transaction = parse_kuraimi_sms(message_body)
        elif wallet_name == 'ONE Cash':
            transaction = parse_onecash_sms(message_body)
        
        if transaction:
            transaction.update({
                'wallet': wallet_name,
                'raw_message': message,
                'timestamp': datetime.now(YEMEN_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            })
            transactions.append(transaction)
    
    return transactions

# Database Operations
def save_transactions(transactions):
    """Save transactions to database"""
    try:
        for tx_data in transactions:
            transaction = Transaction(
                wallet=tx_data['wallet'],
                type=tx_data['type'],
                amount=tx_data['amount'],
                currency=tx_data['currency'],
                balance=tx_data.get('balance', 0),
                details=tx_data.get('details', ''),
                timestamp=tx_data['timestamp']
            )
            db.session.add(transaction)
        db.session.commit()
        return len(transactions)
    except Exception as e:
        db.session.rollback()
        raise e

# Routes
@app.route('/')
@login_required
def index():
    """Main dashboard"""
    transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
    summary = {}
    
    # Generate wallet summary
    for wallet in WALLET_TYPES:
        summary[wallet] = {
            'YER': {'credits': 0, 'debits': 0, 'net': 0},
            'SAR': {'credits': 0, 'debits': 0, 'net': 0},
            'USD': {'credits': 0, 'debits': 0, 'net': 0}
        }
        
        for tx in Transaction.query.filter_by(wallet=wallet):
            if tx.type == 'credit':
                summary[wallet][tx.currency]['credits'] += tx.amount
            else:
                summary[wallet][tx.currency]['debits'] += tx.amount
            summary[wallet][tx.currency]['net'] = (
                summary[wallet][tx.currency]['credits'] - 
                summary[wallet][tx.currency]['debits']
            )
    
    return render_template('index.html',
                         transactions=transactions,
                         summary=summary,
                         now=format_yemen_datetime())

@app.route('/upload', methods=['POST'])
@login_required
def upload_sms():
    """Handle SMS upload"""
    sms_text = request.form.get('sms_text')
    if not sms_text:
        flash('لم يتم تقديم نص الرسائل', 'error')
        return redirect(url_for('index'))
    
    try:
        transactions = parse_sms(sms_text)
        num_saved = save_transactions(transactions)
        flash(f'تم معالجة {num_saved} معاملة بنجاح', 'success')
    except Exception as e:
        flash(f'خطأ في معالجة الرسائل: {str(e)}', 'danger')
    
    return redirect(url_for('index'))

# API Endpoints
@app.route('/api/transactions', methods=['GET'])
def api_get_transactions():
    """Get transactions via API"""
    if request.headers.get('X-API-Key') != API_KEY:
        return jsonify({'error': 'غير مصرح به'}), 401
    
    transactions = Transaction.query.all()
    return jsonify([{
        'id': tx.id,
        'wallet': tx.wallet,
        'type': tx.type,
        'amount': tx.amount,
        'currency': tx.currency,
        'timestamp': tx.timestamp.isoformat()
    } for tx in transactions])

# User Management
class LoginForm(FlaskForm):
    username = StringField('اسم المستخدم', validators=[DataRequired()])
    password = PasswordField('كلمة المرور', validators=[DataRequired()])
    remember_me = BooleanField('تذكرني')
    submit = SubmitField('تسجيل الدخول')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember_me.data)
            return redirect(url_for('index'))
        flash('بيانات الدخول غير صحيحة', 'danger')
    
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    """User logout"""
    logout_user()
    return redirect(url_for('login'))

# Admin Panel
@app.route('/admin')
@login_required
def admin_dashboard():
    """Admin dashboard"""
    if not current_user.is_admin:
        flash('صلاحيات غير كافية', 'danger')
        return redirect(url_for('index'))
    
    users = User.query.all()
    return render_template('admin.html', users=users)

# Database Initialization
def create_default_admin():
    """Create default admin user"""
    with app.app_context():
        if User.query.count() == 0:
            admin = User(
                username='admin',
                email='admin@example.com',
                is_admin=True
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()

# Application Startup
if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    create_default_admin()
    app.run(host='0.0.0.0', port=5000, debug=True)
