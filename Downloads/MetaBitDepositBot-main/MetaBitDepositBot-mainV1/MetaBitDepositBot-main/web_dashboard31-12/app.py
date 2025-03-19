from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import psycopg2
from psycopg2.extras import DictCursor
import pandas as pd
import plotly
import plotly.express as px
import plotly.graph_objects as go
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.urandom(24)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@app.template_filter('format_currency')
def format_currency(value):
    """تنسيق القيم النقدية"""
    try:
        return f"{float(value):,.2f} USD"
    except (ValueError, TypeError):
        return "0.00 USD"

def get_db_connection():
    """إنشاء اتصال بقاعدة البيانات"""
    try:
        # تكوين سلسلة الاتصال
        DATABASE_URL = "postgres://alhubaishi:jAtNbIdExraRUo1ZosQ1f0EEGz3fMZWt@dpg-csserj9u0jms73ea9gmg-a.singapore-postgres.render.com/meta_bit_database"
        
        # إنشاء الاتصال
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        
        # تمكين الالتزام التلقائي
        conn.autocommit = True
        
        # اختبار الاتصال وطباعة معلومات عن الجداول
        with conn.cursor() as cur:
            # التحقق من وجود الجداول
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            tables = cur.fetchall()
            print("📊 الجداول الموجودة:", [table[0] for table in tables])
            
            # التحقق من عدد السجلات في جدول withdrawal_requests
            cur.execute("SELECT COUNT(*) FROM withdrawal_requests")
            wr_count = cur.fetchone()[0]
            print(f"📝 عدد السجلات في withdrawal_requests: {wr_count}")
            
            # التحقق من عدد السجلات في جدول registration_codes
            cur.execute("SELECT COUNT(*) FROM registration_codes")
            rc_count = cur.fetchone()[0]
            print(f"🔑 عدد السجلات في registration_codes: {rc_count}")
            
        print("✅ تم الاتصال بقاعدة البيانات بنجاح")
        return conn
        
    except Exception as e:
        print(f"❌ خطأ في الاتصال بقاعدة البيانات: {str(e)}")
        return None

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Admin credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "Meta123++"

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

@app.route('/')
@login_required
def index():
    try:
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بقاعدة البيانات', 'error')
            return render_template('index.html', stats={}, withdrawals=[], amounts={}, exchange_rates=[])

        cur = conn.cursor(cursor_factory=DictCursor)
        
        # جلب الإحصائيات
        cur.execute("""
            SELECT 
                COUNT(*) as total_withdrawals,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_withdrawals,
                COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_withdrawals,
                COUNT(CASE WHEN status = 'failed' OR status = 'rejected' THEN 1 END) as failed_withdrawals
            FROM withdrawal_requests
        """)
        stats = dict(cur.fetchone())
        
        # جلب المبالغ الإجمالية
        cur.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END), 0) as total_completed_usd,
                COALESCE(SUM(CASE WHEN status = 'pending' THEN crypto_amount ELSE 0 END), 0) as total_pending_usd
            FROM withdrawal_requests
        """)
        amounts = dict(cur.fetchone())
        
        # جلب أسعار الصرف
        cur.execute("""
            SELECT 
                er.currency_code,
                er.rate,
                er.updated_at
            FROM exchange_rates er
            ORDER BY er.currency_code
        """)
        exchange_rates = [dict(row) for row in cur.fetchall()]
        
        # جلب آخر العمليات
        cur.execute("""
            SELECT 
                withdrawal_id,
                user_id,
                crypto_currency,
                local_currency,
                local_amount,
                crypto_amount,
                status,
                created_at
            FROM withdrawal_requests 
            ORDER BY created_at DESC 
            LIMIT 10
        """)
        withdrawals = [dict(row) for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        return render_template('index.html',
                             stats=stats,
                             withdrawals=withdrawals,
                             amounts=amounts,
                             exchange_rates=exchange_rates)
                             
    except Exception as e:
        print(f"خطأ: {str(e)}")
        flash(f'حدث خطأ: {str(e)}', 'error')
        return render_template('index.html', 
                             stats={}, 
                             withdrawals=[], 
                             amounts={}, 
                             exchange_rates=[])
@app.route('/exchange-rates', methods=['GET'])
@login_required
def exchange_rates():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        
        # جلب كل أسعار الصرف
        cur.execute("""
            SELECT currency_code, rate, updated_at
            FROM exchange_rates
            ORDER BY currency_code
        """)
        rates = [dict(row) for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        return render_template('exchange_rates.html', rates=rates)
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'error')
        return render_template('exchange_rates.html', rates=[])

@app.route('/exchange-rates/add', methods=['POST'])
@login_required
def add_exchange_rate():
    try:
        currency = request.form.get('currency').strip().upper()
        rate = float(request.form.get('rate'))
        
        if not currency or rate <= 0:
            flash('يرجى إدخال عملة وسعر صحيح', 'error')
            return redirect(url_for('exchange_rates'))
            
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO exchange_rates (currency_code, rate)
            VALUES (%s, %s)
            ON CONFLICT (currency_code) 
            DO UPDATE SET rate = EXCLUDED.rate, updated_at = CURRENT_TIMESTAMP
        """, (currency, rate))
        
        conn.commit()
        cur.close()
        conn.close()
        
        flash(f'تم تحديث سعر صرف {currency} بنجاح', 'success')
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'error')
    
    return redirect(url_for('exchange_rates'))

@app.route('/exchange-rates/delete/<currency>', methods=['POST'])
@login_required
def delete_exchange_rate(currency):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # التحقق من استخدام العملة في أي عمليات
        cur.execute("""
            SELECT COUNT(*) FROM withdrawal_requests 
            WHERE local_currency = %s
        """, (currency,))
        count = cur.fetchone()[0]
        
        if count > 0:
            flash(f'لا يمكن حذف العملة {currency} لأنها مستخدمة في {count} عمليات', 'error')
        else:
            cur.execute("""
                DELETE FROM exchange_rates 
                WHERE currency_code = %s
            """, (currency,))
            conn.commit()
            flash(f'تم حذف العملة {currency} بنجاح', 'success')
        
        cur.close()
        conn.close()
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'error')
    
    return redirect(url_for('exchange_rates'))
@app.route('/withdrawals')
@login_required
def withdrawals():
    try:
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بقاعدة البيانات', 'error')
            return render_template('withdrawals.html', withdrawals=[])

        cur = conn.cursor(cursor_factory=DictCursor)
        
        # استعلام محسن يجمع كل المعلومات المطلوبة
        cur.execute("""
            SELECT 
                wr.withdrawal_id,
                wr.user_id,
                rc.code as registration_code,
                wr.local_amount,
                wr.local_currency,
                wr.local_currency_name,
                wr.crypto_amount,
                wr.crypto_currency,
                wr.network_code,
                wr.network_name,
                wr.wallet_address,
                wr.transfer_number,
                wr.transfer_issuer,
                wr.status,
                wr.created_at
            FROM withdrawal_requests wr
            LEFT JOIN registration_codes rc ON wr.user_id = rc.user_id
            WHERE rc.is_used = true
            ORDER BY wr.created_at DESC
        """)
        
        withdrawals_list = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        return render_template('withdrawals.html', withdrawals=withdrawals_list)
        
    except Exception as e:
        print(f"خطأ: {str(e)}")
        flash(f'حدث خطأ: {str(e)}', 'error')
        return render_template('withdrawals.html', withdrawals=[])
@app.route('/codes')
@login_required
def codes():
    try:
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بقاعدة البيانات', 'error')
            return render_template('codes.html', codes=[])

        cur = conn.cursor(cursor_factory=DictCursor)
        
        # تعديل الاستعلام لاستخدام المعلومات المتوفرة فقط
        cur.execute("""
            SELECT 
                rc.code,
                rc.user_id,
                rc.is_used,
                COUNT(wr.withdrawal_id) as transactions_count,
                COALESCE(SUM(CASE WHEN wr.status = 'completed' THEN wr.crypto_amount ELSE 0 END), 0) as total_amount_usd
            FROM registration_codes rc
            LEFT JOIN withdrawal_requests wr ON rc.user_id = wr.user_id
            GROUP BY rc.code, rc.user_id, rc.is_used
            ORDER BY rc.code
        """)
        
        codes_list = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        
        return render_template('codes.html', codes=codes_list)
    except Exception as e:
        print(f"خطأ: {str(e)}")
        flash(f'حدث خطأ: {str(e)}', 'error')
        return render_template('codes.html', codes=[])
def get_trend_percentage(current, previous):
    """حساب نسبة التغير"""
    if previous == 0:
        return 0
    return round(((current - previous) / previous) * 100, 1)

@app.route('/analytics')
@login_required
def analytics():
    try:
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بقاعدة البيانات')
            return render_template('analytics.html')

        cur = conn.cursor(cursor_factory=DictCursor)
        
        # إحصائيات اليوم
        cur.execute("""
            WITH daily_stats AS (
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as count,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
                    SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END) as total_usd
                FROM withdrawal_requests
                WHERE created_at >= NOW() - INTERVAL '2 days'
                GROUP BY DATE(created_at)
            )
            SELECT 
                *,
                CASE WHEN count > 0 THEN (completed_count::float / count * 100) ELSE 0 END as success_rate,
                CASE WHEN count > 0 THEN (total_usd / count) ELSE 0 END as avg_amount
            FROM daily_stats
            ORDER BY date DESC
            LIMIT 2
        """)
        daily_stats = cur.fetchall()
        
        # حساب الإحصائيات والاتجاهات
        today_stats = daily_stats[0] if daily_stats else {'count': 0, 'total_usd': 0, 'success_rate': 0, 'avg_amount': 0}
        yesterday_stats = daily_stats[1] if len(daily_stats) > 1 else {'count': 0, 'total_usd': 0, 'success_rate': 0, 'avg_amount': 0}
        
        # حساب الاتجاهات
        amount_trend = get_trend_percentage(today_stats['total_usd'], yesterday_stats['total_usd'])
        transaction_trend = get_trend_percentage(today_stats['count'], yesterday_stats['count'])
        success_trend = get_trend_percentage(today_stats['success_rate'], yesterday_stats['success_rate'])
        avg_trend = get_trend_percentage(today_stats['avg_amount'], yesterday_stats['avg_amount'])
        
        # بيانات المخططات
        # المبالغ اليومية
        cur.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as count,
                SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END) as total_usd
            FROM withdrawal_requests
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        daily_data = pd.DataFrame(cur.fetchall(), columns=['date', 'count', 'total_usd'])
        
        # توزيع العملات
        cur.execute("""
            SELECT 
                crypto_currency,
                COUNT(*) as count,
                SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END) as total_amount
            FROM withdrawal_requests
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY crypto_currency
            ORDER BY total_amount DESC
        """)
        crypto_dist = pd.DataFrame(cur.fetchall(), columns=['crypto_currency', 'count', 'total_amount'])
        
        # توزيع الحالات
        cur.execute("""
            SELECT 
                status,
                COUNT(*) as count
            FROM withdrawal_requests
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY status
            ORDER BY count DESC
        """)
        status_dist = pd.DataFrame(cur.fetchall(), columns=['status', 'count'])
        
        cur.close()
        conn.close()

        # تحديد القيم الافتراضية للإحصائيات
        default_stats = {
            'total_amount': 0,
            'total_transactions': 0,
            'success_rate': 0,
            'avg_amount': 0,
            'amount_trend': 0,
            'transaction_trend': 0,
            'success_trend': 0,
            'avg_trend': 0,
            'plot_amount': "{}",
            'plot_count': "{}",
            'plot_crypto_dist': "{}",
            'plot_status_dist': "{}"
        }

        # إنشاء المخططات
        if not daily_data.empty:
            # مخطط المبالغ
            fig_amount = px.line(daily_data, x='date', y='total_usd',
                               title='المبالغ اليومية (بالدولار الأمريكي)',
                               labels={'date': 'التاريخ', 'total_usd': 'المبلغ (USD)'})
            fig_amount.update_traces(mode='lines+markers')
            
            # مخطط العمليات
            fig_count = px.bar(daily_data, x='date', y='count',
                             title='عدد العمليات اليومية',
                             labels={'date': 'التاريخ', 'count': 'عدد العمليات'})
            
            # مخطط توزيع العملات
            fig_crypto = px.pie(crypto_dist, values='total_amount', names='crypto_currency',
                              title='توزيع العملات المشفرة')
            
            # مخطط توزيع الحالات
            fig_status = px.pie(status_dist, values='count', names='status',
                              title='توزيع حالات العمليات')
            
            # تحويل المخططات إلى JSON
            plot_amount = json.dumps(fig_amount, cls=plotly.utils.PlotlyJSONEncoder)
            plot_count = json.dumps(fig_count, cls=plotly.utils.PlotlyJSONEncoder)
            plot_crypto_dist = json.dumps(fig_crypto, cls=plotly.utils.PlotlyJSONEncoder)
            plot_status_dist = json.dumps(fig_status, cls=plotly.utils.PlotlyJSONEncoder)
        else:
            plot_amount = plot_count = plot_crypto_dist = plot_status_dist = "{}"

        # تجميع الإحصائيات
        stats = {
            'total_amount': today_stats['total_usd'],
            'total_transactions': today_stats['count'],
            'success_rate': round(today_stats['success_rate'], 1),
            'avg_amount': today_stats['avg_amount'],
            'amount_trend': amount_trend,
            'transaction_trend': transaction_trend,
            'success_trend': success_trend,
            'avg_trend': avg_trend,
            'plot_amount': plot_amount,
            'plot_count': plot_count,
            'plot_crypto_dist': plot_crypto_dist,
            'plot_status_dist': plot_status_dist
        }
        
        # دمج القيم الافتراضية مع الإحصائيات الفعلية
        template_data = {**default_stats, **stats}
        
        return render_template('analytics.html', **template_data)
                             
    except Exception as e:
        print(f"خطأ: {str(e)}")
        flash(f'حدث خطأ: {str(e)}')
        
        # إرجاع القالب مع القيم الافتراضية في حالة حدوث خطأ
        default_stats = {
            'total_amount': 0,
            'total_transactions': 0,
            'success_rate': 0,
            'avg_amount': 0,
            'amount_trend': 0,
            'transaction_trend': 0,
            'success_trend': 0,
            'avg_trend': 0,
            'plot_amount': "{}",
            'plot_count': "{}",
            'plot_crypto_dist': "{}",
            'plot_status_dist': "{}"
        }
        return render_template('analytics.html', **default_stats)

@app.route('/analytics/data')
@login_required
def analytics_data():
    """جلب بيانات المخططات التحليلية"""
    try:
        days = int(request.args.get('days', 30))
        chart_type = request.args.get('type', 'amount')
        
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'فشل الاتصال بقاعدة البيانات'})

        cur = conn.cursor(cursor_factory=DictCursor)
        
        # جلب البيانات للفترة المحددة
        cur.execute("""
            WITH daily_data AS (
                SELECT 
                    DATE(created_at) as date,
                    COUNT(*) as count,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count,
                    SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END) as total_usd
                FROM withdrawal_requests
                WHERE created_at >= NOW() - INTERVAL '%s days'
                GROUP BY DATE(created_at)
            )
            SELECT 
                date,
                count,
                completed_count,
                total_usd,
                CASE WHEN count > 0 
                    THEN ROUND((completed_count::float / count * 100)::numeric, 2)
                    ELSE 0 
                END as success_rate
            FROM daily_data
            ORDER BY date
        """, (days,))
        
        # جلب النتائج
        results = cur.fetchall()
        
        # تحديد أسماء الأعمدة
        columns = ['date', 'count', 'completed_count', 'total_usd', 'success_rate']
        
        # تحويل النتائج إلى DataFrame مع تحديد أسماء الأعمدة
        df = pd.DataFrame(results, columns=columns)
        
        # تحويل التاريخ إلى التنسيق المناسب
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        
        # تأكد من أن جميع القيم الرقمية صحيحة
        df['count'] = pd.to_numeric(df['count'], errors='coerce').fillna(0)
        df['completed_count'] = pd.to_numeric(df['completed_count'], errors='coerce').fillna(0)
        df['total_usd'] = pd.to_numeric(df['total_usd'], errors='coerce').fillna(0)
        df['success_rate'] = pd.to_numeric(df['success_rate'], errors='coerce').fillna(0)
        
        cur.close()
        conn.close()
        
        if df.empty:
            return jsonify({'error': 'لا توجد بيانات للفترة المحددة'})

        # تهيئة مظهر المخطط
        layout = {
            'font': {'family': 'Arial, sans-serif'},
            'paper_bgcolor': 'rgba(0,0,0,0)',
            'plot_bgcolor': 'rgba(0,0,0,0)',
            'margin': {'t': 50, 'r': 20, 'b': 50, 'l': 50},
            'showlegend': True,
            'hovermode': 'x unified',
            'xaxis': {
                'gridcolor': '#eee',
                'zeroline': False,
                'title': 'التاريخ'
            },
            'yaxis': {
                'gridcolor': '#eee',
                'zeroline': False,
                'title': 'المبلغ (USD)' if chart_type == 'amount' else 'عدد العمليات'
            }
        }

        # إنشاء قائمة التواريخ للمحور السيني
        date_range = pd.date_range(
            end=pd.Timestamp.now(),
            periods=days,
            freq='D'
        ).strftime('%Y-%m-%d').tolist()

        # دمج البيانات مع قائمة التواريخ الكاملة
        df_full = pd.DataFrame({'date': date_range})
        df_full = df_full.merge(df, on='date', how='left')
        df_full = df_full.fillna(0)

        if chart_type == 'amount':
            # مخطط المبالغ
            fig = go.Figure()
            
            # إضافة خط المبالغ
            fig.add_trace(go.Scatter(
                x=df_full['date'],
                y=df_full['total_usd'],
                mode='lines+markers',
                name='المبالغ اليومية',
                line={'color': '#2ecc71', 'width': 2},
                marker={'size': 8, 'symbol': 'circle'},
                hovertemplate='<b>التاريخ:</b> %{x}<br><b>المبلغ:</b> $%{y:,.2f}<extra></extra>'
            ))
            
            # تحديث العنوان
            fig.update_layout(
                title=f'المبالغ اليومية (آخر {days} يوم)',
                yaxis_title='المبلغ (USD)'
            )
        else:
            # مخطط العمليات
            fig = go.Figure()
            
            # إضافة أعمدة إجمالي العمليات
            fig.add_trace(go.Bar(
                x=df_full['date'],
                y=df_full['count'],
                name='إجمالي العمليات',
                marker_color='#3498db',
                hovertemplate='<b>التاريخ:</b> %{x}<br><b>إجمالي العمليات:</b> %{y}<extra></extra>'
            ))
            
            # إضافة أعمدة العمليات المكتملة
            fig.add_trace(go.Bar(
                x=df_full['date'],
                y=df_full['completed_count'],
                name='العمليات المكتملة',
                marker_color='#2ecc71',
                hovertemplate='<b>التاريخ:</b> %{x}<br><b>العمليات المكتملة:</b> %{y}<extra></extra>'
            ))
            
            # إضافة خط نسبة النجاح
            fig.add_trace(go.Scatter(
                x=df_full['date'],
                y=df_full['success_rate'],
                name='نسبة النجاح',
                yaxis='y2',
                line={'color': '#e74c3c', 'width': 2, 'dash': 'dot'},
                hovertemplate='<b>التاريخ:</b> %{x}<br><b>نسبة النجاح:</b> %{y:.1f}%<extra></extra>'
            ))
            
            # تحديث التخطيط
            fig.update_layout(
                title=f'عدد العمليات اليومية (آخر {days} يوم)',
                barmode='group',
                yaxis={'title': 'عدد العمليات'},
                yaxis2={
                    'title': 'نسبة النجاح (%)',
                    'overlaying': 'y',
                    'side': 'right',
                    'showgrid': False,
                    'range': [0, 100]
                }
            )

        # تطبيق التنسيق العام
        fig.update_layout(layout)
            
        return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        
    except Exception as e:
        print(f"خطأ: {str(e)}")
        return jsonify({'error': str(e)})

@app.route('/api/code_transactions/<int:user_id>')
@login_required
def get_code_transactions(user_id):
    """جلب تفاصيل العمليات لمستخدم معين"""
    conn = None
    try:
        # إنشاء اتصال بقاعدة البيانات
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'error': 'فشل الاتصال بقاعدة البيانات',
                'transactions': []
            }), 500

        # إنشاء cursor مع التعامل مع النتائج كقواميس
        with conn.cursor(cursor_factory=DictCursor) as cur:
            # التحقق من وجود المستخدم
            cur.execute("SELECT code FROM registration_codes WHERE user_id = %s AND is_used = TRUE", (user_id,))
            user_code = cur.fetchone()
            
            if not user_code:
                return jsonify({
                    'error': 'لم يتم العثور على الكود',
                    'transactions': []
                }), 404
            
            # جلب تفاصيل العمليات للمستخدم
            cur.execute("""
                SELECT 
                    withdrawal_id,
                    local_amount,
                    local_currency,
                    local_currency_name,
                    crypto_amount,
                    crypto_currency,
                    network_code,
                    network_name,
                    status,
                    created_at,
                    transfer_number,
                    transfer_issuer
                FROM withdrawal_requests 
                WHERE user_id = %s
                ORDER BY created_at DESC
            """, (user_id,))
            
            # تحويل النتائج إلى قائمة من القواميس
            transactions = []
            for row in cur.fetchall():
                transaction = dict(row)
                # تنسيق التواريخ والأرقام
                transaction['created_at'] = transaction['created_at'].isoformat()
                transaction['local_amount'] = float(transaction['local_amount']) if transaction['local_amount'] else 0
                transaction['crypto_amount'] = float(transaction['crypto_amount']) if transaction['crypto_amount'] else 0
                transactions.append(transaction)
            
            return jsonify({
                'code': user_code['code'],
                'transactions': transactions,
                'total_count': len(transactions),
                'total_amount': sum(t['crypto_amount'] for t in transactions)
            })
            
    except Exception as e:
        print(f"خطأ في جلب تفاصيل العمليات: {str(e)}")
        return jsonify({
            'error': 'حدث خطأ أثناء جلب البيانات',
            'transactions': []
        }), 500
        
    finally:
        if conn:
            conn.close()

@app.route('/analytics/export')
@login_required
def export_analytics():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        
        # جمع البيانات للتصدير
        cur.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as total_transactions,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_transactions,
                SUM(CASE WHEN status = 'completed' THEN crypto_amount ELSE 0 END) as total_amount_usd,
                AVG(CASE WHEN status = 'completed' THEN crypto_amount ELSE NULL END) as avg_amount_usd
            FROM withdrawal_requests
            WHERE created_at >= NOW() - INTERVAL '90 days'
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        
        df = pd.DataFrame(cur.fetchall())
        cur.close()
        conn.close()
        
        if not df.empty:
            # تنسيق البيانات
            df['success_rate'] = (df['completed_transactions'] / df['total_transactions'] * 100).round(2)
            df['avg_amount_usd'] = df['avg_amount_usd'].round(2)
            
            # إنشاء ملف Excel
            export_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
            if not os.path.exists(export_dir):
                os.makedirs(export_dir)
                
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(export_dir, f'analytics_report_{timestamp}.xlsx')
            
            # تصدير إلى Excel مع تنسيق العربية
            writer = pd.ExcelWriter(filename, engine='xlsxwriter')
            df.to_excel(writer, sheet_name='Analytics', index=False)
            
            # تنسيق الورقة
            workbook = writer.book
            worksheet = writer.sheets['Analytics']
            
            # تنسيق العناوين
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'top',
                'align': 'center',
                'bg_color': '#D9D9D9',
                'border': 1
            })
            
            # تطبيق التنسيق
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)
                worksheet.set_column(col_num, col_num, 15)
            
            writer.close()
            
            return send_file(filename, as_attachment=True)
            
        flash('لا توجد بيانات للتصدير', 'warning')
        return redirect(url_for('analytics'))
        
    except Exception as e:
        flash(f'حدث خطأ أثناء تصدير البيانات: {str(e)}', 'error')
        return redirect(url_for('analytics'))

@app.route('/export_codes')
@login_required
def export_codes():
    """تصدير بيانات الأكواد إلى ملف CSV"""
    try:
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بقاعدة البيانات', 'error')
            return redirect(url_for('codes'))

        with conn.cursor(cursor_factory=DictCursor) as cur:
            # جلب البيانات
            cur.execute("""
                SELECT 
                    rc.code as code,
                    rc.user_id as user_id,
                    CASE WHEN rc.is_used THEN 'نعم' ELSE 'لا' END as is_used,
                    COUNT(wr.withdrawal_id) as total_transactions,
                    COALESCE(SUM(CASE 
                        WHEN wr.status = 'completed' THEN CAST(wr.crypto_amount AS FLOAT) 
                        ELSE 0 
                    END), 0.0) as total_amount_usd,
                    MIN(wr.created_at) as first_transaction_date,
                    MAX(wr.created_at) as last_transaction_date,
                    COUNT(CASE WHEN wr.status = 'completed' THEN 1 END) as completed_transactions,
                    COUNT(CASE WHEN wr.status = 'pending' THEN 1 END) as pending_transactions,
                    COUNT(CASE WHEN wr.status = 'failed' OR wr.status = 'cancelled' THEN 1 END) as failed_transactions
                FROM registration_codes rc
                LEFT JOIN withdrawal_requests wr ON rc.user_id = wr.user_id
                GROUP BY rc.code, rc.user_id, rc.is_used
                ORDER BY rc.code
            """)
            
            # تحويل النتائج إلى DataFrame
            results = cur.fetchall()
            print(f"تم جلب {len(results)} صف من البيانات")
            
            # التحقق من البيانات
            if not results:
                flash('لا توجد بيانات للتصدير', 'warning')
                return redirect(url_for('codes'))
            
            # الحصول على أسماء الأعمدة
            column_names = [desc[0] for desc in cur.description]
            print(f"أسماء الأعمدة: {column_names}")
            
            # تحويل إلى DataFrame مع تحديد أسماء الأعمدة
            df = pd.DataFrame(results, columns=column_names)
            
            # تعيين أسماء الأعمدة العربية
            column_mapping = {
                'code': 'الكود',
                'user_id': 'معرف المستخدم',
                'is_used': 'مستخدم',
                'total_transactions': 'عدد العمليات',
                'total_amount_usd': 'إجمالي المبالغ (USD)',
                'first_transaction_date': 'تاريخ أول عملية',
                'last_transaction_date': 'تاريخ آخر عملية',
                'completed_transactions': 'العمليات المكتملة',
                'pending_transactions': 'العمليات المعلقة',
                'failed_transactions': 'العمليات الملغاة'
            }
            
            # إعادة تسمية الأعمدة
            df = df.rename(columns=column_mapping)
            
            print(f"أعمدة DataFrame: {df.columns.tolist()}")
            print(f"عدد الصفوف: {len(df)}")
            
            # طباعة عينة من البيانات للتحقق
            print("\nعينة من البيانات:")
            print(df.head())
            
            if df.empty:
                flash('لا توجد بيانات للتصدير', 'warning')
                return redirect(url_for('codes'))

            try:
                # تنسيق التواريخ
                date_columns = ['تاريخ أول عملية', 'تاريخ آخر عملية']
                for col in date_columns:
                    if col in df.columns:
                        df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
                        df[col] = df[col].fillna('-')

                # تنسيق الأرقام
                numeric_columns = [
                    'عدد العمليات',
                    'إجمالي المبالغ (USD)',
                    'العمليات المكتملة',
                    'العمليات المعلقة',
                    'العمليات الملغاة'
                ]
                
                for col in numeric_columns:
                    if col in df.columns:
                        # تحويل إلى float وتعبئة القيم الفارغة بـ 0
                        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                        # تقريب الأرقام
                        if col == 'إجمالي المبالغ (USD)':
                            df[col] = df[col].round(2)
                        else:
                            df[col] = df[col].astype(int)

                # ترتيب الأعمدة
                desired_columns = [
                    'الكود',
                    'معرف المستخدم',
                    'مستخدم',
                    'عدد العمليات',
                    'العمليات المكتملة',
                    'العمليات المعلقة',
                    'العمليات الملغاة',
                    'إجمالي المبالغ (USD)',
                    'تاريخ أول عملية',
                    'تاريخ آخر عملية'
                ]
                
                # إعادة ترتيب الأعمدة الموجودة فقط
                existing_columns = [col for col in desired_columns if col in df.columns]
                df = df[existing_columns]

            except Exception as e:
                print(f"خطأ في معالجة البيانات: {str(e)}")
                raise

            # إنشاء مجلد التصدير إذا لم يكن موجوداً
            export_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
            if not os.path.exists(export_dir):
                os.makedirs(export_dir)

            # حفظ الملف بتنسيق Excel
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(export_dir, f'registration_codes_{timestamp}.xlsx')

            # تنسيق البيانات قبل التصدير
            # تنسيق المبالغ
            if 'إجمالي المبالغ (USD)' in df.columns:
                df['إجمالي المبالغ (USD)'] = df['إجمالي المبالغ (USD)'].apply(lambda x: f"${x:,.2f}")

            # تنسيق الأعداد
            numeric_columns = ['عدد العمليات', 'العمليات المكتملة', 'العمليات المعلقة', 'العمليات الملغاة']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = df[col].fillna(0).astype(int)

            # حفظ إلى Excel
            df.to_excel(
                filename,
                sheet_name='الأكواد المسجلة',
                index=False,
                engine='openpyxl'
            )
            
            # إرجاع الملف للتحميل
            return send_file(
                filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                as_attachment=True,
                download_name=f'registration_codes_{timestamp}.xlsx'
            )

    except Exception as e:
        print(f"خطأ في تصدير البيانات: {str(e)}")
        flash(f'حدث خطأ أثناء تصدير البيانات: {str(e)}', 'error')
        return redirect(url_for('codes'))

    finally:
        if conn:
            conn.close()

@app.route('/export_withdrawals')
@login_required
def export_withdrawals():
    try:
        conn = get_db_connection()
        if conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("""
                    SELECT 
                        wr.withdrawal_id,
                        wr.user_id,
                        rc.code as registration_code,
                        wr.local_amount,
                        wr.local_currency,
                        wr.local_currency_name,
                        wr.crypto_amount,
                        wr.crypto_currency,
                        wr.network_code,
                        wr.network_name,
                        wr.wallet_address,
                        wr.transfer_number,
                        wr.transfer_issuer,
                        wr.status,
                        wr.created_at
                    FROM withdrawal_requests wr
                    LEFT JOIN registration_codes rc ON wr.user_id = rc.user_id
                    ORDER BY wr.created_at DESC
                """)
                withdrawals = cur.fetchall()
                
                # تحويل البيانات إلى DataFrame
                df = pd.DataFrame(withdrawals, columns=[
                    'withdrawal_id', 'user_id', 'registration_code', 'local_amount',
                    'local_currency', 'local_currency_name', 'crypto_amount', 'crypto_currency',
                    'network_code', 'network_name', 'wallet_address', 'transfer_number',
                    'transfer_issuer', 'status', 'created_at'
                ])
                
                # تنسيق التاريخ
                df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                # إنشاء المسار المطلق لمجلد التصدير
                export_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'exports')
                
                # إنشاء مجلد للملفات المصدرة إذا لم يكن موجوداً
                if not os.path.exists(export_dir):
                    os.makedirs(export_dir)
                
                # حفظ الملف
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = os.path.join(export_dir, f'withdrawals_{timestamp}.xlsx')
                df.to_excel(filename, index=False, sheet_name='Withdrawals')
                
                # إرجاع الملف للتحميل
                return send_file(filename, as_attachment=True)
    except Exception as e:
        flash(f'حدث خطأ أثناء تصدير البيانات: {str(e)}', 'error')
        return redirect(url_for('withdrawals'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            user = User(username)
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('خطأ في اسم المستخدم أو كلمة المرور')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/send-message')
@login_required
def send_message():
    return render_template('send_message.html')

@app.route('/restart-scheduler', methods=['POST'])
@login_required
def restart_scheduler():
    try:
        init_app()
        flash('تم إعادة تشغيل المجدول بنجاح', 'success')
    except Exception as e:
        flash(f'حدث خطأ أثناء إعادة تشغيل المجدول: {str(e)}', 'error')
    return redirect(url_for('scheduled_messages'))

@app.route('/scheduled-messages')
@login_required
def scheduled_messages():
    from datetime import datetime, timezone
    import pytz
    
    messages = []
    current_time_utc = datetime.now(timezone.utc)
    current_time_riyadh = current_time_utc.astimezone(pytz.timezone('Asia/Riyadh'))
    scheduler_status = "متوقف"
    
    try:
        conn = get_db_connection()
        if not conn:
            flash('خطأ في الاتصال بقاعدة البيانات', 'error')
            return render_template('scheduled_messages.html',
                                messages=messages,
                                current_time_utc=current_time_utc,
                                current_time_riyadh=current_time_riyadh,
                                scheduler_status=scheduler_status)
        
        cur = conn.cursor(cursor_factory=DictCursor)
        
        # جلب الرسائل المجدولة
        cur.execute("""
            SELECT 
                id,
                message_text,
                user_ids,
                scheduled_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh' as scheduled_time,
                status,
                sent_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh' as sent_at,
                error_message
            FROM scheduled_messages
            ORDER BY scheduled_time DESC
        """)
        messages = [dict(row) for row in cur.fetchall()]
        
        # الحصول على التوقيت الحالي
        cur.execute("""
            SELECT 
                NOW() AT TIME ZONE 'UTC' as utc_time,
                NOW() AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Riyadh' as riyadh_time
        """)
        times = cur.fetchone()
        
        if times:
            current_time_utc = times['utc_time']
            current_time_riyadh = times['riyadh_time']
        
        # التحقق من حالة المجدول
        scheduler_status = "نشط" if hasattr(app, 'scheduler_thread') and app.scheduler_thread.is_alive() else "متوقف"
        
    except Exception as e:
        flash(f'حدث خطأ: {str(e)}', 'error')
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals() and conn:
            conn.close()
    
    return render_template('scheduled_messages.html',
                         messages=messages,
                         current_time_utc=current_time_utc,
                         current_time_riyadh=current_time_riyadh,
                         scheduler_status=scheduler_status)

@app.route('/api/get_users')
@login_required
def get_users():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=DictCursor)
        
        # استعلام محسن للحصول على جميع المستخدمين المسجلين
        cur.execute("""
            WITH registered_users AS (
                -- الحصول على جميع المستخدمين المسجلين
                SELECT 
                    user_id,
                    code as registration_code
                FROM registration_codes
                WHERE user_id IS NOT NULL
            )
            SELECT 
                ru.user_id as id,
                COALESCE(
                    ru.registration_code,
                    'مستخدم ' || ru.user_id::text
                ) as name,
                COUNT(wr.withdrawal_id) as withdrawal_count,
                MAX(wr.created_at) as last_activity
            FROM registered_users ru
            LEFT JOIN withdrawal_requests wr ON ru.user_id = wr.user_id
            GROUP BY ru.user_id, ru.registration_code
            ORDER BY last_activity DESC NULLS LAST, ru.user_id DESC
        """)
        
        users = [dict(row) for row in cur.fetchall()]
        print(f"Found {len(users)} unique users")
        
        # طباعة معلومات تفصيلية عن أول 5 مستخدمين
        if users:
            print("\nFirst 5 users details:")
            for user in users[:5]:
                print(f"ID: {user['id']}, Name: {user['name']}, "
                      f"Withdrawals: {user['withdrawal_count']}, "
                      f"Last Activity: {user['last_activity']}")
        
        # تحويل التاريخ إلى نص قبل إرسال JSON
        for user in users:
            if user['last_activity']:
                user['last_activity'] = user['last_activity'].isoformat()
        
        cur.close()
        conn.close()
        
        return jsonify(users)
    except Exception as e:
        print(f"Error getting users: {str(e)}")
        return jsonify([])
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.telegram_service import telegram_service
import asyncio
import tempfile
from contextlib import asynccontextmanager

def get_or_create_event_loop():
    """الحصول على حلقة أحداث موجودة أو إنشاء واحدة جديدة"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop

def send_telegram_message(chat_id: int, text: str, files=None) -> bool:
    """إرسال رسالة عبر Telegram مع دعم الوسائط المتعددة"""
    try:
        loop = get_or_create_event_loop()
        
        # إرسال الرسالة النصية
        success = loop.run_until_complete(
            telegram_service.send_message_with_retry(
                chat_id=chat_id,
                text=text
            )
        )
        
        if not success:
            return False
            
        # إرسال الملفات إذا وجدت
        if files:
            for file in files:
                # حفظ الملف مؤقتاً
                temp_dir = tempfile.mkdtemp()
                temp_path = os.path.join(temp_dir, file.filename)
                file.save(temp_path)
                
                try:
                    # تحديد نوع الملف وإرساله
                    with open(temp_path, 'rb') as f:
                        if file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                            loop.run_until_complete(
                                telegram_service.bot.send_photo(chat_id=chat_id, photo=f)
                            )
                        elif file.filename.lower().endswith(('.mp4', '.avi', '.mov')):
                            loop.run_until_complete(
                                telegram_service.bot.send_video(chat_id=chat_id, video=f)
                            )
                        else:
                            loop.run_until_complete(
                                telegram_service.bot.send_document(chat_id=chat_id, document=f)
                            )
                finally:
                    # تنظيف الملفات المؤقتة
                    try:
                        os.remove(temp_path)
                        os.rmdir(temp_dir)
                    except:
                        pass
                            
        return True
            
    except Exception as e:
        print(f"Error in send_telegram_message: {e}")
        return False

def save_scheduled_message(user_ids, message_text, scheduled_time, files=None):
    """حفظ رسالة مجدولة في قاعدة البيانات"""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # تحويل معرفات المستخدمين إلى مصفوفة من BIGINT
        user_ids_array = [int(uid) for uid in user_ids]
        
        # حفظ الملفات المؤقتة إذا وجدت
        saved_files = []
        if files:
            for file in files:
                # إنشاء مجلد للملفات المجدولة إذا لم يكن موجوداً
                os.makedirs('scheduled_files', exist_ok=True)
                
                # حفظ الملف بشكل مؤقت
                filename = secure_filename(file.filename)
                temp_path = os.path.join('scheduled_files', f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}")
                file.save(temp_path)
                saved_files.append(temp_path)
        
        # حفظ الرسالة في قاعدة البيانات
        cur.execute("""
            INSERT INTO scheduled_messages 
            (user_ids, message_text, scheduled_time, files)
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (user_ids_array, message_text, scheduled_time, saved_files if saved_files else None))
        
        message_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        
        return True, message_id
    except Exception as e:
        print(f"Error saving scheduled message: {str(e)}")
        return False, str(e)

@app.route('/api/send_custom_message', methods=['POST'])
@login_required
def send_custom_message():
    """معالج إرسال الرسائل المخصصة"""
    try:
        # التحقق من البيانات المطلوبة
        user_ids = request.form.getlist('user_ids[]')
        message = request.form.get('message')
        files = request.files.getlist('files[]')
        
        # التحقق من الجدولة
        is_scheduled = request.form.get('is_scheduled') == '1'
        scheduled_time = request.form.get('scheduled_time')

        if not user_ids or not message:
            return jsonify({
                'success': False,
                'error': 'يجب تحديد المستخدم والرسالة'
            })

        # تحويل المعرفات إلى أرقام
        try:
            user_ids = [int(uid) for uid in user_ids if uid != 'all']
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'معرف مستخدم غير صالح'
            })

        # التحقق من الجدولة وحفظ الرسالة المجدولة
        if is_scheduled and scheduled_time:
            try:
                # تحويل التوقيت إلى UTC
                from datetime import datetime
                import pytz
                
                # تحويل النص إلى كائن datetime
                riyadh_tz = pytz.timezone('Asia/Riyadh')
                # إضافة ":00" للثواني إذا لم تكن موجودة
                if len(scheduled_time) == 16:
                    scheduled_time += ":00"
                # تحويل النص إلى datetime في توقيت الرياض
                local_dt = riyadh_tz.localize(datetime.strptime(scheduled_time, "%Y-%m-%dT%H:%M:%S"))
                # تحويل إلى UTC
                utc_dt = local_dt.astimezone(pytz.UTC)
                
                # حفظ الرسالة المجدولة
                success, result = save_scheduled_message(user_ids, message, utc_dt, files)
                
                if success:
                    return jsonify({
                        'success': True,
                        'message': f'تمت جدولة الرسالة للإرسال في {local_dt.strftime("%Y-%m-%d %H:%M")}'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': f'خطأ في حفظ الرسالة المجدولة: {result}'
                    })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'خطأ في معالجة وقت الجدولة: {str(e)}'
                })

        # إذا لم تكن الرسالة مجدولة، نتابع مع الإرسال الفوري
        try:
            user_ids = [int(uid) for uid in user_ids if uid != 'all']
        except ValueError:
            return jsonify({
                'success': False,
                'error': 'معرف المستخدم غير صالح'
            })

        # إذا كان الإرسال للجميع، نجلب كل المستخدمين
        if 'all' in request.form.getlist('user_ids[]'):
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT user_id FROM withdrawal_requests")
            all_users = [row[0] for row in cur.fetchall()]
            cur.close()
            conn.close()
            user_ids.extend(all_users)
            # إزالة التكرار
            user_ids = list(set(user_ids))

        # حفظ الملفات مؤقتًا
        temp_files = []
        if files:
            for file in files:
                temp_dir = tempfile.mkdtemp()
                temp_path = os.path.join(temp_dir, file.filename)
                file.save(temp_path)
                temp_files.append({
                    'path': temp_path,
                    'dir': temp_dir,
                    'filename': file.filename
                })

        success_count = 0
        failed_users = []

        # إرسال الرسائل النصية لجميع المستخدمين
        loop = get_or_create_event_loop()
        for user_id in user_ids:
            try:
                # إرسال النص
                success = loop.run_until_complete(
                    telegram_service.send_message_with_retry(
                        chat_id=user_id,
                        text=message
                    )
                )

                if success:
                    # إرسال الملفات
                    for temp_file in temp_files:
                        try:
                            with open(temp_file['path'], 'rb') as f:
                                if temp_file['filename'].lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                                    loop.run_until_complete(
                                        telegram_service.bot.send_photo(chat_id=user_id, photo=f)
                                    )
                                elif temp_file['filename'].lower().endswith(('.mp4', '.avi', '.mov')):
                                    loop.run_until_complete(
                                        telegram_service.bot.send_video(chat_id=user_id, video=f)
                                    )
                                else:
                                    loop.run_until_complete(
                                        telegram_service.bot.send_document(chat_id=user_id, document=f)
                                    )
                        except Exception as e:
                            print(f"Error sending file to user {user_id}: {e}")

                    success_count += 1
                else:
                    failed_users.append(user_id)
            except Exception as e:
                print(f"Error sending to user {user_id}: {e}")
                failed_users.append(user_id)

        # تنظيف الملفات المؤقتة
        for temp_file in temp_files:
            try:
                os.remove(temp_file['path'])
                os.rmdir(temp_file['dir'])
            except:
                pass

        # إعداد رسالة النتيجة
        if success_count == len(user_ids):
            return jsonify({
                'success': True,
                'message': f'تم إرسال الرسالة بنجاح إلى {success_count} مستخدم'
            })
        elif success_count > 0:
            return jsonify({
                'success': True,
                'message': f'تم إرسال الرسالة بنجاح إلى {success_count} مستخدم، وفشل الإرسال إلى {len(failed_users)} مستخدم'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'فشل في إرسال جميع الرسائل'
            })

    except Exception as e:
        print(f"Error sending message: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'خطأ غير متوقع: {str(e)}'
        })

def start_scheduler():
    """بدء تشغيل جدولة الرسائل في خلفية منفصلة"""
    import threading
    import asyncio
    from datetime import datetime, timezone
    import pytz
    
    async def process_scheduled_messages():
        """معالجة الرسائل المجدولة"""
        print("🔄 بدء تشغيل معالج الرسائل المجدولة")
        while not getattr(app, 'scheduler_stop', False):
            try:
                conn = get_db_connection()
                cur = conn.cursor(cursor_factory=DictCursor)
                
                # البحث عن الرسائل المجدولة التي حان وقت إرسالها
                now_utc = datetime.now(timezone.utc)
                riyadh_tz = pytz.timezone('Asia/Riyadh')
                now_riyadh = now_utc.astimezone(riyadh_tz)
                
                print(f"\nChecking scheduled messages at:")
                print(f"UTC time: {now_utc}")
                print(f"Riyadh time: {now_riyadh}")
                
                cur.execute("""
                    SELECT 
                        id, 
                        user_ids, 
                        message_text, 
                        files,
                        scheduled_time AT TIME ZONE 'UTC' AS utc_time,
                        scheduled_time AT TIME ZONE 'Asia/Riyadh' AS riyadh_time,
                        scheduled_time as original_time
                    FROM scheduled_messages
                    WHERE status = 'pending'
                    AND scheduled_time <= timezone('UTC', NOW())
                    ORDER BY scheduled_time
                """)
                
                print("\nCurrent pending messages:")
                
                # طباعة معلومات التوقيت للتشخيص
                print("\nSystem time (UTC):", datetime.now(timezone.utc))
                print("Checking scheduled messages...")
                
                messages = cur.fetchall()
                
                for msg in messages:
                    print(f"\nProcessing scheduled message {msg['id']}")
                    print(f"Scheduled time (UTC): {msg['utc_time']}")
                    print(f"Scheduled time (Riyadh): {msg['riyadh_time']}")
                    print(f"Message text: {msg['message_text']}")
                    success_count = 0
                    failed_users = []
                    
                    # إرسال الرسالة لكل مستخدم
                    for user_id in msg['user_ids']:
                        try:
                            success = send_telegram_message(
                                chat_id=user_id,
                                text=msg['message_text'],
                                files=msg['files']
                            )
                            
                            if success:
                                success_count += 1
                            else:
                                failed_users.append(user_id)
                                
                        except Exception as e:
                            print(f"Error processing user {user_id} for message {msg['id']}: {e}")
                            failed_users.append(user_id)
                    
                    # تحديث حالة الرسالة
                    status = 'completed' if not failed_users else 'partial'
                    error_message = f"Failed users: {failed_users}" if failed_users else None
                    
                    cur.execute("""
                        UPDATE scheduled_messages
                        SET status = %s,
                            sent_at = NOW(),
                            error_message = %s
                        WHERE id = %s
                    """, (status, error_message, msg['id']))
                    
                    # حذف الملفات المؤقتة
                    if msg['files']:
                        for file_path in msg['files']:
                            try:
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                            except Exception as e:
                                print(f"Error deleting file {file_path}: {e}")
                    
                    conn.commit()
                    
                    print(f"Message {msg['id']} processed: {success_count} successful, {len(failed_users)} failed")
                
                cur.close()
                conn.close()
                
            except Exception as e:
                print(f"Error in process_scheduled_messages: {e}")
            
            # انتظار 60 ثانية قبل التحقق مرة أخرى
            await asyncio.sleep(60)

    def run_scheduler():
        """تشغيل المجدول في حلقة غير متزامنة"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_scheduled_messages())

    # بدء المجدول في خيط منفصل
    app.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    app.scheduler_thread.start()
    print("✅ تم بدء تشغيل نظام جدولة الرسائل")

def init_app():
    """تهيئة التطبيق وبدء المجدول"""
    # تأكد من إيقاف المجدول القديم إذا كان موجوداً
    if hasattr(app, 'scheduler_thread') and app.scheduler_thread and app.scheduler_thread.is_alive():
        print("Stopping old scheduler...")
        app.scheduler_stop = True
        app.scheduler_thread.join(timeout=5)
    
    # إعادة تعيين متغير التوقف
    app.scheduler_stop = False
    
    # بدء المجدول
    start_scheduler()
    print("✅ تم تهيئة التطبيق وبدء المجدول")

if __name__ == '__main__':
    # تهيئة التطبيق
    init_app()
    
    # تشغيل التطبيق
    port = int(os.environ.get('PORT', 54302))
    app.run(host='0.0.0.0', port=port, debug=False)
