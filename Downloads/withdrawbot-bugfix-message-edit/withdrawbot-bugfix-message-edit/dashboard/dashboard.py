import os
import sys
from flask import Flask, render_template, jsonify, request, send_file
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
from io import BytesIO
from utils.database import Database

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# إضافة المسار الرئيسي إلى Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# التأكد من وجود رابط قاعدة البيانات
database_url = os.getenv("DATABASE_URL")
if not database_url:
    raise ValueError("DATABASE_URL غير موجود في ملف .env")

# إنشاء تطبيق Flask
app = Flask(__name__)
db = Database(database_url)

@app.route('/')
def dashboard():
    """عرض لوحة التحكم الرئيسية"""
    try:
        stats = db.get_statistics()
        codes = db.get_all_codes()
        return render_template('index.html', stats=stats, codes=codes)
    except Exception as e:
        app.logger.error(f"خطأ في عرض لوحة التحكم: {e}")
        return render_template('index.html', stats={}, codes=[], error="حدث خطأ في الاتصال بقاعدة البيانات")

@app.route('/transfers')
def transfers_page():
    """صفحة عرض التحويلات"""
    page = request.args.get('page', 1, type=int)
    status = request.args.get('status')
    transfers_data = db.get_transfers(page=page, status=status)
    return render_template('transfers.html', transfers=transfers_data)

@app.route('/api/transfers')
def get_transfers():
    """الحصول على قائمة التحويلات عبر API"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    status = request.args.get('status')
    transfers = db.get_transfers(page=page, per_page=per_page, status=status)
    return jsonify(transfers)

@app.route('/api/transfers/<transfer_id>')
def get_transfer_details(transfer_id):
    """الحصول على تفاصيل تحويل معين عبر API"""
    transfer = db.get_transfer_details(transfer_id)
    if transfer:
        return jsonify(transfer)
    return jsonify({'error': 'Transfer not found'}), 404

@app.route('/api/statistics')
def get_statistics():
    """الحصول على الإحصائيات عبر API"""
    stats = db.get_statistics()
    return jsonify(stats)

@app.route('/api/codes', methods=['GET'])
def get_codes():
    """عرض جميع الأكواد عبر API"""
    codes = db.get_all_codes()
    return jsonify(codes)

@app.route('/api/codes', methods=['POST'])
def add_code():
    """إضافة كود جديد عبر API"""
    try:
        data = request.json
        if not data or 'code' not in data:
            return jsonify({'success': False, 'error': 'Code is required'}), 400
        
        # التحقق من صحة البيانات
        code = data['code'].strip()
        if not code:
            return jsonify({'success': False, 'error': 'Code cannot be empty'}), 400
            
        # التحقق من صحة max_uses
        max_uses = data.get('max_uses', -1)
        try:
            max_uses = int(max_uses)
            if max_uses != -1 and max_uses < 1:
                return jsonify({'success': False, 'error': 'Max uses must be -1 or greater than 0'}), 400
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid max uses value'}), 400
        
        # التحقق من صحة الحالة
        status = data.get('status', 'active')
        if status not in ['active', 'inactive']:
            return jsonify({'success': False, 'error': 'Invalid status'}), 400
        
        code_data = {
            'code': code,
            'description': data.get('description', '').strip(),
            'status': status,
            'max_uses': max_uses,
            'expiry_date': data.get('expiry_date')
        }
        
        success = db.add_registration_code(**code_data)
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Code already exists'}), 400
            
    except Exception as e:
        app.logger.error(f"خطأ في إضافة الكود: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/codes/<code>', methods=['PUT'])
def update_code(code):
    """تحديث كود معين عبر API"""
    data = request.json
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    
    # التحقق من صحة البيانات
    if 'status' in data and data['status'] not in ['active', 'inactive']:
        return jsonify({'success': False, 'error': 'Invalid status value'}), 400
        
    if 'max_uses' in data and (not isinstance(data['max_uses'], int) or data['max_uses'] < -1):
        return jsonify({'success': False, 'error': 'Invalid max_uses value'}), 400
    
    # تحديث الكود
    update_data = {
        'code': data.get('code', code),
        'description': data.get('description'),
        'status': data.get('status'),
        'max_uses': data.get('max_uses'),
        'expiry_date': data.get('expiry_date')
    }
    
    # حذف القيم الفارغة
    update_data = {k: v for k, v in update_data.items() if v is not None}
    
    success = db.update_registration_code(code, update_data)
    return jsonify({'success': success})

@app.route('/api/codes/<code>', methods=['GET'])
def get_code_details(code):
    """الحصول على تفاصيل كود معين عبر API"""
    code_details = db.get_code_details(code)
    if code_details:
        return jsonify(code_details)
    return jsonify({'error': 'Code not found'}), 404

@app.route('/api/codes/<code>', methods=['DELETE'])
def delete_code(code):
    """حذف كود معين عبر API"""
    success = db.delete_registration_code(code)
    return jsonify({'success': success})

@app.route('/api/settings', methods=['GET', 'POST'])
def handle_settings():
    """إعدادات البوت عبر API"""
    if request.method == 'POST':
        data = request.json
        # تحديث الإعدادات في قاعدة البيانات
        settings = {
            'fixed_fee_threshold': float(data.get('fixed_fee_threshold', 20)),
            'fixed_fee_amount': float(data.get('fixed_fee_amount', 1)),
            'percentage_fee': float(data.get('percentage_fee', 5)) / 100,  # تحويل النسبة المئوية إلى عدد عشري
            'min_withdrawal': float(data.get('min_withdrawal', 10)),
            'max_withdrawal': float(data.get('max_withdrawal', 1000))
        }
        success = db.update_settings(settings)
        return jsonify({'success': success})
    else:
        # استرجاع الإعدادات من قاعدة البيانات
        settings = db.get_settings()
        if not settings:
            # القيم الافتراضية إذا لم تكن هناك إعدادات مخزنة
            settings = {
                'fixed_fee_threshold': 20,
                'fixed_fee_amount': 1,
                'percentage_fee': 5,  # تحويل من عدد عشري إلى نسبة مئوية
                'min_withdrawal': 10,
                'max_withdrawal': 1000
            }
        else:
            settings['percentage_fee'] = settings['percentage_fee'] * 100  # تحويل من عدد عشري إلى نسبة مئوية
        return jsonify(settings)

@app.route('/api/exchange-rates', methods=['GET'])
def get_exchange_rates():
    """الحصول على جميع أسعار الصرف عبر API"""
    rates = db.get_exchange_rates()
    return jsonify(rates)

@app.route('/api/exchange-rates/<currency>', methods=['PUT'])
def update_exchange_rate(currency):
    """تحديث سعر الصرف لعملة معينة عبر API"""
    data = request.json
    if not data or 'rate' not in data:
        return jsonify({'error': 'Rate is required'}), 400
    try:
        rate = float(data['rate'])
        success = db.update_exchange_rate(currency, rate)
        return jsonify({'success': success})
    except ValueError:
        return jsonify({'error': 'Invalid rate value'}), 400

@app.route('/api/exchange-rates/<currency>', methods=['DELETE'])
def delete_exchange_rate(currency):
    """حذف سعر الصرف لعملة معينة عبر API"""
    success = db.delete_exchange_rate(currency)
    return jsonify({'success': success})

@app.route('/export-codes')
def export_codes():
    """تصدير الأكواد إلى ملف إكسل"""
    try:
        # الحصول على الأكواد من قاعدة البيانات
        codes = db.export_codes_to_excel()
        if not codes:
            app.logger.warning("لم يتم العثور على أي أكواد للتصدير")
            return jsonify({'error': 'لا توجد أكواد للتصدير'}), 404
            
        app.logger.info(f"تم استخراج {len(codes)} كود من قاعدة البيانات")
        
        # تحويل التواريخ إلى نص وتنظيف البيانات
        clean_codes = []
        for code in codes:
            clean_code = {
                'code': code.get('code', ''),
                'description': code.get('description', ''),
                'status': 'نشط' if code.get('status') == 'active' else 'متوقف',
                'used_count': code.get('used_count', 0),
                'max_uses': code.get('max_uses', -1),
                'created_at': code['created_at'].strftime('%Y-%m-%d %H:%M:%S') if code.get('created_at') else '',
                'expiry_date': code['expiry_date'].strftime('%Y-%m-%d %H:%M:%S') if code.get('expiry_date') else '',
                'created_by': code.get('created_by', '')
            }
            clean_codes.append(clean_code)
        
        # إنشاء DataFrame مع العناوين العربية
        df = pd.DataFrame(clean_codes)
        df = df.rename(columns={
            'code': 'الكود',
            'description': 'الوصف',
            'status': 'الحالة',
            'used_count': 'عدد الاستخدامات',
            'max_uses': 'الحد الأقصى للاستخدام',
            'created_at': 'تاريخ الإنشاء',
            'expiry_date': 'تاريخ انتهاء الصلاحية',
            'created_by': 'المنشئ'
        })
        
        # إنشاء ملف إكسل في الذاكرة
        excel_file = BytesIO()
        
        # إنشاء ملف إكسل مع تنسيق
        with pd.ExcelWriter(excel_file, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='الأكواد', index=False)
            
            # الحصول على ورقة العمل وتنسيقها
            worksheet = writer.sheets['الأكواد']
            workbook = writer.book
            
            # تنسيق العناوين
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'align': 'center',
                'bg_color': '#D9EAD3',
                'border': 1
            })
            
            # تطبيق التنسيق على العناوين
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
                # تعيين عرض العمود بناءً على محتواه
                max_length = max(
                    df[value].astype(str).apply(len).max(),
                    len(str(value))
                )
                worksheet.set_column(col_num, col_num, max_length + 2)
        
        # إعادة المؤشر إلى بداية الملف
        excel_file.seek(0)
        
        # إرسال الملف
        return send_file(
            excel_file,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'registration_codes_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )
        
    except Exception as e:
        app.logger.error(f"خطأ في تصدير الأكواد: {e}")
        return jsonify({'error': 'حدث خطأ أثناء تصدير الأكواد'}), 500

@app.route('/import-codes', methods=['POST'])
def import_codes():
    """استيراد الأكواد من ملف إكسل"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'لم يتم تحديد ملف'}), 400
            
        file = request.files['file']
        if not file.filename.endswith('.xlsx'):
            return jsonify({'error': 'يجب أن يكون الملف بصيغة Excel (.xlsx)'}), 400
            
        # قراءة الملف
        df = pd.read_excel(file)
        codes_data = df.to_dict('records')
        
        # استيراد الأكواد
        success_count, failed_count, errors = db.import_codes_from_excel(codes_data)
        
        return jsonify({
            'success': True,
            'message': f'تم استيراد {success_count} كود بنجاح، فشل استيراد {failed_count} كود',
            'errors': errors
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/add-test-codes')
def add_test_codes():
    """إضافة أكواد اختبار للتجربة"""
    try:
        success = db.add_test_codes()
        if success:
            return jsonify({'success': True, 'message': 'تم إضافة أكواد الاختبار بنجاح'})
        else:
            return jsonify({'success': False, 'error': 'فشل في إضافة أكواد الاختبار'}), 500
    except Exception as e:
        app.logger.error(f"خطأ في إضافة أكواد الاختبار: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("Please run the application using run.py")
