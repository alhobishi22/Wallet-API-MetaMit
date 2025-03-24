from dotenv import load_dotenv
import os
import logging
import hmac
import hashlib
import aiohttp
import asyncio
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Tuple
import time
import urllib.parse

load_dotenv()
logger = logging.getLogger(__name__)

class BinanceVerifier:
    def __init__(self):
        # التحقق من المتغيرات البيئية المطلوبة
        self.api_key = os.getenv('BINANCE_API_KEY')
        if not self.api_key:
            raise ValueError("BINANCE_API_KEY environment variable is required")

        self.api_secret = os.getenv('BINANCE_API_SECRET')
        if not self.api_secret:
            raise ValueError("BINANCE_API_SECRET environment variable is required")

        self.bsc_api_key = os.getenv('BSCSCAN_API_KEY')
        if not self.bsc_api_key:
            raise ValueError("BSCSCAN_API_KEY environment variable is required")

        self.base_url = 'https://api.binance.com'
        self.bsc_url = 'https://api.bscscan.com/api'
        self.usdt_contract = '0x55d398326f99059fF775485246999027B3197955'
        
        # Rate limiting settings
        self.last_api_call = 0
        self.min_call_interval = 0.1  # 100ms between calls
        self.max_retries = 3
        
        # Cache settings
        self._cache = {}

    async def _wait_for_rate_limit(self):
        """التحكم في معدل الطلبات"""
        now = time.time()
        time_since_last_call = now - self.last_api_call
        if time_since_last_call < self.min_call_interval:
            await asyncio.sleep(self.min_call_interval - time_since_last_call)
        self.last_api_call = time.time()

    def _get_cache_key(self, method: str, params: dict) -> str:
        """إنشاء مفتاح للتخزين المؤقت"""
        return f"{method}:{str(sorted(params.items()))}"

    def _get_from_cache(self, cache_key: str) -> Optional[Dict]:
        """استرجاع البيانات من التخزين المؤقت"""
        if cache_key in self._cache:
            data, timestamp = self._cache[cache_key]
            if time.time() - timestamp < 300:  # صالح لمدة 5 دقائق
                return data
            del self._cache[cache_key]
        return None

    def _add_to_cache(self, cache_key: str, data: Dict):
        """إضافة البيانات إلى التخزين المؤقت"""
        self._cache[cache_key] = (data, time.time())

    async def _get_server_time(self) -> int:
        """الحصول على وقت الخادم مع التخزين المؤقت"""
        cache_key = self._get_cache_key('server_time', {})
        cached_data = self._get_from_cache(cache_key)
        if cached_data:
            return cached_data

        await self._wait_for_rate_limit()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/v3/time") as response:
                    if response.status == 200:
                        data = await response.json()
                        server_time = int(data['serverTime'])
                        self._add_to_cache(cache_key, server_time)
                        return server_time
                    else:
                        logger.error(f"Failed to get server time: {response.status}")
        except Exception as e:
            logger.error(f"Error getting server time: {e}")
        
        # Fallback to local time
        return int(time.time() * 1000)

    def _generate_signature(self, params: dict) -> Tuple[str, str]:
        # تحويل جميع القيم إلى سلاسل نصية
        params = {k: str(v) for k, v in params.items()}
        query_string = urllib.parse.urlencode(sorted(params.items()))
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # تسجيل معلومات التصحيح
        logger.debug(f"Query String: {query_string}")
        logger.debug(f"Signature: {signature}")

        return signature, query_string

    def _verify_amount_and_time(
        self,
        amount: Decimal,
        timestamp: datetime,
        expected_amount: Decimal,
        deposit_time: datetime
    ) -> bool:
        amount_matches = amount == expected_amount
        time_diff = abs((timestamp - deposit_time).total_seconds() / 60)
        time_matches = time_diff <= 60  # زيادة الفترة الزمنية إلى 60 دقيقة

        logger.info(f"المبلغ المتوقع: {expected_amount}, المبلغ الفعلي: {amount}, متطابق: {amount_matches}")
        logger.info(f"وقت الإيداع المتوقع: {deposit_time}, وقت المعاملة: {timestamp}")
        logger.info(f"فارق الوقت: {time_diff} دقائق, ضمن الحد المسموح: {time_matches}")

        if not amount_matches:
            logger.warning(f"رفض المعاملة - المبلغ غير متطابق: متوقع {expected_amount}, فعلي {amount}")
        if not time_matches:
            logger.warning(f"رفض المعاملة - تجاوز الوقت المسموح: {time_diff} دقائق")

        return amount_matches and time_matches

    async def verify_transaction(
        self,
        tx_input: str,
        expected_amount: Decimal,
        deposit_time: datetime
    ) -> Optional[Dict]:
        logger.info(f"التحقق من المعاملة: {tx_input}")
        logger.info(f"المبلغ المتوقع: {expected_amount} USDT")
        logger.info(f"وقت الإيداع: {deposit_time}")

        if 'off-chain' in tx_input.lower():
            transfer_id = re.search(r'\d+', tx_input)
            if transfer_id:
                result = await self._verify_binance_pay_transaction(
                    transfer_id.group(),
                    expected_amount,
                    deposit_time
                )
                if result:
                    return result
                else:
                    return await self._verify_offchain_transfer(
                        transfer_id.group(),
                        expected_amount,
                        deposit_time
                    )
        elif tx_input.strip().isdigit():
            return await self._verify_internal_transfer(
                tx_input.strip(),
                expected_amount,
                deposit_time
            )
        else:
            return await self._verify_blockchain_tx(
                tx_input,
                expected_amount,
                deposit_time
            )

    async def _verify_binance_pay_transaction(
        self,
        transfer_id: str,
        expected_amount: Decimal,
        deposit_time: datetime
    ) -> Optional[Dict]:
        try:
            timestamp = await self._get_server_time()
            params = {
                'timestamp': str(timestamp),
                'recvWindow': '5000',
                'startTime': str(int((deposit_time - timedelta(minutes=60)).timestamp() * 1000)),
                'limit': '100'
            }

            signature, query_string = self._generate_signature(params)
            full_query_string = f"{query_string}&signature={signature}"
            headers = {'X-MBX-APIKEY': self.api_key}

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/sapi/v1/pay/transactions?{full_query_string}",
                    headers=headers
                ) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        data = await response.json()
                        transactions = data.get('data', [])
                        logger.info(f"Found Binance Pay transactions: {transactions}")

                        for transaction in transactions:
                            order_id = str(transaction.get('orderId', '')).strip()
                            if order_id == transfer_id:
                                amount = Decimal(str(transaction.get('amount')))
                                tx_time = datetime.fromtimestamp(int(transaction['transactionTime']) / 1000)

                                if self._verify_amount_and_time(amount, tx_time, expected_amount, deposit_time):
                                    return {
                                        'txid': transfer_id,
                                        'amount': float(amount),
                                        'timestamp': tx_time,
                                        'type': 'binance_pay',
                                        'status': transaction.get('transactionStatus'),
                                        'confirmed': True
                                    }
                    else:
                        logger.error(
                            f"Failed to retrieve Binance Pay transactions: {response.status}, Response: {response_text}"
                        )
            return None
        except Exception as e:
            logger.error(f"Error verifying Binance Pay transaction: {str(e)}", exc_info=True)
            return None

    async def _verify_offchain_transfer(
        self,
        transfer_id: str,
        expected_amount: Decimal,
        deposit_time: datetime
    ) -> Optional[Dict]:
        try:
            timestamp = await self._get_server_time()
            base_params = {
                'timestamp': str(timestamp),
                'recvWindow': '5000',
                'startTime': str(int((deposit_time - timedelta(minutes=60)).timestamp() * 1000)),
                'endTime': str(timestamp)
            }

            endpoints = [
                {
                    'url': '/sapi/v1/capital/deposit/hisrec',
                    'extra_params': {'coin': 'USDT'}
                },
                {
                    'url': '/sapi/v1/asset/transfer',
                    'extra_params': {'type': 'MAIN_FUNDING'}
                },
                {
                    'url': '/sapi/v1/capital/withdraw/history',
                    'extra_params': {'coin': 'USDT'}
                }
            ]

            headers = {'X-MBX-APIKEY': self.api_key}

            async with aiohttp.ClientSession() as session:
                for endpoint in endpoints:
                    try:
                        params = {**base_params, **endpoint['extra_params']}
                        signature, query_string = self._generate_signature(params)
                        full_query_string = f"{query_string}&signature={signature}"

                        async with session.get(
                            f"{self.base_url}{endpoint['url']}?{full_query_string}",
                            headers=headers
                        ) as response:
                            response_text = await response.text()
                            if response.status == 200:
                                data = await response.json()
                                logger.info(f"Response from {endpoint['url']}: {data}")

                                transactions = data if isinstance(data, list) else data.get('rows', data.get('data', []))

                                for tx in transactions:
                                    for id_field in ['txId', 'tranId', 'orderId', 'transactionId']:
                                        tx_id_value = str(tx.get(id_field, '')).strip()
                                        # إزالة البادئة إذا وجدت
                                        tx_id_clean = tx_id_value.replace('Off-chain transfer ', '').strip()
                                        if tx_id_clean == transfer_id.strip():
                                            amount = Decimal(str(tx.get('amount', tx.get('transactionAmount', 0))))

                                            tx_timestamp = int(tx.get(
                                                'insertTime',
                                                tx.get('timestamp', time.time() * 1000)
                                            ))
                                            tx_time = datetime.fromtimestamp(tx_timestamp / 1000)

                                            if self._verify_amount_and_time(amount, tx_time, expected_amount, deposit_time):
                                                return {
                                                    'txid': transfer_id,
                                                    'amount': float(amount),
                                                    'timestamp': tx_time,
                                                    'type': 'internal',
                                                    'transfer_type': 'off-chain',
                                                    'status': 'completed',
                                                    'confirmed': True
                                                }
                            else:
                                logger.error(
                                    f"Failed to retrieve data from {endpoint['url']}: {response.status}, Response: {response_text}"
                                )
                    except Exception as e:
                        logger.error(f"Error checking endpoint {endpoint['url']}: {str(e)}")
                        continue

            return None

        except Exception as e:
            logger.error(f"Error verifying off-chain transfer: {str(e)}")
            return None

    async def _verify_internal_transfer(
        self,
        transfer_id: str,
        expected_amount: Decimal,
        deposit_time: datetime
    ) -> Optional[Dict]:
        try:
            timestamp = await self._get_server_time()
            params = {
                'timestamp': str(timestamp),
                'startTime': str(int((deposit_time - timedelta(minutes=60)).timestamp() * 1000)),
                'endTime': str(timestamp),
                'recvWindow': '5000'
            }

            # تحويل القيم إلى سلاسل نصية
            params = {k: str(v) for k, v in params.items()}

            signature, query_string = self._generate_signature(params)
            full_query_string = f"{query_string}&signature={signature}"
            headers = {'X-MBX-APIKEY': self.api_key}

            logger.debug(f"Request URL: {self.base_url}/sapi/v1/asset/transfer?{full_query_string}")

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/sapi/v1/asset/transfer?{full_query_string}",
                    headers=headers
                ) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        data = await response.json()
                        for transfer in data.get('rows', []):
                            tran_id = str(transfer.get('tranId', '')).strip()
                            # إزالة البادئة إذا وجدت
                            tran_id_clean = tran_id.replace('Off-chain transfer ', '').strip()
                            if tran_id_clean == transfer_id.strip():
                                amount = Decimal(str(transfer.get('amount', 0)))
                                tx_time = datetime.fromtimestamp(transfer['timestamp'] / 1000)

                                if self._verify_amount_and_time(amount, tx_time, expected_amount, deposit_time):
                                    return {
                                        'txid': transfer_id,
                                        'amount': float(amount),
                                        'timestamp': tx_time,
                                        'type': 'internal',
                                        'confirmed': True
                                    }
                    else:
                        logger.error(
                            f"Failed to retrieve internal transfers: {response.status}, Response: {response_text}"
                        )
                return None

        except Exception as e:
            logger.error(f"Error verifying internal transfer: {str(e)}")
            return None

    async def _verify_blockchain_tx(
        self,
        tx_hash: str,
        expected_amount: Decimal,
        deposit_time: datetime
    ) -> Optional[Dict]:
        try:
            params = {
                'module': 'proxy',
                'action': 'eth_getTransactionByHash',
                'txhash': tx_hash,
                'apikey': self.bsc_api_key
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(self.bsc_url, params=params) as response:
                    if response.status != 200:
                        return None

                    tx_data = await response.json()
                    if not tx_data.get('result'):
                        return None

                    tx = tx_data['result']
                    if tx.get('to', '').lower() != self.usdt_contract.lower():
                        return None

                    receipt_params = {
                        'module': 'proxy',
                        'action': 'eth_getTransactionReceipt',
                        'txhash': tx_hash,
                        'apikey': self.bsc_api_key
                    }

                    async with session.get(self.bsc_url, params=receipt_params) as response:
                        if response.status != 200:
                            return None

                        receipt_data = await response.json()
                        receipt = receipt_data.get('result', {})

                        if not receipt or receipt.get('status') != '0x1':
                            return None

                        input_data = tx.get('input', '')
                        if not input_data.startswith('0xa9059cbb'):
                            return None

                        amount_hex = input_data[74:]
                        amount_int = int(amount_hex, 16)
                        amount = Decimal(amount_int) / Decimal('1000000000000000000')

                        block_params = {
                            'module': 'proxy',
                            'action': 'eth_getBlockByNumber',
                            'tag': tx['blockNumber'],
                            'boolean': 'true',
                            'apikey': self.bsc_api_key
                        }

                        async with session.get(self.bsc_url, params=block_params) as response:
                            if response.status != 200:
                                return None

                            block_data = await response.json()
                            block = block_data.get('result', {})
                            if not block:
                                return None

                            tx_time = datetime.fromtimestamp(int(block['timestamp'], 16))

                            if self._verify_amount_and_time(amount, tx_time, expected_amount, deposit_time):
                                return {
                                    'txid': tx_hash,
                                    'amount': float(amount),
                                    'timestamp': tx_time,
                                    'from_address': tx['from'],
                                    'to_address': self.usdt_contract,
                                    'confirmed': True,
                                    'type': 'blockchain',
                                    'block_number': int(tx['blockNumber'], 16)
                                }
            return None

        except Exception as e:
            logger.error(f"Error verifying blockchain tx: {str(e)}")
            return None
