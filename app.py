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

# Initialize Flask app
app = Flask(__name__)
app.config.from_object('config')
app.secret_key = 'wallet_sms_analyzer_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'يرجى تسجيل الدخول للوصول إلى هذه الصفحة'
login_manager.login_message_category = 'info'

# Configure PostgreSQL database
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://metabit_safty_db_user:i7jQbcMMM2sg7k12PwweDO1koIUd3ppF@dpg-cvc9e8bv2p9s73ad9g5g-a.singapore-postgres.render.com/metabit_safty_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database and migration
db.init_app(app)
migrate = Migrate(app, db)

# Configure CORS
CORS(app, resources={r"/api/*": {"origins": "*"}})

# API Key - In production, store in environment variables
API_KEY = "MetaBit_API_Key_24X7"

# Wallet types
WALLET_TYPES = ['Jaib', 'Jawali', 'Cash', 'KuraimiIMB', 'ONE Cash']

# Yemen timezone configuration
YEMEN_TIMEZONE = pytz.timezone('Asia/Aden')

# Helper functions
def format_yemen_datetime(dt_str=None):
    """Format datetime according to Yemen timezone"""
    if dt_str:
        try:
            dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            dt = pytz.utc.localize(dt).astimezone(YEMEN_TIMEZONE)
        except:
            return dt_str
    else:
        dt = datetime.now(YEMEN_TIMEZONE)
    
    return format_datetime(dt, format='dd/MM/yyyy hh:mm:ss a', locale='ar_YE')

# Template filter for Yemen time
@app.template_filter('yemen_time')
def yemen_time_filter(dt_str):
    """Convert datetime to 12-hour format"""
    try:
        dt = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        dt = dt.replace(tzinfo=pytz.UTC).astimezone(YEMEN_TIMEZONE)
        return dt.strftime('%I:%M:%S %p %d/%m/%Y')
    except:
        return dt_str

# Currency symbols and codes
CURRENCIES = {
    'ر.ي': 'YER',
    'ر.س': 'SAR',
    'د.أ': 'USD'
}

# Ensure data directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Inject current time into all templates
@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# SMS Parsing Functions
def parse_jaib_sms(message):
    """Parse SMS messages from Jaib wallet."""
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
        currency_raw = amount_match.group(2).strip()
        transaction['currency'] = CURRENCIES.get(currency_raw, currency_raw)
    
    balance_match = re.search(r'رص:(\d+(?:\.\d+)?)([^م]+)', message)
    if balance_match:
        transaction['balance'] = float(balance_match.group(1))
        balance_currency_raw = balance_match.group(2).strip()
        transaction['balance_currency'] = CURRENCIES.get(balance_currency_raw, balance_currency_raw)
    
    if 'مقابل' in message:
        details_match = re.search(r'مقابل ([^ر]+)', message)
        if details_match:
            transaction['details'] = details_match.group(1).strip()
    
    if 'من' in message and 'مقابل' in message:
        sender_match = re.search(r'من (.+?)(?:$|\n)', message)
        if sender_match:
            transaction['counterparty'] = sender_match.group(1).strip()
    elif 'الى' in message:
        recipient_match = re.search(r'الى (.+?)(?:$|\n)', message)
        if recipient_match:
            transaction['counterparty'] = recipient_match.group(1).strip()
    
    return transaction

# [Other parsing functions: parse_jawali_sms, parse_cash_sms, parse_kuraimi_sms, parse_onecash_sms]
# ... (include all other parsing functions here)

def parse_sms(sms_text):
    """Parse SMS text to extract transaction data."""
    transactions = []
    sms_messages = re.split(r'\n\s*\n', sms_text)
    
    for message in sms_messages:
        if not message.strip():
            continue
        
        wallet_match = re.search(r'From: ([^\n]+)', message)
        if not wallet_match:
            continue
        
        wallet_name = wallet_match.group(1).strip()
        message_body = message.replace(wallet_match.group(0), '').strip()
        
        transaction = None
        
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
        else:
            if 'محفظة جيب' in message_body:
                transaction = parse_jaib_sms(message_body)
                wallet_name = 'Jaib'
            elif 'جوالي' in message_body:
                transaction = parse_jawali_sms(message_body)
                wallet_name = 'Jawali'
            elif 'كاش' in message_body and not 'ون كاش' in message_body:
                transaction = parse_cash_sms(message_body)
                wallet_name = 'Cash'
            elif 'الكريمي' in message_body or 'كريمي' in message_body:
                transaction = parse_kuraimi_sms(message_body)
                wallet_name = 'KuraimiIMB'
            elif 'ون كاش' in message_body or 'ONE' in message_body:
                transaction = parse_onecash_sms(message_body)
                wallet_name = 'ONE Cash'
            
        if transaction and all(key in transaction for key in ['amount', 'currency']):
            transaction['wallet'] = wallet_name
            transaction['raw_message'] = message
            transaction['timestamp'] = datetime.now(YEMEN_TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')
            transactions.append(transaction)
    
    return transactions

# Database Operations
def save_transactions(transactions):
    """Save transactions to the database."""
    count = 0
    for tx_data in transactions:
        transaction = Transaction.from_dict(tx_data)
        db.session.add(transaction)
        count += 1
    db.session.commit()
    return count

def load_transactions():
    """Load all transactions from the database."""
    transactions = Transaction.query.all()
    return [transaction.to_dict() for transaction in transactions]

# [Other helper functions: generate_transaction_summary, generate_charts, generate_wallet_charts]
# ... (include all other helper functions here)

# Routes
@app.route('/')
@login_required
def index():
    """Render the home page."""
    try:
        transactions = Transaction.query.order_by(Transaction.timestamp.desc()).all()
        wallets = {}
        for transaction in transactions:
            if transaction.wallet not in wallets:
                wallets[transaction.wallet] = {'total': 0, 'currencies': {}}
            
            if transaction.currency not in wallets[transaction.wallet]['currencies']:
                wallets[transaction.wallet]['currencies'][transaction.currency] = 0
            
            wallets[transaction.wallet]['currencies'][transaction.currency] += 1
            wallets[transaction.wallet]['total'] += 1
        
        summary = {}
        currencies = ['YER', 'SAR', 'USD']
        
        for wallet in WALLET_TYPES:
            summary[wallet] = {}
            for currency in currencies:
                summary[wallet][currency] = {'credits': 0, 'debits': 0, 'net': 0}
                
            for transaction in [t for t in transactions if t.wallet == wallet]:
                if transaction.type == 'credit':
                    summary[wallet][transaction.currency]['credits'] += transaction.amount
                else:
                    summary[wallet][transaction.currency]['debits'] += transaction.amount
                
                summary[wallet][transaction.currency]['net'] = (
                    summary[wallet][transaction.currency]['credits'] - 
                    summary[wallet][transaction.currency]['debits']
                )
        
        charts = generate_wallet_charts(transactions)
        
        response = make_response(render_template(
            'index.html',
            wallets=wallets,
            transactions=transactions,
            summary=summary,
            charts=charts,
            now=format_yemen_datetime()
        ))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception as e:
        print(f"Error in index: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Server error: {str(e)}'
        }), 500

# [All other routes: /wallet/<wallet_name>, /upload, /clear, /api endpoints, etc.]
# ... (include all other routes here)

# Login and User Management
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
    """Login page for admins."""
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
            return redirect(url_for('login'))
        
        login_user(user, remember=form.remember_me.data)
        user.last_login = datetime.now()
        db.session.commit()
        
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'):
            next_page = url_for('admin_dashboard')
        return redirect(next_page)
    
    now = datetime.now()
    return render_template('login.html', title='تسجيل الدخول', form=form, now=now)

# [Other user management routes: /logout, /admin, /create-user, etc.]
# ... (include all other user management routes here)

# Main Application Entry Point
if __name__ == '__main__':
    # Ensure the upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Create database tables
    with app.app_context():
        db.create_all()
        
        # Create default admin user if no users exist
        if User.query.count() == 0:
            print("Creating default admin user...")
            default_admin = User(
                username="admin",
                email="admin@metabit.com",
                is_admin=True
            )
            default_admin.set_password("MetaBit@2025")
            db.session.add(default_admin)
            db.session.commit()
            print("Default admin user created:")
            print("Username: admin")
            print("Password: MetaBit@2025")
            print("Please change password after login.")
    
    # Get port from environment variable
    port = int(os.environ.get('PORT', 5000))
    
    # Run the app
    app.run(host='0.0.0.0', port=port, debug=True)
