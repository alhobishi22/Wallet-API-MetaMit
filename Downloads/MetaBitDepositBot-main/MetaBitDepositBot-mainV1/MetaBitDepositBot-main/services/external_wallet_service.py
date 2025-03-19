import asyncio
import logging
import os
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account
from eth_utils import to_checksum_address

logger = logging.getLogger(__name__)

class ExternalWalletService:
    def __init__(self):
        """
        مسؤول عن التعامل مع المحفظة الخارجية على شبكة BSC.
        يقوم بتهيئة الاتصال بـ web3، ضبط عقد USDT، وغيرها.
        """
        load_dotenv()
        
        # تحميل القيم من ملف env:
        self.private_key = os.getenv('WALLET_PRIVATE_KEY')
        self.bsc_rpc = os.getenv('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/')
        self.usdt_contract = os.getenv('BSC_USDT_CONTRACT')
        
        # إضافة قفل للترامن وتتبع الـ nonce
        self._nonce_lock = asyncio.Lock()
        self._last_known_nonce: Optional[int] = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        
        if not self.private_key or not self.usdt_contract:
            logger.error("المفتاح الخاص أو عنوان العقد غير متوفر في متغيرات البيئة")
            raise ValueError("المفتاح الخاص أو عنوان العقد غير متوفر")
        
        try:
            # تهيئة الاتصال بشبكة BSC
            self.w3 = Web3(Web3.HTTPProvider(self.bsc_rpc))
            if not self.w3.is_connected():
                raise Exception("فشل الاتصال بشبكة BSC")
            
            # إنشاء حساب من خلال المفتاح الخاص
            self.account = Account.from_key(self.private_key)
            
            # تعريف واجهة العقد (ABI) وتكوين العقد الذكي لعملة USDT
            self.contract = self.w3.eth.contract(
                address=self.usdt_contract,
                abi=[
                    {
                        "constant": False,
                        "inputs": [
                            {"name": "_to", "type": "address"},
                            {"name": "_value", "type": "uint256"}
                        ],
                        "name": "transfer",
                        "outputs": [{"name": "", "type": "bool"}],
                        "type": "function"
                    },
                    {
                        "constant": True,
                        "inputs": [{"name": "_owner", "type": "address"}],
                        "name": "balanceOf",
                        "outputs": [{"name": "balance", "type": "uint256"}],
                        "type": "function"
                    }
                ]
            )
            
            logger.info(f"تم تهيئة المحفظة بنجاح. عنوان المحفظة: {self.account.address}")
        
        except Exception as e:
            logger.error(f"خطأ في تهيئة المحفظة الخارجية: {e}")
            raise

    async def _get_next_nonce(self) -> int:
        """
        الحصول على الـ nonce التالي بشكل آمن ومترامن
        """
        async with self._nonce_lock:
            if self._last_known_nonce is not None:
                next_nonce = self._last_known_nonce + 1
            else:
                pending_nonce = await self._run_in_executor(
                    self.w3.eth.get_transaction_count,
                    self.account.address,
                    'pending'
                )
                latest_nonce = await self._run_in_executor(
                    self.w3.eth.get_transaction_count,
                    self.account.address,
                    'latest'
                )
                next_nonce = max(pending_nonce, latest_nonce)
            
            self._last_known_nonce = next_nonce
            return next_nonce

    async def _run_in_executor(self, func, *args):
        """
        تنفيذ العمليات المتزامنة في خيط منفصل
        """
        return await asyncio.get_event_loop().run_in_executor(
            self._executor, func, *args
        )

    async def check_balance(self, amount: float) -> bool:
        """
        التحقق من توفر الرصيد الكافي في المحفظة قبل إرسال أي مبلغ.
        """
        try:
            amount_wei = int(amount * 10**18)
            balance = await self._run_in_executor(
                self.contract.functions.balanceOf(self.account.address).call
            )
            logger.info(f"الرصيد الحالي: {balance / 10**18} USDT")
            return balance >= amount_wei
        
        except Exception as e:
            logger.error(f"خطأ في التحقق من الرصيد: {e}")
            return False

    async def withdraw(self, address: str, amount: float) -> dict:
        """
        تنفيذ عملية إرسال USDT من المحفظة الأساسية إلى عنوان آخر على شبكة BSC (BEP20).
        """
        max_retries = 3
        base_delay = 2  # ثانيتان
        
        for retry in range(max_retries):
            try:
                # 1) تنظيف وتحقق من العنوان
                clean_address = address.strip()
                if not clean_address.startswith("0x") or len(clean_address) != 42:
                    raise ValueError("عنوان المحفظة غير صالح (تنسيق أو طول غير صحيح).")
                
                checksum_address = to_checksum_address(clean_address.lower())

                # 2) تحويل المبلغ إلى Wei
                amount_wei = int(amount * 10**18)

                # 3) التحقق من الرصيد
                balance = await self._run_in_executor(
                    self.contract.functions.balanceOf(self.account.address).call
                )
                
                if balance < amount_wei:
                    raise ValueError(f"الرصيد غير كافٍ. المتوفر: {balance / 10**18} USDT.")

                # 4) تحضير المعاملة مع nonce آمن
                nonce = await self._get_next_nonce()
                
                gas_price = await self._run_in_executor(
                    lambda: self.w3.eth.gas_price
                )

                # تقدير الغاز
                gas_estimate = await self._run_in_executor(
                    lambda: self.contract.functions.transfer(
                        checksum_address, 
                        amount_wei
                    ).estimate_gas({'from': self.account.address})
                )

                # بناء المعاملة
                transaction = self.contract.functions.transfer(
                    checksum_address,
                    amount_wei
                ).build_transaction({
                    'chainId': 56,
                    'gas': gas_estimate,  # استخدام القيمة المقدرة مباشرة
                    'gasPrice': gas_price,
                    'nonce': nonce,
                })

                # 5) توقيع وإرسال المعاملة
                signed_txn = self.w3.eth.account.sign_transaction(
                    transaction, 
                    self.private_key
                )
                
                tx_hash = await self._run_in_executor(
                    self.w3.eth.send_raw_transaction,
                    signed_txn.rawTransaction
                )

                # 6) انتظار تأكيد المعاملة مع timeout متزايد
                timeout = 60 * (retry + 1)  # زيادة مهلة الانتظار مع كل محاولة
                # Wait for transaction receipt directly since timeout is needed
                receipt = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
                )

                if receipt['status'] == 1:
                    return {
                        'txId': receipt['transactionHash'].hex(),
                        'status': 'completed',
                        'amount': amount,
                        'address': checksum_address,
                        'network': 'BSC',
                        'gas_used': receipt['gasUsed'],
                        'block_number': receipt['blockNumber']
                    }
                else:
                    raise Exception("فشلت المعاملة (status = 0)")

            except Exception as e:
                error_msg = str(e).lower()
                
                if retry < max_retries - 1:
                    if 'nonce too low' in error_msg:
                        # إعادة ضبط الـ nonce المخزن
                        self._last_known_nonce = None
                        delay = base_delay * (2 ** retry)
                        logger.warning(f"خطأ في nonce. انتظار {delay} ثوان قبل المحاولة {retry + 2}/{max_retries}")
                        await asyncio.sleep(delay)
                        continue
                    elif 'replacement transaction underpriced' in error_msg:
                        # زيادة سعر الغاز في المحاولة التالية
                        gas_price = int(gas_price * 1.1)  # زيادة بنسبة 10% فقط
                        continue
                
                logger.error(f"خطأ في تنفيذ السحب: {e}")
                raise

        raise Exception(f"فشلت جميع محاولات إرسال المعاملة بعد {max_retries} محاولات")

    async def close(self):
        """
        تنظيف الموارد عند إغلاق الخدمة
        """
        self._executor.shutdown(wait=True)

# إنشاء نسخة واحدة من الخدمة
external_wallet_service = ExternalWalletService()