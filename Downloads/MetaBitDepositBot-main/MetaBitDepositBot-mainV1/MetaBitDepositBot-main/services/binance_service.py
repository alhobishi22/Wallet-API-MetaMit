# services/binance_service.py

import logging
import time
import asyncio
import backoff
from binance.client import Client
from binance.exceptions import BinanceAPIException
from requests.exceptions import ConnectionError
from urllib3.exceptions import ProtocolError
from config.settings import BINANCE_API_KEY, BINANCE_API_SECRET

logger = logging.getLogger(__name__)

class BinanceService:
    def __init__(self):
        self.client = None
        self.time_offset = 0
        self.initialized = False
        self.test_mode = False

    async def get_withdrawal_status_with_tx(self, withdrawal_id: str, max_retries: int = 10, delay: int = 2) -> dict:
        """الحصول على حالة السحب مع رقم المعاملة"""
        for attempt in range(max_retries):
            try:
                # جلب معلومات السحب
                withdrawal_info = await asyncio.to_thread(
                    self.client.get_withdraw_history
                )
                
                # البحث عن السحب المحدد
                for withdrawal in withdrawal_info:
                    if withdrawal.get('id') == withdrawal_id:
                        tx_id = withdrawal.get('txId')
                        if tx_id:
                            logger.info(f"تم العثور على رقم المعاملة: {tx_id} للسحب {withdrawal_id}")
                            return {
                                'id': withdrawal_id,
                                'txId': tx_id,
                                'status': withdrawal.get('status'),
                                'amount': withdrawal.get('amount'),
                                'address': withdrawal.get('address'),
                                'coin': withdrawal.get('coin'),
                                'network': withdrawal.get('network')
                            }
                
                logger.info(f"محاولة {attempt + 1}/{max_retries}: لم يتم العثور على رقم المعاملة بعد")
                await asyncio.sleep(delay)
                
            except Exception as e:
                logger.error(f"خطأ في الحصول على معلومات السحب: {e}")
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(delay)
        
        raise Exception("لم يتم العثور على رقم المعاملة بعد المحاولات المحددة")

    async def check_withdrawal_status(self, transaction_id: str) -> str:
        """
        التحقق من حالة عملية السحب
        
        Args:
            transaction_id (str): معرف المعاملة
                
        Returns:
            str: حالة المعاملة ('completed', 'pending', 'failed')
        """
        try:
            # في وضع الاختبار
            if self.test_mode:
                logger.info(f"وضع الاختبار: التحقق من حالة السحب {transaction_id}")
                return 'completed'

            # محاولة الحصول على معلومات السحب
            withdrawal_info = await self.get_withdrawal_status_with_tx(transaction_id)
            
            if not withdrawal_info:
                logger.warning(f"لم يتم العثور على معلومات للسحب {transaction_id}")
                return 'pending'

            # تحويل حالات Binance إلى حالاتنا
            status = str(withdrawal_info.get('status', '')).lower()
            
            if status in ['6', 'success', 'completed']:
                return 'completed'
            elif status in ['1', '3', '5', 'failed', 'rejected']:
                return 'failed'
            else:  # ['0', '2', '4', 'pending', 'processing']
                return 'pending'

        except Exception as e:
            logger.error(f"خطأ في التحقق من حالة السحب: {str(e)}")
            return 'pending'  # نفترض أنها معلقة في حالة الخطأ

    async def initialize(self):
        """تهيئة خدمة Binance"""
        try:
            if not (BINANCE_API_KEY and BINANCE_API_SECRET):
                logger.warning("مفاتيح API غير متوفرة! سيتم تشغيل الخدمة في وضع الاختبار.")
                self.test_mode = True
                self.initialized = True
                return

            logger.info("تهيئة خدمة Binance باستخدام مفاتيح API...")
            self.client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

            # التحقق من الاتصال بـ Binance API
            try:
                server_time = await asyncio.to_thread(self.client.get_server_time)
                self.time_offset = server_time['serverTime'] - int(time.time() * 1000)
                self.client.timestamp_offset = self.time_offset
                logger.info("تم الاتصال بنجاح بـ Binance API")
            except BinanceAPIException as e:
                logger.error(f"خطأ في Binance API أثناء التحقق من الاتصال: {e}")
                self.test_mode = True
                self.initialized = True
                return
            except Exception as e:
                logger.error(f"خطأ غير متوقع أثناء التحقق من الاتصال بـ Binance API: {e}")
                self.test_mode = True
                self.initialized = True
                return

            # التحقق من صلاحيات السحب
            try:
                account_info = await asyncio.to_thread(self.client.get_account)
                self.test_mode = False
                logger.info("تم التحقق من صلاحيات السحب - التشغيل في الوضع الحقيقي.")
            except Exception as e:
                logger.warning(f"خطأ أثناء جلب معلومات الحساب: {e} - سيتم تشغيل الخدمة في وضع الاختبار.")
                self.test_mode = True

            self.initialized = True

        except Exception as e:
            logger.error(f"خطأ أثناء تهيئة خدمة Binance: {e}")
            self.test_mode = True
            self.initialized = True

        finally:
            mode = "اختبار" if self.test_mode else "حقيقي"
            logger.info(f"تم تهيئة خدمة Binance في وضع {mode}.")

    def _get_timestamp(self):
        """الحصول على الوقت المزامن"""
        return int(time.time() * 1000) + self.time_offset

    async def check_api_connection(self):
        """التحقق من الاتصال بـ API"""
        try:
            server_time = await asyncio.to_thread(self.client.get_server_time)
            logger.info(f"تم التحقق من الاتصال بـ Binance API: {server_time}")
            return server_time
        except Exception as e:
            logger.error(f"فشل التحقق من الاتصال بـ Binance API: {e}")
            raise

    @backoff.on_exception(
        backoff.expo,
        (ConnectionError, ProtocolError, BinanceAPIException),
        max_tries=3,
        max_time=30
    )
    async def check_balance(self, coin: str, amount: float) -> bool:
        """التحقق من توفر الرصيد"""
        logger.info(f"التحقق من الرصيد لـ {amount} {coin}")
        if self.test_mode:
            logger.info("وضع الاختبار: سيتم إرجاع True دائماً.")
            return True

        try:
            balance = await asyncio.to_thread(self.client.get_asset_balance, asset=coin)
            if balance and float(balance['free']) >= amount:
                logger.info(f"الرصيد كافٍ: {balance['free']} {coin} متاح.")
                return True
            else:
                logger.warning(f"الرصيد غير كافٍ: {balance['free']} {coin} متاح.")
                return False
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من الرصيد لـ {coin}: {e}")
            return False

    @backoff.on_exception(
        backoff.expo,
        (ConnectionError, ProtocolError, BinanceAPIException),
        max_tries=3,
        max_time=30
    )
    async def withdraw(self, coin: str, address: str, amount: float, network: str = None) -> dict:
        """تنفيذ عملية السحب"""
        if not self.initialized:
            raise Exception("خدمة Binance غير مهيأة")

        try:
            if self.test_mode:
                logger.warning("وضع الاختبار: تنفيذ سحب وهمي")
                return {
                    'id': f"TEST_WD_{int(time.time())}",
                    'txId': f"TEST_TX_{int(time.time())}",  # إضافة txId
                    'status': 'completed',
                    'amount': amount,
                    'address': address,
                    'coin': coin,
                    'network': network,
                    'test_mode': True
                }

            # التحقق من الاتصال والرصيد
            await self.check_api_connection()
            if not await self.check_balance(coin, amount):
                raise Exception(f"الرصيد غير كافٍ لـ {amount} {coin}")

            # تقريب المبلغ إلى 6 أرقام عشرية (مضاعف لـ 0.000001) وتحويله إلى سلسلة نصية
            formatted_amount = "{:.6f}".format(float(amount))
            logger.info(f"المبلغ المنسق للسحب: {formatted_amount} {coin}")
            
            # تنفيذ السحب
            try:
                withdrawal = await asyncio.to_thread(
                    self.client.withdraw,
                    coin=coin,
                    address=address,
                    amount=formatted_amount,
                    network=network
                )
                logger.info(f"تم إرسال طلب السحب بنجاح: {withdrawal}")
            except Exception as e:
                logger.error(f"خطأ في تنفيذ السحب - المبلغ: {formatted_amount}, العملة: {coin}, الشبكة: {network}")
                logger.error(f"تفاصيل الخطأ: {str(e)}")
                raise

            logger.info(f"تم إرسال طلب السحب: {withdrawal}")

            # التحقق من حالة السحب والانتظار حتى يتم تأكيد خصم المبلغ
            max_attempts = 20  # زيادة عدد المحاولات
            initial_delay = 3  # تأخير أولي
            
            for attempt in range(max_attempts):
                try:
                    withdrawal_history = await asyncio.to_thread(
                        self.client.get_withdraw_history
                    )
                    
                    for withdraw_info in withdrawal_history:
                        if withdraw_info.get('id') == withdrawal['id']:
                            # التحقق من خصم المبلغ أو وجود txId
                            if (withdraw_info.get('txId') or 
                                withdraw_info.get('transfered') or 
                                str(withdraw_info.get('status')).lower() in ['6', 'success', 'completed']):
                                
                                return {
                                    'id': withdrawal['id'],
                                    'txId': withdraw_info.get('txId', 'PROCESSING'),
                                    'status': withdraw_info.get('status'),
                                    'amount': amount,
                                    'address': address,
                                    'coin': coin,
                                    'network': network
                                }
                            
                            # إذا كان هناك حالة فشل واضحة
                            if str(withdraw_info.get('status')).lower() in ['1', '3', '5', 'failed', 'rejected']:
                                raise Exception(f"فشل السحب: {withdraw_info.get('status')}")
                    
                    # حساب التأخير التصاعدي
                    delay = initial_delay * (2 ** attempt)
                    logger.info(f"محاولة {attempt + 1}/{max_attempts}: في انتظار تأكيد السحب... ({delay}s)")
                    await asyncio.sleep(delay)
                
                except BinanceAPIException as e:
                    logger.warning(f"خطأ أثناء التحقق من حالة السحب: {e}")
                    await asyncio.sleep(initial_delay)
                    continue

            # إذا لم نحصل على تأكيد بعد كل المحاولات
            # نرجع معلومات السحب الأولية مع حالة 'processing'
            return {
                **withdrawal,
                'status': 'processing',
                'message': 'جاري معالجة السحب. قد يستغرق ذلك بعض الوقت.'
            }

        except Exception as e:
            logger.error(f"خطأ أثناء تنفيذ السحب: {e}")
            raise

    async def get_transaction_status(self, txid: str) -> dict:
        """التحقق من حالة المعاملة"""
        if self.test_mode:
            return {'status': 'completed', 'test_mode': True}

        try:
            # البحث في تاريخ السحوبات عن طريق txId
            withdrawal_history = await asyncio.to_thread(self.client.get_withdraw_history)
            for withdraw_info in withdrawal_history:
                if withdraw_info.get('txId') == txid:
                    logger.info(f"حالة المعاملة لـ {txid}: {withdraw_info['status']}")
                    return withdraw_info
            logger.warning(f"لم يتم العثور على المعاملة {txid} في تاريخ السحب.")
            return {'status': 'not_found'}
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من حالة المعاملة لـ {txid}: {e}")
            return {'status': 'error', 'message': str(e)}

    async def get_withdrawal_info(self, withdrawal_id: str) -> dict:
        """الحصول على معلومات السحب"""
        if self.test_mode:
            return {
                'id': withdrawal_id,
                'txId': f"TX_{withdrawal_id}",
                'status': 'completed',
                'amount': 0.0,
                'address': 'test_address',
                'coin': 'TEST',
                'network': 'TEST_NETWORK',
                'timestamp': self._get_timestamp(),
                'test_mode': True
            }

        try:
            withdrawal_history = await asyncio.to_thread(self.client.get_withdraw_history)
            for withdrawal in withdrawal_history:
                if withdrawal.get('id') == withdrawal_id:
                    logger.info(f"معلومات السحب لـ {withdrawal_id}: {withdrawal}")
                    return withdrawal
            logger.warning(f"لم يتم العثور على السحب {withdrawal_id} في تاريخ السحب.")
            return {'status': 'not_found'}
        except Exception as e:
            logger.error(f"خطأ أثناء الحصول على معلومات السحب لـ {withdrawal_id}: {e}")
            return {'status': 'error', 'message': str(e)}

    async def verify_withdrawal(self, txid: str) -> bool:
        """التحقق من اكتمال السحب"""
        try:
            status_info = await self.get_transaction_status(txid)
            return str(status_info.get('status', '')).lower() in ['6', 'success', 'completed']
        except Exception as e:
            logger.error(f"خطأ أثناء التحقق من السحب: {e}")
            return False

    async def close(self):
        """إغلاق الجلسات وتنظيف الموارد"""
        if self.client:
            await asyncio.to_thread(self.client.close_connection)
            logger.info("تم إغلاق اتصال Binance API")

# إنشاء نسخة واحدة من الخدمة
binance_service = BinanceService()
