from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
import os
from flask_migrate import Migrate
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, FloatField, DateField, FileField
from wtforms.validators import DataRequired, Optional
import io
import xlsxwriter
from flask import send_file
from admin_telegram_codes import telegram_codes_bp
import json
from markupsafe import Markup
import re
import logging
import time
from sqlalchemy.exc import OperationalError, SQLAlchemyError
import asyncio
from telegram_bot import send_new_report_notification

# إعداد التسجيل
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# دالة إعادة المحاولة للاتصال بقاعدة البيانات
def db_retry(func):
    def wrapper(*args, **kwargs):
        max_retries = 3
        retry_delay = 1  # ثانية
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                if "SSL connection has been closed unexpectedly" in str(e) and attempt < max_retries - 1:
                    logger.warning(f"SSL connection error, retrying ({attempt+1}/{max_retries}): {str(e)}")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # زيادة وقت الانتظار بشكل تصاعدي
                    # إعادة تهيئة الاتصال
                    db.session.remove()
                else:
                    logger.error(f"Database operational error after {attempt+1} attempts: {str(e)}")
                    raise
            except SQLAlchemyError as e:
                logger.error(f"SQLAlchemy error: {str(e)}")
                raise
    return wrapper

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))

# تعديل رابط قاعدة البيانات للتوافق مع PostgreSQL على Render
database_url = os.environ.get('DATABASE_URL', 'sqlite:///fraud_reports.db')
# تعديل رابط PostgreSQL إذا كان يبدأ بـ postgres:// (تغييره إلى postgresql://)
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

# إضافة معلمات SSL للتعامل مع مشاكل الاتصال
if database_url and 'postgresql' in database_url:
    # إضافة معلمات SSL إذا لم تكن موجودة بالفعل
    if '?' not in database_url:
        database_url += '?'
    else:
        database_url += '&'
    database_url += 'connect_timeout=10&keepalives=1&keepalives_idle=5&keepalives_interval=2&keepalives_count=3&sslmode=require'

print(f"استخدام قاعدة البيانات: {database_url.split('@')[0] + '@***' if '@' in database_url else database_url}")

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,  # فحص الاتصال قبل استخدامه
    'pool_recycle': 280,    # إعادة تدوير الاتصالات كل 280 ثانية (أقل من 5 دقائق)
    'pool_timeout': 30,     # انتهاء مهلة الاتصال بعد 30 ثانية
    'max_overflow': 10,     # السماح بـ 10 اتصالات إضافية فوق حجم المجمع
    'pool_size': 5          # حجم مجمع الاتصالات الافتراضي
}
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Register blueprints
app.register_blueprint(telegram_codes_bp)

# تكوين معالج الأخطاء
@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    app.logger.error(f"Internal Server Error: {str(error)}")
    import traceback
    app.logger.error(traceback.format_exc())
    return render_template('error.html', error=error), 500

@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error=error), 404

# Add zip to Jinja2 globals
app.jinja_env.globals.update(zip=zip)

# إضافة فلتر nl2br
@app.template_filter('nl2br')
def nl2br_filter(s):
    if s:
        s = s.replace('\n', Markup('<br>'))
        return Markup(s)
    return ''

# إضافة فلتر tojson
@app.template_filter('tojson')
def tojson_filter(s):
    return json.dumps(s, ensure_ascii=False)

# إضافة فلتر fromjson
@app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return json.loads(s)
    except:
        return {}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# تعريف نموذج المستخدم
class User(UserMixin, db.Model):
    __tablename__ = 'users'  # تأكيد اسم الجدول
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_admin = db.Column(db.Boolean, default=False)
    reports = db.relationship('Report', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # scammer, debt
    debt_amount = db.Column(db.Float)
    debt_date = db.Column(db.Date)
    scammer_name = db.Column(db.Text)
    scammer_phone = db.Column(db.Text)
    wallet_address = db.Column(db.Text)
    network_type = db.Column(db.Text)
    paypal = db.Column(db.String(100))
    payer = db.Column(db.String(100))
    perfect_money = db.Column(db.String(100))
    alkremi_bank = db.Column(db.String(100))
    jeeb_wallet = db.Column(db.String(100))
    jawali_wallet = db.Column(db.String(100))
    cash_wallet = db.Column(db.String(100))
    one_cash = db.Column(db.String(100))
    custom_fields = db.Column(db.Text)  # تخزين الحقول المخصصة كـ JSON
    description = db.Column(db.Text)
    media_files = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ReportForm(FlaskForm):
    type = SelectField('نوع البلاغ', choices=[('scammer', 'نصاب'), ('debt', 'مديونية')], validators=[DataRequired()])
    debt_amount = FloatField('قيمة المديونية', validators=[Optional()])
    debt_date = DateField('تاريخ المديونية', validators=[Optional()])
    scammer_name = StringField('اسم النصاب', validators=[DataRequired()])
    scammer_phone = StringField('رقم الهاتف', validators=[DataRequired()])
    wallet_address = StringField('عنوان المحفظة', validators=[Optional()])
    network_type = StringField('نوع الشبكة', validators=[Optional()])
    paypal = StringField('PayPal', validators=[Optional()])
    payer = StringField('Payer', validators=[Optional()])
    perfect_money = StringField('Perfect Money', validators=[Optional()])
    alkremi_bank = StringField('بنك الكريمي', validators=[Optional()])
    jeeb_wallet = StringField('محفظة جيب', validators=[Optional()])
    jawali_wallet = StringField('محفظة جوالي', validators=[Optional()])
    cash_wallet = StringField('محفظة كاش', validators=[Optional()])
    one_cash = StringField('ون كاش', validators=[Optional()])
    description = TextAreaField('الوصف', validators=[DataRequired()])
    media_files = FileField('الملفات المرفقة', validators=[Optional()])
    custom_fields = TextAreaField('الحقول المخصصة', validators=[Optional()])

@login_manager.user_loader
@db_retry
def load_user(id):
    return db.session.get(User, int(id))

@app.route('/')
@login_required
def index():
    # إحصائيات النظام
    total_reports = Report.query.count()
    scammer_reports = Report.query.filter_by(type='scammer').count()
    debt_reports = Report.query.filter_by(type='debt').count()
    total_users = User.query.count()
    
    # آخر البلاغات
    latest_reports = Report.query.order_by(Report.created_at.desc()).limit(4).all()
    
    return render_template('index.html', 
                         total_reports=total_reports,
                         scammer_reports=scammer_reports,
                         debt_reports=debt_reports,
                         total_users=total_users,
                         latest_reports=latest_reports)

@app.route('/search')
@login_required
def search():
    query = request.args.get('q', '')
    report_type = request.args.get('type', 'all')
    search_results = []
    duplicates = {}
    
    if query:
        # تحديد نوع البحث
        reports_query = Report.query
        if report_type != 'all':
            reports_query = reports_query.filter_by(type=report_type)
        
        reports = reports_query.all()
        search_results = []
        
        for report in reports:
            report_data = {
                'id': report.id,
                'type': report.type,
                'scammer_name': report.scammer_name,
                'scammer_phone': report.scammer_phone,
                'username': report.user.username,
                'creation_date': report.created_at,
                'debt_amount': report.debt_amount,
                'wallet_address': report.wallet_address,
                'wallet_type': report.network_type,
                'custom_fields': {},
                'description': report.description
            }
            
            # معالجة الحقول المخصصة
            if report.custom_fields and report.custom_fields.strip():
                # محاولة معالجة البيانات كـ JSON
                if report.custom_fields.strip().startswith('{') and report.custom_fields.strip().endswith('}'):
                    try:
                        custom_data = json.loads(report.custom_fields)
                        # تصفية قيم "nan" من الحقول المخصصة
                        for key, value in custom_data.items():
                            if isinstance(value, str):
                                if value.lower() != "nan" and value.strip():
                                    report_data['custom_fields'][key] = value
                                elif value.strip():
                                    report_data['custom_fields'][key] = "لا يوجد"
                            elif value is not None:
                                report_data['custom_fields'][key] = str(value)
                    except json.JSONDecodeError:
                        pass
                
                # إذا لم تكن بيانات JSON أو فشل التحليل، نحاول التعامل معها كنص عادي
                if not report_data['custom_fields'] and ':' in report.custom_fields:
                    lines = report.custom_fields.split('\n')
                    for line in lines:
                        if ':' in line:
                            parts = line.split(':', 1)
                            key = parts[0].strip()
                            value = parts[1].strip()
                            if value and value.lower() != "nan":
                                report_data['custom_fields'][key] = value
                            elif value.strip():
                                report_data['custom_fields'][key] = "لا يوجد"
                        elif line.strip() and line.strip().lower() != "nan":
                            # إذا لم يكن هناك ":" في السطر، نستخدم السطر كمفتاح وقيمة
                            report_data['custom_fields'][f"حقل {len(report_data['custom_fields']) + 1}"] = line.strip()
            
            # البحث في جميع الحقول
            match_found = False
            search_fields = [
                report.scammer_name, 
                report.scammer_phone, 
                report.wallet_address, 
                report.network_type,
                report.paypal, 
                report.payer, 
                report.perfect_money,
                report.alkremi_bank, 
                report.jeeb_wallet, 
                report.jawali_wallet,
                report.cash_wallet, 
                report.one_cash
            ]
            
            # تنظيف حقول البحث من قيم "nan"
            for i, field in enumerate(search_fields):
                if field and isinstance(field, str) and field.lower() == "nan":
                    search_fields[i] = ""
            
            # البحث في وصف البلاغ
            if report.description and query.lower() in report.description.lower():
                match_found = True
            
            # البحث في الحقول الأساسية
            if not match_found:
                for field in search_fields:
                    if field and query.lower() in field.lower():
                        match_found = True
                        break
            
            # البحث في الحقول المخصصة (فقط في القيم وليس في أسماء الحقول)
            if not match_found and report_data['custom_fields']:
                for field_name, field_value in report_data['custom_fields'].items():
                    if isinstance(field_value, str) and query.lower() in field_value.lower():
                        match_found = True
                        break
            
            if match_found:
                search_results.append(report_data)
        
        # Count duplicates across all reports
        all_reports = Report.query.all()
        
        # Process phone numbers
        for r in all_reports:
            if r.scammer_phone:
                phones = r.scammer_phone.split('|')
                for phone in phones:
                    phone = phone.strip()
                    if phone and phone.lower() != "nan":
                        duplicates[phone] = duplicates.get(phone, 0) + 1
        
        # Process names
        for r in all_reports:
            if r.scammer_name:
                names = r.scammer_name.split('|')
                for name in names:
                    name = name.strip()
                    if name and name.lower() != "nan":
                        duplicates[name] = duplicates.get(name, 0) + 1
        
        # Process wallet addresses
        for r in all_reports:
            if r.wallet_address:
                addresses = r.wallet_address.split('|')
                for addr in addresses:
                    addr = addr.strip()
                    if addr and addr.lower() != "nan":
                        duplicates[addr] = duplicates.get(addr, 0) + 1
        
        # Process payment methods
        payment_fields = ['paypal', 'payer', 'perfect_money', 'alkremi_bank', 
                         'jeeb_wallet', 'jawali_wallet', 'cash_wallet', 'one_cash']
        
        for r in all_reports:
            for field in payment_fields:
                value = getattr(r, field)
                if value and value.strip() and value.lower() != "nan":
                    duplicates[value] = duplicates.get(value, 0) + 1
        
        # إضافة الحقول المخصصة للتكرارات
        for r in all_reports:
            if r.custom_fields and r.custom_fields.strip():
                try:
                    # محاولة معالجة البيانات كـ JSON
                    if r.custom_fields.strip().startswith('{') and r.custom_fields.strip().endswith('}'):
                        custom_data = json.loads(r.custom_fields)
                        for key, value in custom_data.items():
                            if isinstance(value, str) and value.strip() and value.lower() != "nan":
                                duplicates[value.strip()] = duplicates.get(value.strip(), 0) + 1
                    else:
                        # معالجة البيانات كنص عادي
                        lines = r.custom_fields.split('\n')
                        for line in lines:
                            if ':' in line:
                                parts = line.split(':', 1)
                                value = parts[1].strip()
                                if value and value.lower() != "nan":
                                    duplicates[value] = duplicates.get(value, 0) + 1
                except:
                    pass
    
    return render_template('search.html', query=query, report_type=report_type, results=search_results, duplicates=duplicates)

@app.route('/report', methods=['GET', 'POST'])
@login_required
def report():
    if not current_user.is_authenticated:
        flash('يجب تسجيل الدخول لإضافة بلاغ جديد', 'warning')
        return redirect(url_for('login', next=request.path))

    form = ReportForm()
    if request.method == 'POST':
        # جمع البيانات من النموذج
        report_type = request.form.get('type')
        debt_amount = request.form.get('debt_amount')
        debt_date = request.form.get('debt_date')
        
        # جمع الأسماء المتعددة
        scammer_names = request.form.getlist('scammer_name')
        scammer_name = '|'.join(filter(None, scammer_names))
        
        # جمع أرقام الهواتف المتعددة
        scammer_phones = request.form.getlist('scammer_phone')
        scammer_phone = '|'.join(filter(None, scammer_phones))
        
        # جمع عناوين المحافظ وأنواع الشبكات
        wallet_addresses = request.form.getlist('wallet_address')
        network_types = request.form.getlist('network_type')
        wallet_address = '|'.join(filter(None, wallet_addresses))
        network_type = '|'.join(filter(None, network_types))

        # معالجة الحقول المخصصة
        custom_fields_data = {}
        
        # الحصول على جميع الحقول من النموذج
        for key in request.form:
            if key.startswith('custom_field_name_'):
                index = key.split('_')[-1]
                field_name = request.form.get(f'custom_field_name_{index}')
                field_value = request.form.get(f'custom_field_value_{index}')
                if field_name and field_value:
                    custom_fields_data[field_name] = field_value
        
        # تحويل الحقول المخصصة إلى JSON
        custom_fields_json = json.dumps(custom_fields_data, ensure_ascii=False) if custom_fields_data else '{}'

        # التحقق من صحة البيانات
        if not scammer_name:
            flash('يجب إدخال اسم النصاب', 'danger')
            return render_template('report.html', form=form)
        
        if not scammer_phone:
            flash('يجب إدخال رقم هاتف النصاب', 'danger')
            return render_template('report.html', form=form)
        
        if not report_type:
            flash('يجب اختيار نوع البلاغ', 'danger')
            return render_template('report.html', form=form)
        
        # إنشاء كائن البلاغ
        try:
            report = Report(
                user_id=current_user.id,
                type=report_type,
                scammer_name=scammer_name,
                scammer_phone=scammer_phone,
                wallet_address=wallet_address,
                network_type=network_type,
                paypal=request.form.get('paypal'),
                payer=request.form.get('payer'),
                perfect_money=request.form.get('perfect_money'),
                alkremi_bank=request.form.get('alkremi_bank'),
                jeeb_wallet=request.form.get('jeeb_wallet'),
                jawali_wallet=request.form.get('jawali_wallet'),
                cash_wallet=request.form.get('cash_wallet'),
                one_cash=request.form.get('one_cash'),
                description=request.form.get('description'),
                custom_fields=custom_fields_json
            )
            
            # إضافة معلومات المديونية إذا كان نوع البلاغ مديونية
            if report_type == 'debt':
                if debt_amount:
                    report.debt_amount = float(debt_amount)
                if debt_date:
                    report.debt_date = datetime.strptime(debt_date, '%Y-%m-%d').date()
            
            # معالجة الملفات المرفقة
            if 'media_files' in request.files:
                files = request.files.getlist('media_files')
                file_paths = []
                
                for file in files:
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        # إضافة طابع زمني لتجنب تكرار أسماء الملفات
                        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                        unique_filename = f"{timestamp}_{filename}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                        file.save(file_path)
                        file_paths.append(unique_filename)
                
                if file_paths:
                    report.media_files = '|'.join(file_paths)
            
            db.session.add(report)
            db.session.commit()
            
            # إرسال إشعار عبر تلجرام
            report_data = {
                'id': report.id,
                'type': report.type,
                'scammer_name': report.scammer_name,
                'scammer_phone': report.scammer_phone,
                'created_at': report.created_at.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # إرسال الإشعار بشكل غير متزامن
            def send_telegram_notification():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(send_new_report_notification(report_data))
                loop.close()
            
            # تشغيل الإشعار في خلفية منفصلة
            import threading
            notification_thread = threading.Thread(target=send_telegram_notification)
            notification_thread.daemon = True
            notification_thread.start()
            
            flash('تم إضافة البلاغ بنجاح', 'success')
            return redirect(url_for('index'))
        except OperationalError as e:
            db.session.rollback()
            logger.error(f"Database operational error: {str(e)}")
            flash('حدث خطأ أثناء حفظ البلاغ. الرجاء المحاولة مرة أخرى.', 'danger')
            return render_template('report.html', form=form)
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"SQLAlchemy error: {str(e)}")
            flash('حدث خطأ أثناء حفظ البلاغ. الرجاء المحاولة مرة أخرى.', 'danger')
            return render_template('report.html', form=form)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error: {str(e)}")
            flash('حدث خطأ أثناء حفظ البلاغ. الرجاء المحاولة مرة أخرى.', 'danger')
            return render_template('report.html', form=form)

    return render_template('report.html', form=form)

@app.route('/edit_report/<int:report_id>', methods=['GET', 'POST'])
@login_required
def edit_report(report_id):
    report = Report.query.get_or_404(report_id)
    
    # التحقق من أن المستخدم هو صاحب البلاغ أو مدير
    if report.user_id != current_user.id and not current_user.is_admin:
        flash('ليس لديك صلاحية تعديل هذا البلاغ', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # جمع البيانات من النموذج
        report_type = request.form.get('type')
        debt_amount = request.form.get('debt_amount')
        debt_date = request.form.get('debt_date')
        
        # جمع الأسماء المتعددة
        scammer_names = request.form.getlist('scammer_name')
        scammer_name = '|'.join(filter(None, scammer_names))
        
        # جمع أرقام الهواتف المتعددة
        scammer_phones = request.form.getlist('scammer_phone')
        scammer_phone = '|'.join(filter(None, scammer_phones))
        
        # جمع عناوين المحافظ وأنواع الشبكات
        wallet_addresses = request.form.getlist('wallet_address')
        network_types = request.form.getlist('network_type')
        wallet_address = '|'.join(filter(None, wallet_addresses))
        network_type = '|'.join(filter(None, network_types))

        # معالجة الحقول المخصصة
        custom_fields_data = {}
        
        # الحصول على جميع الحقول من النموذج
        for key in request.form:
            if key.startswith('custom_field_name_'):
                index = key.split('_')[-1]
                field_name = request.form.get(f'custom_field_name_{index}')
                field_value = request.form.get(f'custom_field_value_{index}')
                if field_name and field_value:
                    custom_fields_data[field_name] = field_value
        
        # تحويل الحقول المخصصة إلى JSON
        custom_fields_json = json.dumps(custom_fields_data, ensure_ascii=False) if custom_fields_data else '{}'

        # التحقق من صحة البيانات
        if not scammer_name:
            flash('يجب إدخال اسم النصاب', 'danger')
            return render_template('edit_report.html', report=report)
        
        if not scammer_phone:
            flash('يجب إدخال رقم هاتف النصاب', 'danger')
            return render_template('edit_report.html', report=report)
        
        if not report_type:
            flash('يجب اختيار نوع البلاغ', 'danger')
            return render_template('edit_report.html', report=report)
        
        # تحديث البلاغ
        try:
            report.type = report_type
            report.scammer_name = scammer_name
            report.scammer_phone = scammer_phone
            report.wallet_address = wallet_address
            report.network_type = network_type
            report.paypal = request.form.get('paypal')
            report.payer = request.form.get('payer')
            report.perfect_money = request.form.get('perfect_money')
            report.alkremi_bank = request.form.get('alkremi_bank')
            report.jeeb_wallet = request.form.get('jeeb_wallet')
            report.jawali_wallet = request.form.get('jawali_wallet')
            report.cash_wallet = request.form.get('cash_wallet')
            report.one_cash = request.form.get('one_cash')
            report.description = request.form.get('description')
            report.custom_fields = custom_fields_json
            
            # تحديث معلومات المديونية إذا كان نوع البلاغ مديونية
            if report_type == 'debt':
                if debt_amount:
                    report.debt_amount = float(debt_amount)
                else:
                    report.debt_amount = None
                
                if debt_date:
                    report.debt_date = datetime.strptime(debt_date, '%Y-%m-%d').date()
                else:
                    report.debt_date = None
            else:
                report.debt_amount = None
                report.debt_date = None
            
            # معالجة الملفات المرفقة
            if 'media_files' in request.files:
                files = request.files.getlist('media_files')
                new_file_paths = []
                
                for file in files:
                    if file and file.filename and allowed_file(file.filename):
                        filename = secure_filename(file.filename)
                        # إضافة طابع زمني لتجنب تكرار أسماء الملفات
                        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                        unique_filename = f"{timestamp}_{filename}"
                        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                        file.save(file_path)
                        new_file_paths.append(unique_filename)
                
                # إذا كان هناك ملفات جديدة، قم بإضافتها إلى الملفات الموجودة
                if new_file_paths:
                    if report.media_files:
                        existing_files = report.media_files.split('|')
                        all_files = existing_files + new_file_paths
                        report.media_files = '|'.join(all_files)
                    else:
                        report.media_files = '|'.join(new_file_paths)
            
            # تحديث وقت التعديل
            report.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            flash('تم تحديث البلاغ بنجاح', 'success')
            return redirect(url_for('view_report', report_id=report.id))
        except OperationalError as e:
            db.session.rollback()
            logger.error(f"Database operational error: {str(e)}")
            flash('حدث خطأ أثناء تحديث البلاغ. الرجاء المحاولة مرة أخرى.', 'danger')
            return render_template('edit_report.html', report=report)
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"SQLAlchemy error: {str(e)}")
            flash('حدث خطأ أثناء تحديث البلاغ. الرجاء المحاولة مرة أخرى.', 'danger')
            return render_template('edit_report.html', report=report)
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error: {str(e)}")
            flash('حدث خطأ أثناء تحديث البلاغ. الرجاء المحاولة مرة أخرى.', 'danger')
            return render_template('edit_report.html', report=report)

    # تحميل البيانات الحالية للبلاغ
    custom_fields = {}
    if report.custom_fields:
        try:
            custom_fields = json.loads(report.custom_fields)
        except:
            custom_fields = {}
    
    return render_template('edit_report.html', report=report, custom_fields=custom_fields)

@app.route('/report/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    report = Report.query.get_or_404(report_id)
    
    # التحقق من أن المستخدم هو صاحب البلاغ أو مدير
    if report.user_id != current_user.id and not current_user.is_admin:
        flash('ليس لديك صلاحية حذف هذا البلاغ', 'danger')
        return redirect(url_for('index'))

    # حذف الملفات المرفقة
    if report.media_files:
        files = report.media_files.split('|')
        for file in files:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
            try:
                os.remove(file_path)
            except OSError:
                pass

    db.session.delete(report)
    db.session.commit()
    flash('تم حذف البلاغ بنجاح', 'success')
    return redirect(url_for('index'))

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user, remember=True)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('خطأ في اسم المستخدم أو كلمة المرور', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    try:
        logout_user()
        flash('تم تسجيل الخروج بنجاح', 'success')
    except Exception as e:
        logger.error(f"Error during logout: {str(e)}")
        # حتى لو فشل تسجيل الخروج، نعيد توجيه المستخدم إلى صفحة تسجيل الدخول
        flash('حدث خطأ أثناء تسجيل الخروج، يرجى تسجيل الدخول مرة أخرى', 'warning')
    
    # تنظيف الجلسة بغض النظر عن نجاح أو فشل تسجيل الخروج
    return redirect(url_for('login'))

@app.route('/register')
def register():
    flash('تم إيقاف تسجيل الحسابات الجديدة. يرجى التواصل معنا واتساب  لإنشاء حساب جديد.', 'info')
    return redirect(url_for('login'))

@app.route('/view_report/<int:report_id>')
@login_required
def view_report(report_id):
    report = db.session.get(Report, report_id)
    
    # معالجة ملفات الوسائط
    media_files = []
    if report.media_files:
        media_files = report.media_files.split('|')
    
    # قائمة بجميع الأرقام والأسماء للتحقق من التكرارات
    duplicates = {}
    
    # معالجة أرقام الهواتف
    all_reports = Report.query.all()
    for r in all_reports:
        if r.scammer_phone:
            phones = r.scammer_phone.split('|')
            for phone in phones:
                phone = phone.strip()
                if phone and phone.lower() != "nan":
                    duplicates[phone] = duplicates.get(phone, 0) + 1
    
    # معالجة الأسماء
    for r in all_reports:
        if r.scammer_name:
            names = r.scammer_name.split('|')
            for name in names:
                name = name.strip()
                if name and name.lower() != "nan":
                    duplicates[name] = duplicates.get(name, 0) + 1
    
    # معالجة عناوين المحافظ
    for r in all_reports:
        if r.wallet_address:
            addresses = r.wallet_address.split('|')
            for addr in addresses:
                addr = addr.strip()
                if addr and addr.lower() != "nan":
                    duplicates[addr] = duplicates.get(addr, 0) + 1
    
    # معالجة طرق الدفع
    payment_fields = ['paypal', 'payer', 'perfect_money', 'alkremi_bank', 
                     'jeeb_wallet', 'jawali_wallet', 'cash_wallet', 'one_cash']
    
    for r in all_reports:
        for field in payment_fields:
            value = getattr(r, field)
            if value and value.strip() and value.lower() != "nan":
                duplicates[value] = duplicates.get(value, 0) + 1
    
    # معالجة الحقول المخصصة
    custom_fields = {}
    if report.custom_fields and report.custom_fields.strip():
        # محاولة معالجة البيانات كـ JSON
        if report.custom_fields.strip().startswith('{') and report.custom_fields.strip().endswith('}'):
            try:
                custom_data = json.loads(report.custom_fields)
                # تصفية قيم "nan" من الحقول المخصصة
                for key, value in custom_data.items():
                    if isinstance(value, str):
                        if value.lower() != "nan" and value.strip():
                            custom_fields[key] = value
                            # إضافة قيمة الحقل المخصص إلى التكرارات
                            duplicates[value] = duplicates.get(value, 0) + 1
                        elif value.strip():
                            custom_fields[key] = "لا يوجد"
                    elif value is not None:
                        str_value = str(value)
                        custom_fields[key] = str_value
                        duplicates[str_value] = duplicates.get(str_value, 0) + 1
            except json.JSONDecodeError:
                pass
        
        # إذا لم تكن بيانات JSON أو فشل التحليل، نحاول التعامل معها كنص عادي
        if not custom_fields and ':' in report.custom_fields:
            lines = report.custom_fields.split('\n')
            for line in lines:
                if ':' in line:
                    parts = line.split(':', 1)
                    key = parts[0].strip()
                    value = parts[1].strip()
                    if value and value.lower() != "nan":
                        custom_fields[key] = value
                        duplicates[value] = duplicates.get(value, 0) + 1
                    elif value.strip():
                        custom_fields[key] = "لا يوجد"
                elif line.strip() and line.strip().lower() != "nan":
                    # إذا لم يكن هناك ":" في السطر، نستخدم السطر كمفتاح وقيمة
                    field_key = f"حقل {len(custom_fields) + 1}"
                    custom_fields[field_key] = line.strip()
                    duplicates[line.strip()] = duplicates.get(line.strip(), 0) + 1
    
    return render_template('view_report.html', report=report, media_files=media_files, duplicates=duplicates, custom_fields=custom_fields)

@app.route('/get_all_contacts', methods=['GET'])
@login_required
@db_retry
def get_all_contacts():
    try:
        contacts = []
        reports = Report.query.all()
        
        for report in reports:
            if report.scammer_phone and report.scammer_name:
                # تنظيف البيانات
                phone = report.scammer_phone.strip()
                name = report.scammer_name.strip()
                
                # تجاهل السجلات التي تحتوي على قيم فارغة أو nan
                if phone and name and phone.lower() != 'nan' and name.lower() != 'nan':
                    contacts.append({
                        'phone': phone,
                        'name': name
                    })
        
        return jsonify(contacts)
    except Exception as e:
        logger.error(f"Error in get_all_contacts: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Admin Routes
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    # إحصائيات النظام
    total_reports = Report.query.count()
    scammer_reports = Report.query.filter_by(type='scammer').count()
    debt_reports = Report.query.filter_by(type='debt').count()
    total_users = User.query.count()
    
    return render_template('admin/dashboard.html', 
                         total_reports=total_reports,
                         scammer_reports=scammer_reports,
                         debt_reports=debt_reports,
                         total_users=total_users)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    users = User.query.all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/add', methods=['GET', 'POST'])
@login_required
def admin_add_user():
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        is_admin = 'is_admin' in request.form
        
        # التحقق من عدم وجود مستخدم بنفس اسم المستخدم أو البريد الإلكتروني
        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()
        
        if existing_user:
            flash('اسم المستخدم أو البريد الإلكتروني مستخدم بالفعل', 'danger')
            return redirect(url_for('admin_add_user'))
        
        # إنشاء مستخدم جديد
        new_user = User(username=username, email=email, is_admin=is_admin)
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash(f'تم إنشاء المستخدم {username} بنجاح', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin/add_user.html')

@app.route('/admin/users/<int:id>/toggle_admin', methods=['POST'])
@login_required
def toggle_admin(id):
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    user = db.session.get(User, id)
    if not user:
        flash('المستخدم غير موجود', 'danger')
        return redirect(url_for('admin_users'))
    
    # لا يمكن إلغاء صلاحيات المشرف الحالي
    if user.id == current_user.id:
        flash('لا يمكنك إلغاء صلاحيات المشرف الخاصة بك', 'warning')
        return redirect(url_for('admin_users'))
    
    user.is_admin = not user.is_admin
    db.session.commit()
    
    status = 'منح' if user.is_admin else 'إلغاء'
    flash(f'تم {status} صلاحيات المشرف للمستخدم {user.username} بنجاح', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:id>/delete', methods=['POST'])
@login_required
def delete_user(id):
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    user = db.session.get(User, id)
    if not user:
        flash('المستخدم غير موجود', 'danger')
        return redirect(url_for('admin_users'))
    
    # لا يمكن حذف المشرف الحالي
    if user.id == current_user.id:
        flash('لا يمكنك حذف حسابك الخاص', 'warning')
        return redirect(url_for('admin_users'))
    
    # حذف جميع البلاغات المرتبطة بالمستخدم
    reports = Report.query.filter_by(user_id=user.id).all()
    for report in reports:
        # حذف الملفات المرفقة
        if report.media_files:
            for filename in report.media_files.split(','):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try:
                    os.remove(file_path)
                except OSError:
                    pass
        db.session.delete(report)
    
    # حذف المستخدم
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    flash(f'تم حذف المستخدم {username} وجميع البلاغات المرتبطة به بنجاح', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/reports')
@login_required
def admin_reports():
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    # فلترة البلاغات
    report_type = request.args.get('type', 'all')
    if report_type == 'scammer':
        reports = Report.query.filter_by(type='scammer').order_by(Report.created_at.desc()).all()
    elif report_type == 'debt':
        reports = Report.query.filter_by(type='debt').order_by(Report.created_at.desc()).all()
    else:
        reports = Report.query.order_by(Report.created_at.desc()).all()
    
    # إعداد قائمة البلاغات مع معلومات المستخدمين
    report_data = []
    for report in reports:
        user = db.session.get(User, report.user_id)
        report_data.append({
            'report': report,
            'username': user.username if user else 'غير معروف'
        })
    
    return render_template('admin/reports.html', reports=report_data, report_type=report_type)

@app.route('/admin/report/<int:report_id>/delete', methods=['POST'])
@login_required
def admin_delete_report(report_id):
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى هذه الصفحة', 'danger')
        return redirect(url_for('index'))
    
    report = Report.query.get_or_404(report_id)
    
    # حذف الملفات المرفقة
    if report.media_files:
        files = report.media_files.split('|')
        for file in files:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
            try:
                os.remove(file_path)
            except OSError:
                pass
    
    db.session.delete(report)
    db.session.commit()
    
    flash('تم حذف البلاغ بنجاح', 'success')
    return redirect(url_for('admin_reports'))

@app.route('/admin/reports/export', methods=['GET'])
@login_required
def export_reports_excel():
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    try:
        # تأجيل استيراد pandas حتى نحتاجه فعلياً
        import pandas as pd
        
        # فلترة البلاغات مع تحديد عدد السجلات
        report_type = request.args.get('type', 'all')
        if report_type == 'scammer':
            reports = Report.query.filter_by(type='scammer').order_by(Report.created_at.desc()).limit(500).all()
            filename = "scammer_reports.xlsx"
        elif report_type == 'debt':
            reports = Report.query.filter_by(type='debt').order_by(Report.created_at.desc()).limit(500).all()
            filename = "debt_reports.xlsx"
        else:
            reports = Report.query.order_by(Report.created_at.desc()).limit(500).all()
            filename = "all_reports.xlsx"
        
        # إنشاء ملف إكسل في الذاكرة
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet('البلاغات')
        
        # تنسيق العناوين
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#0d6efd',
            'color': 'white',
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        # تنسيق الخلايا
        cell_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'text_wrap': True
        })
        
        # تنسيق للنصابين
        scammer_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#ffcccc',
            'text_wrap': True
        })
        
        # تنسيق للمديونية
        debt_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#ffffcc',
            'text_wrap': True
        })
        
        # إعداد العناوين
        headers = [
            'رقم البلاغ', 'النوع', 'اسم النصاب', 'رقم الهاتف', 'المحفظة', 'الشبكة',
            'PayPal', 'Payer', 'Perfect Money', 'بنك الكريمي', 'محفظة جيب',
            'محفظة جوالي', 'محفظة كاش', 'ون كاش', 'قيمة المديونية', 'تاريخ المديونية',
            'الوصف', 'المستخدم', 'تاريخ الإنشاء', 'الحقول المخصصة'
        ]
        
        # كتابة العناوين
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, header_format)
        
        # ضبط عرض الأعمدة
        worksheet.set_column(0, 0, 10)  # رقم البلاغ
        worksheet.set_column(1, 1, 15)  # النوع
        worksheet.set_column(2, 2, 25)  # اسم النصاب
        worksheet.set_column(3, 3, 20)  # رقم الهاتف
        worksheet.set_column(4, 14, 20)  # المحافظ والحسابات
        worksheet.set_column(15, 15, 15)  # تاريخ المديونية
        worksheet.set_column(16, 16, 40)  # الوصف
        worksheet.set_column(17, 17, 15)  # المستخدم
        worksheet.set_column(18, 18, 20)  # تاريخ الإنشاء
        worksheet.set_column(19, 19, 40)  # الحقول المخصصة
        
        # كتابة البيانات
        for row, report in enumerate(reports, start=1):
            # تحديد التنسيق بناءً على نوع البلاغ
            format_to_use = scammer_format if report.type == 'scammer' else debt_format
            
            # تحضير البيانات
            user = User.query.get(report.user_id)
            username = user.username if user else "غير معروف"
            
            # تقسيم البيانات المتعددة
            scammer_names = report.scammer_name.split('|') if report.scammer_name else []
            scammer_name = scammer_names[0] if scammer_names else ""
            
            scammer_phones = report.scammer_phone.split('|') if report.scammer_phone else []
            scammer_phone = scammer_phones[0] if scammer_phones else ""
            
            wallet_addresses = report.wallet_address.split('|') if report.wallet_address else []
            wallet_address = wallet_addresses[0] if wallet_addresses else ""
            
            network_types = report.network_type.split('|') if report.network_type else []
            network_type = network_types[0] if network_types else ""
            
            # تنسيق التواريخ
            created_at = report.created_at.strftime('%Y-%m-%d %H:%M') if report.created_at else ""
            debt_date = report.debt_date.strftime('%Y-%m-%d') if report.debt_date else ""
            
            # كتابة البيانات في الصفوف
            data = [
                report.id,
                'نصاب' if report.type == 'scammer' else 'مديونية',
                scammer_name,
                scammer_phone,
                wallet_address,
                network_type,
                report.paypal or "",
                report.payer or "",
                report.perfect_money or "",
                report.alkremi_bank or "",
                report.jeeb_wallet or "",
                report.jawali_wallet or "",
                report.cash_wallet or "",
                report.one_cash or "",
                report.debt_amount or "",
                debt_date,
                report.description or "",
                username,
                created_at,
                report.custom_fields or ""
            ]
            
            for col, value in enumerate(data):
                worksheet.write(row, col, value, format_to_use)
        
        workbook.close()
        
        # إعادة مؤشر الملف إلى البداية
        output.seek(0)
        
        # إرسال الملف للتنزيل
        return send_file(
            output,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except OperationalError as e:
        logger.error(f"Database operational error: {str(e)}")
        flash('حدث خطأ أثناء تصدير البلاغات. الرجاء المحاولة مرة أخرى.', 'danger')
        return redirect(url_for('admin_reports'))
    except SQLAlchemyError as e:
        logger.error(f"SQLAlchemy error: {str(e)}")
        flash('حدث خطأ أثناء تصدير البلاغات. الرجاء المحاولة مرة أخرى.', 'danger')
        return redirect(url_for('admin_reports'))
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        flash('حدث خطأ أثناء تصدير البلاغات. الرجاء المحاولة مرة أخرى.', 'danger')
        return redirect(url_for('admin_reports'))

@app.route('/admin/reports/import', methods=['GET', 'POST'])
@login_required
def import_reports_excel():
    if not current_user.is_admin:
        flash('غير مصرح لك بالوصول إلى لوحة التحكم', 'danger')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # التحقق من وجود ملف
        if 'excel_file' not in request.files:
            flash('لم يتم تحديد ملف', 'danger')
            return redirect(request.url)
        
        file = request.files['excel_file']
        
        # التحقق من اسم الملف
        if file.filename == '':
            flash('لم يتم تحديد ملف', 'danger')
            return redirect(request.url)
        
        # التحقق من امتداد الملف
        if not file.filename.endswith(('.xlsx', '.xls')):
            flash('يجب أن يكون الملف بصيغة Excel (.xlsx أو .xls)', 'danger')
            return redirect(request.url)
        
        try:
            # قراءة ملف الإكسل
            import pandas as pd  # تأجيل استيراد pandas حتى نحتاجه فعلياً
            df = pd.read_excel(file, nrows=1000)  # قراءة أول 1000 صف فقط لتقليل استهلاك الذاكرة
            
            # التحقق من وجود الأعمدة المطلوبة
            required_columns = ['النوع', 'اسم النصاب', 'رقم الهاتف', 'الوصف']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                flash(f'الأعمدة التالية مفقودة في الملف: {", ".join(missing_columns)}', 'danger')
                return redirect(request.url)
            
            # عدد البلاغات التي تمت إضافتها
            reports_added = 0
            
            # إضافة البلاغات من الملف
            for _, row in df.iterrows():
                # تحديد نوع البلاغ
                report_type = 'scammer' if row['النوع'] == 'نصاب' else 'debt'
                
                # إنشاء بلاغ جديد
                new_report = Report(
                    user_id=current_user.id,
                    type=report_type,
                    scammer_name=str(row.get('اسم النصاب', '')),
                    scammer_phone=str(row.get('رقم الهاتف', '')),
                    description=str(row.get('الوصف', '')),
                    wallet_address=str(row.get('المحفظة', '')),
                    network_type=str(row.get('الشبكة', '')),
                    paypal=str(row.get('PayPal', '')),
                    payer=str(row.get('Payer', '')),
                    perfect_money=str(row.get('Perfect Money', '')),
                    alkremi_bank=str(row.get('بنك الكريمي', '')),
                    jeeb_wallet=str(row.get('محفظة جيب', '')),
                    jawali_wallet=str(row.get('محفظة جوالي', '')),
                    cash_wallet=str(row.get('محفظة كاش', '')),
                    one_cash=str(row.get('ون كاش', '')),
                    custom_fields=str(row.get('الحقول المخصصة', ''))
                )
                
                # إضافة قيمة المديونية وتاريخها إذا كان نوع البلاغ مديونية
                if report_type == 'debt':
                    debt_amount = row.get('قيمة المديونية')
                    if pd.notna(debt_amount):
                        new_report.debt_amount = float(debt_amount)
                    
                    debt_date = row.get('تاريخ المديونية')
                    if pd.notna(debt_date):
                        # تحويل التاريخ إلى كائن datetime
                        if isinstance(debt_date, str):
                            try:
                                new_report.debt_date = datetime.strptime(debt_date, '%Y-%m-%d').date()
                            except ValueError:
                                pass
                        else:
                            new_report.debt_date = debt_date
                
                # حفظ البلاغ في قاعدة البيانات
                db.session.add(new_report)
                reports_added += 1
            
            # حفظ التغييرات في قاعدة البيانات
            db.session.commit()
            
            flash(f'تم استيراد {reports_added} بلاغ بنجاح', 'success')
            return redirect(url_for('admin_reports'))
            
        except OperationalError as e:
            db.session.rollback()
            logger.error(f"Database operational error: {str(e)}")
            flash('حدث خطأ أثناء استيراد الملف. الرجاء المحاولة مرة أخرى.', 'danger')
            return redirect(request.url)
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"SQLAlchemy error: {str(e)}")
            flash('حدث خطأ أثناء استيراد الملف. الرجاء المحاولة مرة أخرى.', 'danger')
            return redirect(request.url)
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            flash('حدث خطأ أثناء استيراد الملف. الرجاء المحاولة مرة أخرى.', 'danger')
            return redirect(request.url)
    
    return render_template('admin/import_reports.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
