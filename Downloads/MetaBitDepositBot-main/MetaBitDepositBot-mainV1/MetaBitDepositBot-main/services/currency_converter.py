# services/currency_converter.py

from config.settings import EXCHANGE_RATES
import logging

logger = logging.getLogger(__name__)

class CurrencyConverter:
    @staticmethod
    def convert_to_usdt(amount: float, from_currency: str) -> float:
        """تحويل من العملة المحلية إلى USDT"""
        try:
            if from_currency not in EXCHANGE_RATES:
                raise ValueError(f"العملة غير مدعومة: {from_currency}")
            
            rate = EXCHANGE_RATES[from_currency]
            usdt_amount = amount / rate
            return round(usdt_amount, 6)
        except Exception as e:
            logger.error(f"خطأ في تحويل العملة: {e}")
            raise

    @staticmethod
    def convert_from_usdt(amount: float, to_currency: str) -> float:
        """تحويل من USDT إلى العملة المحلية"""
        try:
            if to_currency not in EXCHANGE_RATES:
                raise ValueError(f"العملة غير مدعومة: {to_currency}")
            
            rate = EXCHANGE_RATES[to_currency]
            local_amount = amount * rate
            return round(local_amount, 2)
        except Exception as e:
            logger.error(f"خطأ في تحويل العملة: {e}")
            raise

currency_converter = CurrencyConverter()
