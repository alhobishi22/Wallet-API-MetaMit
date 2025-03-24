# config/config.py

import os
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env
load_dotenv()

# Currency symbols
CURRENCY_SYMBOLS = {
    'YER': '﷼',
    'SAR': 'ر.س',
    'USD': '$'
}
NETWORK_ADDRESSES = {
    'TRC20': "TTjjmundES8xjiMEnUb8xsx7j9UskrkCMu",
    'BEP20': "0xc845b61927E077ECf98915713415472fbE8b18D9",
    'ARB20': "0xc845b61927E077ECf98915713415472fbE8b18D9"
}
# تعريف معدلات الصرف
EXCHANGE_RATES = {
    'YER': float(os.getenv('YER_RATE', '1')),   # ريال يمني
    'SAR': float(os.getenv('SAR_RATE', '1')),   # ريال سعودي
    'USD': float(os.getenv('USD_RATE', '1'))    # دولار أمريكي
}

# تكوين العملات الرقمية
DIGITAL_CURRENCIES = [
    {
        "id": 1,
        "name": "USDT",
        "symbol": "USDT",
        "networks": ["TRC20", "BEP20", "ARB20"],
        "is_default": True
    }
]

# تكوين العملات المتاحة
CURRENCIES = [
    {
        'code': 'YER',
        'name': '﷼ يمني 🇾🇪',
        'symbol': '﷼',
        'is_default': True
    },
    {
        'code': 'SAR',
        'name': ' ﷼ سعودي 🇸🇦',
        'symbol': 'ر.س'
    },
    {
        'code': 'USD',
        'name': ' أمريكي 🇺🇸',
        'symbol': '$'
    }
]

# إعدادات البوت
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("⚠️ متغير البيئة BOT_TOKEN مطلوب ولم يتم العثور عليه.")

# معرف مجموعة المشرفين
try:
    # استخدام القيمة كما هي بدون تحويلها إلى int لتجنب فقدان العلامة السالبة
    ADMIN_GROUP_ID = os.getenv('ADMIN_GROUP_ID', '0')
    if ADMIN_GROUP_ID == '0':
        raise ValueError("⚠️ متغير البيئة ADMIN_GROUP_ID مطلوب ولم يتم تعيينه بشكل صحيح.")
except Exception as e:
    raise ValueError(f"⚠️ ADMIN_GROUP_ID غير صالح: {e}")

# مفاتيح API الخاصة بـ Blockchain
TRONGRID_API_KEY = os.getenv('TRONGRID_API_KEY', '')
BSCSCAN_API_KEY = os.getenv('BSCSCAN_API_KEY', '')
ETHERSCAN_API_KEY = os.getenv('ETHERSCAN_API_KEY', '')
ARBISCAN_API_KEY = os.getenv('ARBISCAN_API_KEY', '')

# معلومات الشبكات المختلفة لـ USDT
NETWORK_INFO = {
    'TRC20': {
        'name': 'Tron Network (TRC20)',
        'min_amount': 1,
        'fee': '1 USDT',
        'confirmation_time': '3-5 minutes'
    },
    'BEP20': {
        'name': 'Binance Smart Chain (BEP20)',
        'min_amount': 1,
        'fee': '0.5-1 USDT',
        'confirmation_time': '5-10 minutes'
    },
    'ARB20': {
        'name': 'Arbitrum One (ARB20)',
        'min_amount': 1,
        'fee': '0.5-1 USDT',
        'confirmation_time': '5-10 minutes'
    }
}

# تعريف الحالات للمحادثات
class States:
    SELECT_LOCAL_CURRENCY = 'SELECT_LOCAL_CURRENCY'
    HANDLE_PENDING = 'HANDLE_PENDING'
    ENTER_REGISTRATION_CODE = 'ENTER_REGISTRATION_CODE'
    SELECT_TRANSFER_TYPE = 'SELECT_TRANSFER_TYPE'
    SELECT_CURRENCY = 'SELECT_CURRENCY'
    ENTER_RECIPIENT_NAME = 'ENTER_RECIPIENT_NAME'
    ENTER_RECIPIENT_NUMBER = 'ENTER_RECIPIENT_NUMBER'
    SELECT_WALLET = 'SELECT_WALLET'
    ENTER_ACCOUNT_NUMBER = 'ENTER_ACCOUNT_NUMBER'
    SELECT_DIGITAL_CURRENCY = 'SELECT_DIGITAL_CURRENCY'
    SELECT_USDT_NETWORK = 'SELECT_USDT_NETWORK'
    WAITING_DEPOSIT = 'WAITING_DEPOSIT'
    ENTER_AMOUNT = 'ENTER_AMOUNT'
    CONFIRM_TRANSFER = 'CONFIRM_TRANSFER'
    ENTER_TXID = 'ENTER_TXID'
    ENTER_REJECTION_REASON = 'ENTER_REJECTION_REASON'
    CONFIRM_RECIPIENT_INFO = 'CONFIRM_RECIPIENT_INFO'
    ENTER_RECIPIENT_NOTES = 'ENTER_RECIPIENT_NOTES'
    ENTER_TRANSFER_AGENCY = 'ENTER_TRANSFER_AGENCY'
    ADMIN_CHOICE = 'ADMIN_CHOICE'
    CANCEL = 'CANCEL'  # حالة جديدة للإلغاء

    # حالات الرجوع
    BACK_TO_NETWORKS = 'BACK_TO_NETWORKS'
    BACK_TO_TRANSFER_TYPE = 'BACK_TO_TRANSFER_TYPE'
    BACK_TO_WALLET_SELECTION = 'BACK_TO_WALLET_SELECTION'

    # حالات المشرف
    ADMIN_INITIAL = "ADMIN_INITIAL"  # حالة البداية للمشرف
    ENTER_TRANSFER_INFO = "ENTER_TRANSFER_INFO"  # إدخال معلومات التحويل
    ENTER_REJECTION_REASON = "ENTER_REJECTION_REASON"  # إدخال سبب الرفض
    SEND_TRANSFER_INFO = "SEND_TRANSFER_INFO"  # إرسال معلومات التحويل (صورة أو نص أو ملف)
    REVIEW_TRANSFER_INFO = "REVIEW_TRANSFER_INFO"  # مراجعة معلومات التحويل قبل إرسالها للعميل
# تكوين العمولة
COMMISSION_SETTINGS = {
    'fixed_fee_threshold': 20,  # المبلغ الحد الفاصل للعمولة الثابتة
    'fixed_fee_amount': 1,      # قيمة العمولة الثابتة للمبالغ الصغيرة
    'percentage_fee': 0.05,     # نسبة العمولة للمبالغ الكبيرة (5%)
    'min_withdrawal': 10,       # الحد الأدنى للسحب
    'max_withdrawal': 1000      # الحد الأعلى للسحب
}

# تكوين المحافظ المتاحة
WALLETS = [
    {"id": 1, "name": " جوالي", "is_highlighted": True},
    {"id": 2, "name": " كريمي", "is_highlighted": True},
    {"id": 4, "name": " كاش", "is_highlighted": True},
    {"id": 5, "name": "ون كاش", "is_highlighted": True},
    {"id": 6, "name": "   جيب", "is_highlighted": True}
]

# تكوين الشبكات المختلفة لـ USDT
USDT_NETWORKS = [
    {
        "id": 1,
        "name": "TRC20",
        "address": "TQQ4LmngvbGycHUCoWyfbdvSUHGo7ZuMA5"  # يجب استبدالها بعنوان محفظة TRC20 الصحيح
    },
    {
        "id": 2,
        "name": "BEP20",
        "address": "0xe8d8a9a5be744e853c45922b7731d588a6d2e5fa"  # مثال على عنوان محفظة BEP20
    },
    {
        "id": 3,
        "name": "ARB20",
        "address": "0xc845b61927E077ECf98915713415472fbE8b18D9"  # عنوان محفظة Arbitrum One الصحيح
    }
]
