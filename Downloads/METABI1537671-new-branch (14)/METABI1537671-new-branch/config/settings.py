# config/settings.py

# حدود السحب لكل عملة مشفرة (اختياري)
WITHDRAWAL_LIMITS = {
    'USDT': {
        'min': 1.0,      # الحد الأدنى للسحب بـ USDT
        'max': 1000.0    # الحد الأقصى للسحب بـ USDT
    },
}


# تعريف أسباب الرفض
REJECTION_REASONS = [
    "رقم الحواله غير صحيح ",
    "المبلغ غير مطابق",
    "اسم المرسل غير مطابق",
    "مشاكل تقنية",
    " خارج اوقات الدوام "
]
CANCELLATION_REASONS = [
     "رقم الحواله غير صحيح ",
    "المبلغ غير مطابق",
    "اسم المرسل غير مطابق",
    "مشاكل تقنية",
    " خارج اوقات الدوام "
]

# config/settings.py
from dotenv import load_dotenv
import os

load_dotenv()  # تحميل المتغيرات من ملف .env

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_USER_IDS  = [6648998922,5125982771,2092304651,5206010877,7848238766] 
 # استبدلها بأرقام معرفات المشرفين الفعلية

# إعدادات قاعدة البيانات
import os
from dotenv import load_dotenv


DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")



# تكوين رابط الاتصال
DATABASE_URL = os.getenv('DATABASE_URL', 
    f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_NAME}'
)
SUPPORTED_CRYPTOCURRENCIES = ['USDT']  # أضف العملات المدعومة
SUPPORTED_NETWORKS = {
    'USDT': {
        'TRX': 'Tron (TRC20)',
        'BSC': 'BNB Smart Chain (BEP20)',
        'ETH': 'Ethereum (ERC20)',
        'ARBITRUM': 'Arbitrum One',
        'AVAX': 'Avalanche C-Chain',
        'POLYGON': 'Polygon',
        'SOL': 'Solana',
        'OPTIMISM': 'Optimism',
        'APTOS': 'Aptos'
    },
    # أضف الشبكات للعملات الأخرى
}
EXCHANGE_RATES = {
    'USD': 1.0,
    'SAR': 3.83,
    'YAR': 540,

    # أضف العملات المحلية الأخرى
}
LOCAL_CURRENCIES = {
    'YER': 'ريال يمني 🇾🇪',
    'SAR': 'ريال سعودي🇸🇦',
    'USD': 'دولار أمريكي 🇺🇸'
    

    # أضف العملات المحلية الأخرى
}
WITHDRAWAL_LIMITS = {
    'USDT': {'min': 1, 'max': 10000},
    # أضف الحدود للعملات الأخرى
}
COMMISSION_RATE = 0.01  # نسبة العمولة
ADMIN_GROUP_ID = -1002410603066  # قروب المشرفين للتحويل عبر الاسم
ADMIN_GROUP_ID_2 = -4764569911  # قروب المشرفين للإيداع البنكي
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')

# حدود السحب العامة
MIN_WITHDRAWAL_AMOUNT = 1.0  # الحد الأدنى للسحب بالعملة المحلية (مثلاً، ريال يمني)
MAX_WITHDRAWAL_AMOUNT = 10.0  # الحد الأقصى للسحب بالعملة المحلية
