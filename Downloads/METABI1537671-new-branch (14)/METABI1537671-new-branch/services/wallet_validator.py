import re
import logging
from web3 import Web3

logger = logging.getLogger(__name__)

class WalletValidator:
    def __init__(self):
        self.w3 = Web3()

    def validate_wallet_address(self, address: str, network: str) -> tuple[bool, str]:
        """التحقق من صحة عنوان المحفظة حسب الشبكة"""
        try:
            if not address:
                return False, "❌ عنوان المحفظة فارغ"

            # تنظيف العنوان من المسافات
            address = address.strip()

            if network in ['BSC', 'ETH', 'ARBITRUM', 'POLYGON', 'OPTIMISM', 'AVAX']:
                return self._validate_evm_address(address)
            elif network == 'TRX':
                return self._validate_tron_address(address)
            elif network == 'SOL':
                return self._validate_solana_address(address)
            elif network == 'APTOS':
                return self._validate_aptos_address(address)
            else:
                return False, "❌ شبكة غير مدعومة"

        except Exception as e:
            logger.error(f"خطأ في التحقق من عنوان المحفظة: {e}")
            return False, "❌ حدث خطأ في التحقق من العنوان"

    def _validate_evm_address(self, address: str) -> tuple[bool, str]:
        """التحقق من صحة عنوان EVM (Ethereum, BSC, etc.)"""
        try:
            # التحقق من طول العنوان والبادئة
            if not address.startswith('0x'):
                return False, "❌ يجب أن يبدأ العنوان بـ '0x'"

            if len(address) != 42:
                return False, "❌ طول العنوان غير صحيح"

            # التحقق من صحة التشفير
            if not self.w3.is_address(address):
                return False, "❌ عنوان غير صالح"

            # التحقق من checksum
            checksum_address = self.w3.to_checksum_address(address)
            if address != checksum_address:
                logger.warning(f"عنوان غير مطابق للـ checksum: {address}")
                # نقبل العنوان لكن نسجل تحذير

            return True, "✅ عنوان صالح"

        except Exception as e:
            logger.error(f"خطأ في التحقق من عنوان EVM: {e}")
            return False, "❌ عنوان غير صالح"

    def _validate_tron_address(self, address: str) -> tuple[bool, str]:
        """التحقق من صحة عنوان Tron"""
        try:
            # التحقق من البادئة
            if not address.startswith('T'):
                return False, "❌ يجب أن يبدأ عنوان Tron بحرف 'T'"

            # التحقق من الطول
            if len(address) != 34:
                return False, "❌ طول عنوان Tron غير صحيح"

            # التحقق من الأحرف المسموحة
            tron_pattern = re.compile(r'^[123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{34}$')
            if not tron_pattern.match(address):
                return False, "❌ عنوان Tron يحتوي على أحرف غير صالحة"

            return True, "✅ عنوان Tron صالح"

        except Exception as e:
            logger.error(f"خطأ في التحقق من عنوان Tron: {e}")
            return False, "❌ عنوان Tron غير صالح"

    def _validate_solana_address(self, address: str) -> tuple[bool, str]:
        """التحقق من صحة عنوان Solana"""
        try:
            # التحقق من الطول
            if len(address) != 44 and len(address) != 32:
                return False, "❌ طول عنوان Solana غير صحيح"

            # التحقق من الأحرف المسموحة
            solana_pattern = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
            if not solana_pattern.match(address):
                return False, "❌ عنوان Solana يحتوي على أحرف غير صالحة"

            return True, "✅ عنوان Solana صالح"

        except Exception as e:
            logger.error(f"خطأ في التحقق من عنوان Solana: {e}")
            return False, "❌ عنوان Solana غير صالح"

    def _validate_aptos_address(self, address: str) -> tuple[bool, str]:
        """التحقق من صحة عنوان Aptos"""
        try:
            # التحقق من البادئة
            if not address.startswith('0x'):
                return False, "❌ يجب أن يبدأ عنوان Aptos بـ '0x'"
                
            # إزالة البادئة 0x للتحقق من الطول
            stripped_address = address[2:]
            
            # التحقق من الطول (64 حرف بعد إزالة 0x)
            if len(stripped_address) != 64:
                return False, "❌ طول عنوان Aptos غير صحيح. يجب أن يكون 64 حرف بعد 0x"

            # التحقق من الأحرف المسموحة (أرقام ستة عشرية)
            aptos_pattern = re.compile(r'^[0-9a-fA-F]{64}$')
            if not aptos_pattern.match(stripped_address):
                return False, "❌ عنوان Aptos يحتوي على أحرف غير صالحة"

            return True, "✅ عنوان Aptos صالح"

        except Exception as e:
            logger.error(f"خطأ في التحقق من عنوان Aptos: {e}")
            return False, "❌ عنوان Aptos غير صالح"

# إنشاء نسخة واحدة من الخدمة
wallet_validator = WalletValidator()