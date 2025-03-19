import logging
from services.database_service import get_setting

logger = logging.getLogger(__name__)

# القيم الافتراضية للإعدادات
DEFAULT_VALUES = {
    'MIN_WITHDRAWAL_USD': 1.0,
    'MAX_WITHDRAWAL_USD': 10.0,
    'COMMISSION_RATE': 0.01
}

async def load_settings(bot_data: dict):
    """
    تحميل الإعدادات من قاعدة البيانات وتخزينها في bot_data.
    إذا لم يتم العثور على قيمة، يتم تعيين القيمة الافتراضية.
    """
    settings_keys = DEFAULT_VALUES.keys()

    for key in settings_keys:
        try:
            value = await get_setting(key)
            if value is not None:
                try:
                    # تحويل القيم إلى نوع البيانات المناسب
                    if key in ['MIN_WITHDRAWAL_USD', 'MAX_WITHDRAWAL_USD', 'COMMISSION_RATE']:
                        bot_data[key] = float(value)
                    else:
                        bot_data[key] = value
                    logger.info(f"✅ تم تحميل الإعداد {key}: {bot_data[key]}")
                except ValueError as e:
                    # التعامل مع القيم غير الصالحة
                    logger.warning(f"⚠️ قيمة غير صالحة للإعداد {key}: {value}. يتم استخدام القيمة الافتراضية.")
                    bot_data[key] = DEFAULT_VALUES[key]
            else:
                # في حالة عدم العثور على القيمة في قاعدة البيانات
                logger.warning(f"⚠️ الإعداد {key} غير موجود في قاعدة البيانات. يتم استخدام القيمة الافتراضية.")
                bot_data[key] = DEFAULT_VALUES[key]
        except Exception as e:
            # التعامل مع الأخطاء أثناء استرجاع الإعداد
            logger.error(f"❌ خطأ أثناء تحميل الإعداد {key}: {e}")
            bot_data[key] = DEFAULT_VALUES[key]
