from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, make_response
import os
import re
import json
import pandas as pd
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from flask_migrate import Migrate
from models import db, Transaction

app = Flask(__name__)
app.secret_key = 'wallet_sms_analyzer_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# Configure PostgreSQL database
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://metabit_safty_db_user:i7jQbcMMM2sg7k12PwweDO1koIUd3ppF@dpg-cvc9e8bv2p9s73ad9g5g-a.singapore-postgres.render.com/metabit_safty_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)
migrate = Migrate(app, db)

# Ensure the data directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Define currency symbols and codes
CURRENCIES = {
    'ر.ي': 'YER',
    'ر.س': 'SAR',
    'د.أ': 'USD'
}

# Define wallet types
WALLET_TYPES = ['Jaib', 'Jawali', 'Cash']

def parse_jaib_sms(message):
    """Parse SMS messages from Jaib wallet."""
    transaction = {}
    
    # Check if it's a credit or debit transaction
    if 'اضيف' in message:
        transaction['type'] = 'credit'
        amount_pattern = r'اضيف (\d+(?:\.\d+)?)([^م]+)'
    elif 'خصم' in message:
        transaction['type'] = 'debit'
        amount_pattern = r'خصم (\d+(?:\.\d+)?)([^م]+)'
    else:
        return None
    
    # Extract amount and currency
    amount_match = re.search(amount_pattern, message)
    if amount_match:
        transaction['amount'] = float(amount_match.group(1))
        currency_raw = amount_match.group(2).strip()
        transaction['currency'] = CURRENCIES.get(currency_raw, currency_raw)
    
    # Extract balance
    balance_match = re.search(r'رص:(\d+(?:\.\d+)?)([^م]+)', message)
    if balance_match:
        transaction['balance'] = float(balance_match.group(1))
        balance_currency_raw = balance_match.group(2).strip()
        transaction['balance_currency'] = CURRENCIES.get(balance_currency_raw, balance_currency_raw)
    
    # Extract transaction details
    if 'مقابل' in message:
        details_match = re.search(r'مقابل ([^ر]+)', message)
        if details_match:
            transaction['details'] = details_match.group(1).strip()
    
    # Extract recipient/sender if available
    if 'من' in message and 'مقابل' in message:
        sender_match = re.search(r'من (.+?)(?:$|\n)', message)
        if sender_match:
            transaction['counterparty'] = sender_match.group(1).strip()
    elif 'الى' in message:
        recipient_match = re.search(r'الى (.+?)(?:$|\n)', message)
        if recipient_match:
            transaction['counterparty'] = recipient_match.group(1).strip()
    
    return transaction

def parse_jawali_sms(message):
    """Parse SMS messages from Jawali wallet."""
    transaction = {}
    
    if 'استلمت مبلغ' in message:
        transaction['type'] = 'credit'
        # Extract amount and currency
        amount_match = re.search(r'استلمت مبلغ (\d+(?:\.\d+)?) ([A-Z]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1))
            transaction['currency'] = amount_match.group(2)
        
        # Extract sender
        sender_match = re.search(r'من (\d+)', message)
        if sender_match:
            transaction['counterparty'] = sender_match.group(1)
        
        # Extract balance
        balance_match = re.search(r'رصيدك هو (\d+(?:\.\d+)?)', message)
        if balance_match:
            transaction['balance'] = float(balance_match.group(1))
            # Extract balance currency
            balance_currency_match = re.search(r'رصيدك هو \d+(?:\.\d+)? ([A-Z]+)', message)
            if balance_currency_match:
                transaction['balance_currency'] = balance_currency_match.group(1)
        
        transaction['details'] = 'استلام مبلغ'
    
    return transaction

def parse_cash_sms(message):
    """Parse SMS messages from Cash wallet."""
    transaction = {}
    
    if 'إضافة' in message:
        transaction['type'] = 'credit'
        # Extract amount and currency
        amount_match = re.search(r'إضافة(\d+(?:\.\d+)?) ([A-Z]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1))
            transaction['currency'] = amount_match.group(2)
        
        # Extract sender
        sender_match = re.search(r'من (.+?) رصيدك', message)
        if sender_match:
            transaction['counterparty'] = sender_match.group(1).strip()
        
        # Extract balance
        balance_match = re.search(r'رصيدك(\d+(?:\.\d+)?) ([A-Z]+)', message)
        if balance_match:
            transaction['balance'] = float(balance_match.group(1))
            transaction['balance_currency'] = balance_match.group(2)
        
        transaction['details'] = 'إضافة رصيد'
    
    elif 'سحب' in message:
        transaction['type'] = 'debit'
        # Extract amount and currency
        amount_match = re.search(r'سحب (\d+(?:\.\d+)?) ([A-Z]+)', message)
        if amount_match:
            transaction['amount'] = float(amount_match.group(1))
            transaction['currency'] = amount_match.group(2)
        
        # Extract balance
        balance_match = re.search(r'رصيدك (\d+(?:\.\d+)?) ([A-Z]+)', message)
        if balance_match:
            transaction['balance'] = float(balance_match.group(1))
            transaction['balance_currency'] = balance_match.group(2)
        
        transaction['details'] = 'سحب رصيد'
    
    return transaction

def parse_sms(sms_text):
    """Parse SMS text to extract transaction data."""
    transactions = []
    
    # Split the text into individual SMS messages
    sms_messages = re.split(r'\n\s*\n', sms_text)
    
    for message in sms_messages:
        if not message.strip():
            continue
        
        # Extract the wallet type from the "From:" line
        wallet_match = re.search(r'From: ([^\n]+)', message)
        if not wallet_match:
            continue
        
        wallet_name = wallet_match.group(1).strip()
        message_body = message.replace(wallet_match.group(0), '').strip()
        
        transaction = None
        if 'Jaib' in wallet_name:
            transaction = parse_jaib_sms(message_body)
        elif 'Jawali' in wallet_name:
            transaction = parse_jawali_sms(message_body)
        elif 'Cash' in wallet_name:
            transaction = parse_cash_sms(message_body)
        
        if transaction:
            transaction['wallet'] = wallet_name
            transaction['raw_message'] = message
            transaction['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            transactions.append(transaction)
    
    return transactions

def save_transactions(transactions):
    """Save transactions to the database."""
    count = 0
    
    # Get the latest transaction for each wallet/currency to check balance consistency
    latest_transactions = {}
    for wallet in WALLET_TYPES:
        latest_transactions[wallet] = {}
        for currency in ['YER', 'SAR', 'USD']:
            latest_tx = Transaction.query.filter_by(wallet=wallet, currency=currency).order_by(Transaction.timestamp.desc()).first()
            if latest_tx:
                latest_transactions[wallet][currency] = latest_tx.balance
            else:
                latest_transactions[wallet][currency] = 0
    
    for tx_data in transactions:
        # Create a new transaction object
        transaction = Transaction.from_dict(tx_data)
        
        # Add to database
        db.session.add(transaction)
        count += 1
    
    # Commit changes
    db.session.commit()
    
    return count

def load_transactions():
    """Load all transactions from the database."""
    transactions = Transaction.query.all()
    return [transaction.to_dict() for transaction in transactions]

def generate_transaction_summary(transactions):
    """Generate a summary of transactions organized by wallet and currency."""
    if not transactions:
        return None
    
    # Initialize summary structure
    summary = {
        wallet: {currency: {'credits': 0.0, 'debits': 0.0, 'net': 0.0} 
                for currency in ['YER', 'SAR', 'USD']}
        for wallet in WALLET_TYPES
    }
    
    # Process each transaction directly
    for tx in transactions:
        # Check if tx is a dict or SQLAlchemy object and extract fields accordingly
        if isinstance(tx, dict):
            wallet = tx.get('wallet')
            currency = tx.get('currency')
            tx_type = tx.get('type')
            tx_amount = tx.get('amount')
            tx_id = tx.get('id')
        else:
            wallet = tx.wallet
            currency = tx.currency
            tx_type = tx.type
            tx_amount = tx.amount
            tx_id = tx.id
        
        if wallet in summary and currency in summary[wallet]:
            try:
                amount = float(tx_amount) if tx_amount is not None else 0.0
                
                if tx_type == 'credit':
                    summary[wallet][currency]['credits'] += amount
                elif tx_type == 'debit':
                    summary[wallet][currency]['debits'] += amount
                
                # Recalculate net balance
                summary[wallet][currency]['net'] = summary[wallet][currency]['credits'] - summary[wallet][currency]['debits']
                
                # Debug output to help diagnose the issue
                print(f"Updated summary for {wallet}/{currency}: Credits={summary[wallet][currency]['credits']}, Debits={summary[wallet][currency]['debits']}, Net={summary[wallet][currency]['net']}")
            except (ValueError, TypeError) as e:
                print(f"Error processing transaction {tx_id}: {str(e)}")
    
    return summary

def generate_charts(transactions):
    """Generate charts for transaction visualization."""
    if not transactions:
        return {}
    
    df = pd.DataFrame(transactions)
    charts = {}
    
    # Ensure required columns exist
    required_columns = ['currency', 'type', 'amount']
    if not all(col in df.columns for col in required_columns):
        return charts
    
    # Transaction type distribution by currency
    plt.figure(figsize=(10, 6))
    for currency in df['currency'].unique():
        currency_df = df[df['currency'] == currency]
        
        # Count transactions by type
        type_counts = currency_df['type'].value_counts()
        
        plt.bar(
            [f"{currency} - {t}" for t in type_counts.index],
            type_counts.values
        )
    
    plt.title('Transaction Types by Currency')
    plt.xlabel('Currency - Transaction Type')
    plt.ylabel('Number of Transactions')
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Save to BytesIO
    img_bytes = BytesIO()
    plt.savefig(img_bytes, format='png')
    img_bytes.seek(0)
    
    # Convert to base64 for embedding in HTML
    img_base64 = base64.b64encode(img_bytes.read()).decode('utf-8')
    charts['transaction_types'] = img_base64
    
    plt.close()
    
    # Amount distribution by currency and type
    plt.figure(figsize=(10, 6))
    
    # Group by currency and type, sum amounts
    if len(df) > 0:
        grouped = df.groupby(['currency', 'type'])['amount'].sum().unstack()
        grouped.plot(kind='bar', ax=plt.gca())
        
        plt.title('Transaction Amounts by Currency and Type')
        plt.xlabel('Currency')
        plt.ylabel('Total Amount')
        plt.legend(title='Transaction Type')
        plt.tight_layout()
        
        # Save to BytesIO
        img_bytes = BytesIO()
        plt.savefig(img_bytes, format='png')
        img_bytes.seek(0)
        
        # Convert to base64 for embedding in HTML
        img_base64 = base64.b64encode(img_bytes.read()).decode('utf-8')
        charts['amount_distribution'] = img_base64
    
    plt.close()
    
    return charts

@app.route('/')
def index():
    """Render the home page."""
    transactions = load_transactions()
    summary = generate_transaction_summary(transactions)
    charts = generate_charts(transactions)
    
    return render_template(
        'index.html',
        transactions=transactions,
        summary=summary,
        charts=charts,
        now=datetime.now()
    )

@app.route('/wallet/<wallet_name>')
def wallet(wallet_name):
    """Display wallet details and transactions."""
    if wallet_name not in WALLET_TYPES:
        flash('المحفظة غير موجودة', 'danger')
        return redirect(url_for('index'))
    
    # Get transactions for this wallet - sort by timestamp ascending (oldest first) for processing
    transactions = Transaction.query.filter_by(wallet=wallet_name).order_by(Transaction.timestamp.asc(), Transaction.id.asc()).all()
    
    print(f"===== تحليل تأكيد المعاملات لمحفظة {wallet_name} =====")
    
    # Initialize dictionary to store confirmation status
    confirmed_status = {}
    db_updates_needed = False
    
    # Group transactions by currency
    transactions_by_currency = {}
    for tx in transactions:
        if tx.currency not in transactions_by_currency:
            transactions_by_currency[tx.currency] = []
        transactions_by_currency[tx.currency].append(tx)
    
    # Process each currency separately
    for currency, txs in transactions_by_currency.items():
        print(f"\n----- العملة: {currency} -----")
        
        # First transaction for each currency is not confirmed (can't verify)
        if len(txs) > 0:
            first_tx = txs[0]
            confirmed_status[first_tx.id] = False
            
            # Update database if different
            if first_tx.is_confirmed_db != False:
                first_tx.is_confirmed_db = False
                db_updates_needed = True
                
            print(f"معاملة {first_tx.transaction_id}: أول معاملة للعملة {currency} - غير مؤكدة")
        
        # Process remaining transactions
        for i in range(1, len(txs)):
            current_tx = txs[i]
            prev_tx = txs[i-1]
            
            tx_code = getattr(current_tx, 'transaction_id', f"TX{current_tx.id}")
            
            # Get current balance and previous balance
            try:
                current_balance = float(current_tx.balance)
                prev_balance = float(prev_tx.balance)
                amount = float(current_tx.amount)
                
                # Calculate expected balance based on previous transaction
                if current_tx.type == 'credit':
                    expected_balance = prev_balance + amount
                else:  # debit
                    expected_balance = prev_balance - amount
                
                # Round values to prevent floating point precision issues
                current_balance = round(current_balance, 2)
                expected_balance = round(expected_balance, 2)
                
                # Compare with a small tolerance (0.01) as in the account-deteils project
                is_confirmed = abs(current_balance - expected_balance) <= 0.01
                confirmed_status[current_tx.id] = is_confirmed
                
                # Update database if different
                if current_tx.is_confirmed_db != is_confirmed:
                    current_tx.is_confirmed_db = is_confirmed
                    db_updates_needed = True
                
                if is_confirmed:
                    print(f"معاملة {tx_code}: مؤكدة - الرصيد المتوقع {expected_balance:.2f} يتطابق مع الرصيد الفعلي {current_balance:.2f}")
                else:
                    print(f"معاملة {tx_code}: غير مؤكدة - الرصيد المتوقع {expected_balance:.2f} لا يتطابق مع الرصيد الفعلي {current_balance:.2f}")
            
            except (ValueError, TypeError):
                confirmed_status[current_tx.id] = False
                
                # Update database if different
                if current_tx.is_confirmed_db != False:
                    current_tx.is_confirmed_db = False
                    db_updates_needed = True
                    
                print(f"معاملة {tx_code}: غير مؤكدة - خطأ في تحويل الرصيد إلى رقم")
    
    # Save changes to database if needed
    if db_updates_needed:
        try:
            db.session.commit()
            print("تم تحديث حالات التأكيد في قاعدة البيانات")
        except Exception as e:
            db.session.rollback()
            print(f"خطأ في تحديث قاعدة البيانات: {str(e)}")
    
    # Sort transactions by timestamp, then by id in descending order for display
    # This handles cases where timestamps are identical (common with imported data)
    sorted_transactions = sorted(
        transactions, 
        key=lambda x: (x.timestamp, x.id), 
        reverse=True
    )
    
    # Generate transaction summary
    summary = generate_transaction_summary(transactions)
    
    # Generate charts if there are transactions
    charts = None
    if transactions:
        charts = generate_charts(transactions)
    
    # Add a no-cache header to ensure the browser doesn't cache the response
    response = make_response(render_template('wallet.html', 
                                            wallet_name=wallet_name, 
                                            transactions=sorted_transactions, 
                                            summary=summary, 
                                            charts=charts, 
                                            confirmed_status=confirmed_status,
                                            now=datetime.now()))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/upload', methods=['POST'])
def upload():
    """Process uploaded SMS text."""
    sms_text = request.form.get('sms_text', '')
    
    if not sms_text:
        flash('No SMS text provided', 'error')
        return redirect(url_for('index'))
    
    transactions = parse_sms(sms_text)
    
    if not transactions:
        flash('No valid transactions found in the SMS text', 'warning')
        return redirect(url_for('index'))
    
    num_saved = save_transactions(transactions)
    flash(f'Successfully processed {num_saved} transactions', 'success')
    
    return redirect(url_for('index'))

@app.route('/upload/<wallet_name>', methods=['POST'])
def upload_wallet(wallet_name):
    """Process uploaded SMS text for a specific wallet."""
    if wallet_name not in WALLET_TYPES:
        flash(f'محفظة غير معروفة: {wallet_name}', 'error')
        return redirect(url_for('index'))
    
    sms_text = request.form.get('sms_text', '')
    
    if not sms_text:
        flash('لم يتم توفير نص الرسائل', 'error')
        return redirect(url_for('wallet', wallet_name=wallet_name))
    
    # Add the wallet name to the beginning of each message if not already there
    lines = sms_text.split('\n')
    processed_lines = []
    
    for line in lines:
        if line.strip() and not line.startswith(f'From: {wallet_name}'):
            if not any(line.startswith(f'From: {w}') for w in WALLET_TYPES):
                processed_lines.append(f'From: {wallet_name} \n{line}')
            else:
                processed_lines.append(line)
        else:
            processed_lines.append(line)
    
    processed_sms = '\n'.join(processed_lines)
    
    transactions = parse_sms(processed_sms)
    
    if not transactions:
        flash('لم يتم العثور على معاملات صالحة في نص الرسائل', 'warning')
        return redirect(url_for('wallet', wallet_name=wallet_name))
    
    num_saved = save_transactions(transactions)
    flash(f'تمت معالجة {num_saved} معاملات بنجاح', 'success')
    
    return redirect(url_for('wallet', wallet_name=wallet_name))

@app.route('/clear', methods=['POST'])
def clear_data():
    """Clear all transaction data."""
    # Delete all transactions from the database
    Transaction.query.delete()
    db.session.commit()
    flash('All transaction data has been cleared', 'success')
    
    return redirect(url_for('index'))

@app.route('/clear/<wallet_name>', methods=['POST'])
def clear_wallet_data(wallet_name):
    """Clear transaction data for a specific wallet."""
    if wallet_name not in WALLET_TYPES:
        flash(f'محفظة غير معروفة: {wallet_name}', 'error')
        return redirect(url_for('index'))
    
    # Delete transactions for the specified wallet from the database
    transactions_to_delete = Transaction.query.filter_by(wallet=wallet_name).all()
    for transaction in transactions_to_delete:
        db.session.delete(transaction)
    db.session.commit()
    flash(f'تم مسح جميع بيانات معاملات محفظة {wallet_name}', 'success')
    
    return redirect(url_for('wallet', wallet_name=wallet_name))

@app.route('/export', methods=['GET'])
def export_data():
    """Export transaction data as JSON."""
    transactions = load_transactions()
    
    return jsonify(transactions)

@app.route('/forward-sms-setup')
def forward_sms_setup():
    """Render the Forward SMS setup guide page."""
    return render_template(
        'forward_sms_setup.html',
        now=datetime.now()
    )

@app.route('/api/receive-sms', methods=['POST', 'GET'])
def receive_sms():
    """Receive SMS from Forward SMS app."""
    print("=== RECEIVED REQUEST TO /api/receive-sms ===")
    print(f"Method: {request.method}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Form data: {request.form}")
    print(f"Args: {request.args}")
    
    if request.is_json:
        print(f"JSON data: {request.get_json()}")
    
    try:
        if request.method == 'POST':
            # Get SMS data from request
            sms_text = None
            sender = None
            
            # Try to get the formatted text from JSON (as shown in the screenshot)
            if request.is_json:
                data = request.get_json()
                print(f"Processing JSON data: {data}")
                
                if 'text' in data:
                    formatted_text = data.get('text', '')
                    print(f"Found formatted text: {formatted_text}")
                    
                    # The format should be "From: {sender}<br>{msg}"
                    if '<br>' in formatted_text:
                        parts = formatted_text.split('<br>', 1)
                        if len(parts) == 2 and parts[0].startswith('From:'):
                            sender = parts[0].replace('From:', '').strip()
                            sms_text = parts[1].strip()
                            print(f"Successfully parsed formatted text - Sender: '{sender}', Text: '{sms_text}'")
                        else:
                            print(f"Formatted text doesn't match expected format: {formatted_text}")
                    else:
                        print(f"No <br> found in formatted text: {formatted_text}")
            
            # If we couldn't extract from the formatted text, try other methods
            if not sms_text:
                # Check form data
                if request.form:
                    print(f"Processing form data: {request.form}")
                    sms_text = request.form.get('msg', '')
                    if not sms_text:
                        sms_text = request.form.get('text', '')
                    sender = request.form.get('sender', '')
                    
                    print(f"Extracted from form - Sender: '{sender}', Text: '{sms_text}'")
                
                # Check URL parameters
                if not sms_text:
                    sms_text = request.args.get('msg', '')
                    if not sms_text:
                        sms_text = request.args.get('text', '')
                    if not sender:
                        sender = request.args.get('sender', '')
                    
                    print(f"Extracted from URL params - Sender: '{sender}', Text: '{sms_text}'")
                
                # Check if data is in the request body but not parsed
                if not sms_text and request.data:
                    try:
                        # Try to parse as JSON
                        body_data = json.loads(request.data.decode('utf-8'))
                        print(f"Processing raw body data as JSON: {body_data}")
                        
                        if 'text' in body_data:
                            formatted_text = body_data.get('text', '')
                            if '<br>' in formatted_text:
                                parts = formatted_text.split('<br>', 1)
                                if len(parts) == 2 and parts[0].startswith('From:'):
                                    sender = parts[0].replace('From:', '').strip()
                                    sms_text = parts[1].strip()
                                    print(f"Successfully parsed formatted text from raw JSON - Sender: '{sender}', Text: '{sms_text}'")
                            else:
                                sms_text = body_data.get('msg', '')
                                sender = body_data.get('sender', '')
                                print(f"Extracted from raw JSON - Sender: '{sender}', Text: '{sms_text}'")
                    except Exception as e:
                        print(f"Error parsing request body: {e}")
            
            # Log final extracted data
            print(f"Final extracted data - Sender: '{sender}', Text: '{sms_text}'")
            
            if not sms_text:
                print("No SMS text found in request")
                return jsonify({
                    'status': 'error',
                    'message': 'No SMS text provided'
                }), 400
            
            # إذا كان sender لا يزال None، استخدم قيمة افتراضية
            if sender is None:
                sender = "Unknown"
                print(f"Using default sender: {sender}")
            
            # Format the SMS in the expected format
            formatted_sms = f"From: {sender} \n{sms_text}"
            print(f"Formatted SMS: {formatted_sms}")
            
            # Parse and save the SMS
            transactions = parse_sms(formatted_sms)
            print(f"Parsed transactions: {transactions}")
            
            if transactions:
                num_saved = save_transactions(transactions)
                print(f"Saved {num_saved} transactions")
                return jsonify({
                    'status': 'success',
                    'message': f'Successfully processed {num_saved} transactions',
                    'transactions': transactions
                }), 200
            else:
                print("No valid transactions found in the SMS")
                return jsonify({
                    'status': 'warning',
                    'message': 'No valid transactions found in the SMS'
                }), 200
        
        elif request.method == 'GET':
            # Handle GET request (for testing)
            sms_text = request.args.get('msg', '')
            if not sms_text:
                sms_text = request.args.get('text', '')
                
            sender = request.args.get('sender', '')
            
            if not sms_text:
                return jsonify({
                    'status': 'error',
                    'message': 'No SMS text provided'
                }), 400
            
            # إذا كان sender فارغًا، استخدم قيمة افتراضية
            if not sender:
                sender = "Unknown"
            
            # Format the SMS in the expected format
            formatted_sms = f"From: {sender} \n{sms_text}"
            
            # Parse and save the SMS
            transactions = parse_sms(formatted_sms)
            
            if transactions:
                num_saved = save_transactions(transactions)
                return jsonify({
                    'status': 'success',
                    'message': f'Successfully processed {num_saved} transactions',
                    'transactions': transactions
                }), 200
            else:
                return jsonify({
                    'status': 'warning',
                    'message': 'No valid transactions found in the SMS'
                }), 200
    except Exception as e:
        print(f"Error in receive_sms: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': f'Server error: {str(e)}'
        }), 500
    
    return jsonify({
        'status': 'error',
        'message': 'Invalid request'
    }), 400

def generate_wallet_charts(transactions, wallet_name):
    """Generate charts for a specific wallet's transaction visualization."""
    if not transactions:
        return {}
    
    df = pd.DataFrame(transactions)
    charts = {}
    
    # Ensure required columns exist
    required_columns = ['currency', 'type', 'amount']
    if not all(col in df.columns for col in required_columns):
        return charts
    
    # Transaction type distribution by currency for this wallet
    plt.figure(figsize=(10, 6))
    
    for currency in df['currency'].unique():
        currency_df = df[df['currency'] == currency]
        
        # Count transactions by type
        type_counts = currency_df['type'].value_counts()
        
        plt.bar(
            [f"{currency} - {t}" for t in type_counts.index],
            type_counts.values
        )
    
    plt.title(f'أنواع المعاملات حسب العملة - {wallet_name}')
    plt.xlabel('العملة - نوع المعاملة')
    plt.ylabel('عدد المعاملات')
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Save to BytesIO
    img_bytes = BytesIO()
    plt.savefig(img_bytes, format='png')
    img_bytes.seek(0)
    
    # Convert to base64 for embedding in HTML
    img_base64 = base64.b64encode(img_bytes.read()).decode('utf-8')
    charts['transaction_types'] = img_base64
    
    plt.close()
    
    # Amount distribution by currency and type for this wallet
    plt.figure(figsize=(10, 6))
    
    # Group by currency and type, sum amounts
    if len(df) > 0:
        grouped = df.groupby(['currency', 'type'])['amount'].sum().unstack()
        grouped.plot(kind='bar', ax=plt.gca())
        
        plt.title(f'مبالغ المعاملات حسب العملة والنوع - {wallet_name}')
        plt.xlabel('العملة')
        plt.ylabel('إجمالي المبلغ')
        plt.legend(title='نوع المعاملة')
        plt.tight_layout()
        
        # Save to BytesIO
        img_bytes = BytesIO()
        plt.savefig(img_bytes, format='png')
        img_bytes.seek(0)
        
        # Convert to base64 for embedding in HTML
        img_base64 = base64.b64encode(img_bytes.read()).decode('utf-8')
        charts['amount_distribution'] = img_base64
    
    plt.close()
    
    # Transaction timeline if we have timestamps
    if 'timestamp' in df.columns and len(df) > 0:
        plt.figure(figsize=(12, 6))
        
        # Convert timestamp to datetime if it's not already
        if df['timestamp'].dtype == 'object':
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Group by date and currency
        df['date'] = df['timestamp'].dt.date
        timeline = df.groupby(['date', 'currency', 'type'])['amount'].sum().unstack(level=[1, 2]).fillna(0)
        
        if not timeline.empty and timeline.shape[1] > 0:
            timeline.plot(kind='line', marker='o', ax=plt.gca())
            
            plt.title(f'تطور المعاملات عبر الزمن - {wallet_name}')
            plt.xlabel('التاريخ')
            plt.ylabel('المبلغ')
            plt.grid(True, linestyle='--', alpha=0.7)
            plt.tight_layout()
            
            # Save to BytesIO
            img_bytes = BytesIO()
            plt.savefig(img_bytes, format='png')
            img_bytes.seek(0)
            
            # Convert to base64 for embedding in HTML
            img_base64 = base64.b64encode(img_bytes.read()).decode('utf-8')
            charts['timeline'] = img_base64
        
        plt.close()
    
    return charts

if __name__ == '__main__':
    # Ensure the upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Get port from environment variable for Render compatibility
    port = int(os.environ.get('PORT', 5000))
    
    # Run the app with the specified port and host
    app.run(host='0.0.0.0', port=port, debug=True)
