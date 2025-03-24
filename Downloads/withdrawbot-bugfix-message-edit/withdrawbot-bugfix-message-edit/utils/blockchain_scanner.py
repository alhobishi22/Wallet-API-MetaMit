import os
import aiohttp
import asyncio
import logging
import json
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
import time as time_module
from typing import Optional, Dict
from datetime import time
logger = logging.getLogger(__name__)

class BlockchainScanner:
    def __init__(self):
        # API keys
        self.tron_api_key = os.getenv('TRONSCAN_API_KEY', '')
        self.bsc_api_key = os.getenv('BSCSCAN_API_KEY', '')
        self.eth_api_key = os.getenv('ETHERSCAN_API_KEY', '')
        self.arb_api_key = os.getenv('ARBISCAN_API_KEY', '')
        
        # Cache settings
        self._tx_cache = {}
        self._cache_timeout = 3600  # 1 hour cache timeout
        
        # Rate limiting settings
        self._last_api_calls = {
            'trc20': 0,
            'bep20': 0,
            'erc20': 0,
            'arb20': 0
        }
        self._min_call_interval = {
            'trc20': 0.2,  # 200ms
            'bep20': 0.2,
            'erc20': 0.2,
            'arb20': 0.2
        }
        
        # Contract addresses
        self.contracts = {
            'TRC20': 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
            'BEP20': '0x55d398326f99059fF775485246999027B3197955',
            'ERC20': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
            'ARB20': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9'  # USDT on Arbitrum One
        }
        
        # Decimal places for each network
        self.decimals = {
            'TRC20': 6,
            'BEP20': 18,
            'ERC20': 6,
            'ARB20': 6  # USDT on Arbitrum One has 6 decimals
        }

    def _get_cache_key(self, network: str, tx_hash: str) -> str:
        """إنشاء مفتاح للتخزين المؤقت"""
        return f"{network}:{tx_hash}"

    def _get_from_cache(self, cache_key: str) -> Optional[Dict]:
        """استرجاع البيانات من التخزين المؤقت"""
        if cache_key in self._tx_cache:
            data, timestamp = self._tx_cache[cache_key]
            if time_module.time() - timestamp < self._cache_timeout:
                logger.info(f"✅ تم استرجاع المعاملة من التخزين المؤقت: {cache_key}")
                return data
            del self._tx_cache[cache_key]
        return None

    def _add_to_cache(self, cache_key: str, data: Dict):
        """إضافة البيانات إلى التخزين المؤقت"""
        self._tx_cache[cache_key] = (data, time_module.time())
        logger.info(f"✅ تم تخزين المعاملة في التخزين المؤقت: {cache_key}")

    async def _wait_for_rate_limit(self, network: str):
        """التحكم في معدل الطلبات"""
        try:
            now = time_module.time()
            network = network.lower()  # تحويل الشبكة إلى أحرف صغيرة
            
            # التأكد من وجود القيم الافتراضية
            if network not in self._last_api_calls:
                self._last_api_calls[network] = 0
                
            if network not in self._min_call_interval:
                self._min_call_interval[network] = 0.2  # القيمة الافتراضية 200ms
            
            # حساب الوقت المنقضي منذ آخر طلب
            time_since_last_call = now - self._last_api_calls[network]
            wait_time = max(0, self._min_call_interval[network] - time_since_last_call)
            
            if wait_time > 0:
                logger.info(f"⏳ انتظار {wait_time:.2f} ثانية قبل الطلب التالي")
                await asyncio.sleep(wait_time)
            
            # تحديث وقت آخر طلب
            self._last_api_calls[network] = now
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحكم بمعدل الطلبات: {str(e)}")
            # في حالة الخطأ، ننتظر 0.2 ثانية كإجراء احتياطي
            await asyncio.sleep(0.2)

    def generate_unique_amount(self, base_amount: float) -> Decimal:
        """إنشاء مبلغ فريد بإضافة أرقام عشوائية"""
        base = Decimal(str(base_amount))
        random_decimals = Decimal(str(random.randint(1000, 9999))) / Decimal('100000')
        unique_amount = base + Decimal('0.02') + random_decimals
        return unique_amount.quantize(Decimal('0.00001'), rounding=ROUND_DOWN)

    async def verify_transaction_by_hash(self, network: str, tx_hash: str, expected_amount: Decimal, expected_address: str) -> Optional[Dict]:
        """التحقق من المعاملة باستخدام رمز المعاملة"""
        try:
            logger.info(f"🔍 التحقق من المعاملة:")
            logger.info(f"🔗 رمز المعاملة: {tx_hash}")
            logger.info(f"🌐 الشبكة: {network}")
            logger.info(f"💰 المبلغ المتوقع: {expected_amount}")
            logger.info(f"📫 العنوان المتوقع: {expected_address}")

            # تنظيف المدخلات
            tx_hash = tx_hash.strip()
            network = network.upper()

            # التحقق من صحة المدخلات
            if not tx_hash or not network or not expected_address:
                logger.error("❌ بيانات غير صالحة")
                return None

            if network not in ['BEP20', 'TRC20', 'ERC20', 'ARB20']:
                logger.error(f"❌ شبكة غير مدعومة: {network}")
                return None

            # التحقق من التخزين المؤقت
            cache_key = self._get_cache_key(network, tx_hash)
            cached_result = self._get_from_cache(cache_key)
            if cached_result:
                # التحقق من المبلغ والعنوان للنتيجة المخزنة مؤقتاً
                if (abs(float(cached_result['amount']) - float(expected_amount)) < 0.01 and
                    cached_result['to_address'].lower() == expected_address.lower()):
                    return cached_result
                logger.info("❌ النتيجة المخزنة مؤقتاً غير مطابقة للقيم المتوقعة")

            # انتظار معدل الطلبات
            await self._wait_for_rate_limit(network)

            # التحقق من المعاملة
            result = None
            if network == 'BEP20':
                result = await self._verify_bsc_transaction_hash(tx_hash, expected_amount, expected_address)
            elif network == 'TRC20':
                result = await self._verify_tron_transaction_hash(tx_hash, expected_amount, expected_address)
            elif network == 'ERC20':
                result = await self._verify_eth_transaction_hash(tx_hash, expected_amount, expected_address)
            elif network == 'ARB20':
                result = await self._verify_arb_transaction_hash(tx_hash, expected_amount, expected_address)

            # تخزين النتيجة في التخزين المؤقت إذا كانت ناجحة
            if result:
                self._add_to_cache(cache_key, result)

            return result

        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من المعاملة: {str(e)}")
            logger.error("Stack trace:", exc_info=True)
            return None

    async def _verify_bsc_transaction_hash(self, tx_hash: str, expected_amount: Decimal, expected_address: str) -> Optional[Dict]:
        """Verify BSC transaction by hash."""
        if not self.bsc_api_key:
            logger.error("❌ مفتاح BSCScan API غير مضبوط")
            return None

        # USDT contract address on BSC
        USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

        async with aiohttp.ClientSession() as session:
            try:
                url = "https://api.bscscan.com/api"
                
                # Clean and validate input
                tx_hash = tx_hash.strip().lower()
                if not tx_hash.startswith('0x'):
                    tx_hash = f'0x{tx_hash}'
                
                # First check if transaction exists
                params = {
                    'module': 'proxy',
                    'action': 'eth_getTransactionByHash',
                    'txhash': tx_hash,
                    'apikey': self.bsc_api_key
                }

                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"❌ خطأ في الاتصال: {response.status}")
                        return None

                    data = await response.json()
                    logger.info(f"Transaction details response: {data}")
                    
                    if not data.get('result'):
                        logger.error("❌ لم يتم العثور على المعاملة")
                        return None

                    # Verify transaction is to USDT contract
                    tx_data = data['result']
                    if tx_data.get('to', '').lower() != USDT_CONTRACT.lower():
                        logger.error("❌ المعاملة ليست إلى عقد USDT")
                        return None

                    # Then check if transaction is confirmed
                    params = {
                        'module': 'proxy',
                        'action': 'eth_getTransactionReceipt',
                        'txhash': tx_hash,
                        'apikey': self.bsc_api_key
                    }

                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            logger.error(f"❌ خطأ في الاتصال: {response.status}")
                            return None

                        data = await response.json()
                        logger.info(f"Transaction receipt response: {data}")
                        
                        result = data.get('result', {})
                        if not result:
                            logger.error("❌ لم يتم العثور على إيصال المعاملة")
                            return None
                            
                        status = result.get('status')
                        if status != '0x1':
                            logger.error("❌ المعاملة غير مؤكدة أو فاشلة")
                            logger.error(f"الحالة: {status}")
                            return None

                    # Finally check token transfer details from input data
                    input_data = tx_data.get('input', '')
                    if not input_data.startswith('0xa9059cbb'):  # Transfer method signature
                        logger.error("❌ ليست معاملة تحويل USDT")
                        return None

                    try:
                        # Extract recipient and amount from input data
                        recipient = '0x' + input_data[34:74]
                        amount_hex = input_data[74:]
                        amount_int = int(amount_hex, 16)
                        amount = Decimal(amount_int) / Decimal('1000000000000000000')  # 18 decimals

                        logger.info("\n📦 تفاصيل التحويل من البيانات:")
                        logger.info(f"💰 القيمة: {amount} USDT")
                        logger.info(f"📝 العقد: {USDT_CONTRACT}")
                        logger.info(f"👤 من: {tx_data['from']}")
                        logger.info(f"📫 إلى: {recipient}")

                        # Verify recipient address
                        if recipient.lower() != expected_address.lower():
                            logger.error("❌ عنوان المستلم غير صحيح")
                            logger.error(f"المتوقع: {expected_address.lower()}")
                            logger.error(f"الفعلي: {recipient.lower()}")
                            return None

                        # Verify amount with tolerance
                        if abs(float(amount) - float(expected_amount)) >= 0.01:
                            logger.error("❌ المبلغ غير مطابق")
                            logger.error(f"المتوقع: {expected_amount}")
                            logger.error(f"الفعلي: {amount}")
                            return None

                        # All checks passed
                        logger.info("✅ تم التحقق من المعاملة بنجاح!")
                        return {
                            'txid': tx_hash,
                            'amount': float(amount),
                            'timestamp': datetime.now(),  # Use current time as we don't have exact timestamp
                            'from_address': tx_data['from'],
                            'to_address': recipient,
                            'confirmed': True,
                            'block_number': tx_data['blockNumber'],
                            'contract_address': USDT_CONTRACT,  # إضافة عنوان العقد
                            'network': 'BEP20'  # إضافة نوع الشبكة
                        }

                    except (ValueError, TypeError, KeyError, IndexError) as e:
                        logger.error(f"❌ خطأ في تحليل بيانات المعاملة: {str(e)}")
                        return None

            except Exception as e:
                logger.error(f"❌ خطأ في التحقق من المعاملة: {str(e)}")
                logger.error("Stack trace:", exc_info=True)
                return None

    async def _verify_tron_transaction_hash(self, tx_hash: str, expected_amount: Decimal, expected_address: str) -> Optional[Dict]:
        """التحقق من معاملة TRON."""
        # قائمة عناوين عقود USDT المعروفة على شبكة TRON
        USDT_CONTRACTS = {
            # العنوان الرئيسي لـ USDT على TRON
            "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t": "41a614f803b6fd780986a42c78ec9c7f77e6ded13c",
            # يمكن إضافة عناوين أخرى هنا إذا لزم الأمر
        }
        
        def normalize_tron_contract(addr: str) -> str:
            """تحويل عنوان العقد إلى الصيغة القياسية"""
            addr = addr.strip()
            # إذا كان العنوان يبدأ بـ TR، نحوله إلى صيغة hex
            if addr.startswith('TR'):
                from base58 import b58decode_check
                try:
                    raw = b58decode_check(addr)
                    return raw[1:].hex()
                except:
                    return addr.lower()
            # إذا كان العنوان يبدأ بـ 41، نستخدمه كما هو
            elif addr.startswith('41'):
                return addr.lower()
            return addr.lower()
        
        try:
            async with aiohttp.ClientSession() as session:
                # تنظيف المدخلات
                tx_hash = tx_hash.strip()
                expected_address = expected_address.strip()
                
                logger.info(f"\n🔍 التحقق من معاملة TRON:")
                logger.info(f"📝 رقم المعاملة: {tx_hash}")
                logger.info(f"💰 المبلغ المتوقع: {expected_amount} USDT")
                logger.info(f"📫 العنوان المتوقع: {expected_address}")
                
                # محاولة استخدام Tronscan API
                url = f"https://api.trongrid.io/wallet/gettransactionbyid"
                headers = {"Accept": "application/json"}
                data = {"value": tx_hash}
                
                async with session.post(url, json=data, headers=headers, timeout=10) as response:
                    if response.status != 200:
                        logger.error(f"❌ فشل الاتصال بـ API: {response.status}")
                        return None

                    tx_data = await response.json()
                    logger.info(f"📦 بيانات المعاملة: {json.dumps(tx_data, indent=2)}")

                    if not tx_data:
                        logger.error("❌ لم يتم العثور على المعاملة")
                        return None

                    # التحقق من حالة المعاملة
                    if not tx_data.get('ret', [{}])[0].get('contractRet') == 'SUCCESS':
                        logger.error("❌ المعاملة غير ناجحة")
                        return None

                    # الحصول على تفاصيل المعاملة
                    contract = tx_data.get('raw_data', {}).get('contract', [{}])[0]
                    if not contract or contract.get('type') != 'TriggerSmartContract':
                        logger.error("❌ نوع المعاملة غير صحيح")
                        return None

                    # التحقق من عقد USDT
                    contract_address = contract.get('parameter', {}).get('value', {}).get('contract_address')
                    if not contract_address:
                        logger.error("❌ لم يتم العثور على عنوان العقد")
                        return None

                    # تحويل عنوان العقد إلى الصيغة القياسية
                    normalized_contract = normalize_tron_contract(contract_address)
                    logger.info(f"📝 عنوان العقد المستخدم: {contract_address}")
                    logger.info(f"📝 عنوان العقد بعد التحويل: {normalized_contract}")

                    # التحقق من أن العقد هو أحد عقود USDT المعروفة
                    valid_contract_addresses = set(normalize_tron_contract(addr) for addr in USDT_CONTRACTS.values())
                    if normalized_contract not in valid_contract_addresses:
                        logger.error("❌ عقد USDT غير صحيح")
                        logger.error(f"العقد المستخدم: {contract_address}")
                        logger.error(f"العقود الصالحة: {', '.join(USDT_CONTRACTS.keys())}")
                        return None
                        
                    # تحديد عنوان العقد الرئيسي للإرجاع في النتيجة
                    main_contract = next(k for k, v in USDT_CONTRACTS.items() 
                                      if normalize_tron_contract(v) == normalized_contract)

                    # استخراج المبلغ والعنوان
                    try:
                        # استخراج العنوان والمبلغ من البيانات
                        data = contract.get('parameter', {}).get('value', {}).get('data', '')
                        if not data.startswith('a9059cbb'):  # Transfer method signature
                            logger.error("❌ ليست معاملة تحويل USDT")
                            return None

                        # استخراج العنوان والمبلغ من البيانات
                        recipient = '41' + data[32:72]  # تحويل العنوان إلى صيغة TRON
                        amount_hex = data[72:]
                        amount = Decimal(int(amount_hex, 16)) / Decimal('1000000')  # 6 decimals for TRON USDT

                        logger.info(f"\n📦 تفاصيل التحويل المستخرجة:")
                        logger.info(f"💰 المبلغ: {amount} USDT")
                        logger.info(f"📫 إلى: {recipient}")

                        # التحقق من المبلغ والعنوان
                        if abs(amount - expected_amount) >= Decimal('0.000001'):
                            logger.error(f"❌ المبلغ غير مطابق. المتوقع: {expected_amount}, الفعلي: {amount}")
                            return None

                        # التحقق من العنوان (مع دعم الصيغ المختلفة)
                        def normalize_tron_address(addr: str) -> str:
                            """تحويل العنوان إلى الصيغة القياسية"""
                            addr = addr.strip()
                            # إذا كان العنوان يبدأ بـ T، نحوله إلى صيغة 41
                            if addr.startswith('T'):
                                from base58 import b58decode_check
                                try:
                                    raw = b58decode_check(addr)
                                    return '41' + raw[1:].hex()
                                except:
                                    return addr.lower()
                            # إذا كان العنوان يبدأ بـ 41، نستخدمه كما هو
                            elif addr.startswith('41'):
                                return addr.lower()
                            # إذا كان العنوان يبدأ بـ 0x، نحذف 0x ونضيف 41
                            elif addr.startswith('0x'):
                                return '41' + addr[2:].lower()
                            return addr.lower()

                        normalized_recipient = normalize_tron_address(recipient)
                        normalized_expected = normalize_tron_address(expected_address)
                        
                        if normalized_recipient != normalized_expected:
                            logger.error(f"❌ العنوان غير مطابق.")
                            logger.error(f"المتوقع: {expected_address} -> {normalized_expected}")
                            logger.error(f"الفعلي: {recipient} -> {normalized_recipient}")
                            return None

                        logger.info("✅ تم التحقق من المعاملة بنجاح!")
                        return {
                            'txid': tx_hash,
                            'amount': float(amount),
                            'timestamp': datetime.now(),
                            'from_address': contract.get('parameter', {}).get('value', {}).get('owner_address'),
                            'to_address': recipient,
                            'confirmed': True,
                            'contract_address': main_contract,
                            'network': 'TRC20'
                        }

                    except (ValueError, TypeError, KeyError, IndexError) as e:
                        logger.error(f"❌ خطأ في تحليل بيانات المعاملة: {str(e)}")
                        return None
                        if not trc20_transfers:
                            logger.error("❌ لا توجد تحويلات USDT")
                            return None

                        # البحث عن التحويل الصحيح
                        transfer = None
                        for t in trc20_transfers:
                            if (t.get('contract_address') == USDT_CONTRACT and 
                                t.get('to_address') == expected_address):
                                transfer = t
                                break

                        if not transfer:
                            logger.error("❌ لم يتم العثور على التحويل المطابق")
                            return None

                        # التحقق من المبلغ
                        tx_amount = Decimal(transfer.get('amount_str', '0')) / Decimal('1000000')
                        if abs(tx_amount - expected_amount) > Decimal('0.01'):
                            logger.error("❌ المبلغ غير مطابق")
                            logger.error(f"المتوقع: {expected_amount}")
                            logger.error(f"الفعلي: {tx_amount}")
                            return None

                        logger.info("✅ تم التحقق من المعاملة بنجاح!")
                        return {
                            'txid': tx_hash,
                            'amount': float(tx_amount),
                            'timestamp': datetime.fromtimestamp(data.get('timestamp', 0) / 1000),
                            'from_address': transfer.get('from_address'),
                            'to_address': transfer.get('to_address'),
                            'confirmed': True,
                            'block_number': data.get('block')
                        }

        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من المعاملة: {str(e)}")
            logger.exception("تفاصيل الخطأ:")
            return None

    async def _verify_eth_transaction_hash(self, tx_hash: str, expected_amount: Decimal, expected_address: str) -> Optional[Dict]:
        """Verify ETH transaction by hash."""
        if not self.eth_api_key:
            logger.error("❌ مفتاح Etherscan API غير مضبوط")
            return None

        # USDT contract address on Ethereum
        USDT_CONTRACT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"

        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.etherscan.io/api"
                
                # Clean and validate input
                tx_hash = tx_hash.strip().lower()
                if not tx_hash.startswith('0x'):
                    tx_hash = f'0x{tx_hash}'
                
                # Get transaction details
                params = {
                    'module': 'proxy',
                    'action': 'eth_getTransactionByHash',
                    'txhash': tx_hash,
                    'apikey': self.eth_api_key
                }

                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"❌ خطأ في الاتصال: {response.status}")
                        return None

                    data = await response.json()
                    if not data.get('result'):
                        logger.error("❌ لم يتم العثور على المعاملة")
                        return None

                    tx_data = data['result']
                    if tx_data.get('to', '').lower() != USDT_CONTRACT.lower():
                        logger.error("❌ المعاملة ليست إلى عقد USDT")
                        return None

                    # Get transaction receipt
                    params['action'] = 'eth_getTransactionReceipt'
                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            logger.error(f"❌ خطأ في الاتصال: {response.status}")
                            return None

                        receipt_data = await response.json()
                        receipt = receipt_data.get('result', {})
                        if not receipt or receipt.get('status') != '0x1':
                            logger.error("❌ المعاملة غير مؤكدة أو فاشلة")
                            return None

                        # Parse transaction data
                        try:
                            input_data = tx_data.get('input', '')
                            if not input_data.startswith('0xa9059cbb'):
                                logger.error("❌ ليست معاملة تحويل USDT")
                                return None

                            recipient = '0x' + input_data[34:74]
                            amount_hex = input_data[74:]
                            amount_int = int(amount_hex, 16)
                            amount = Decimal(amount_int) / Decimal('1000000')  # 6 decimals for USDT on ETH

                            if recipient.lower() != expected_address.lower():
                                logger.error("❌ عنوان المستلم غير صحيح")
                                return None

                            if abs(float(amount) - float(expected_amount)) >= 0.01:
                                logger.error("❌ المبلغ غير مطابق")
                                return None

                            # Get block info for timestamp
                            params['action'] = 'eth_getBlockByNumber'
                            params['tag'] = tx_data['blockNumber']
                            params['boolean'] = 'true'

                            async with session.get(url, params=params) as response:
                                if response.status == 200:
                                    block_data = await response.json()
                                    block = block_data.get('result', {})
                                    timestamp = int(block.get('timestamp', '0'), 16)
                                else:
                                    timestamp = int(time_module.time())

                            return {
                                'txid': tx_hash,
                                'amount': float(amount),
                                'timestamp': datetime.fromtimestamp(timestamp),
                                'from_address': tx_data['from'],
                                'to_address': recipient,
                                'confirmed': True,
                                'block_number': tx_data['blockNumber']
                            }

                        except (ValueError, TypeError, KeyError) as e:
                            logger.error(f"❌ خطأ في تحليل بيانات المعاملة: {str(e)}")
                            return None

        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من معاملة Ethereum: {str(e)}")
            logger.error("Stack trace:", exc_info=True)
            return None

    async def _verify_arb_transaction_hash(self, tx_hash: str, expected_amount: Decimal, expected_address: str) -> Optional[Dict]:
        """Verify Arbitrum One transaction by hash."""
        if not self.arb_api_key:
            logger.error("❌ مفتاح Arbiscan API غير مضبوط")
            return None

        # USDT contract address on Arbitrum One
        USDT_CONTRACT = "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9"

        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.arbiscan.io/api"
                
                # Clean and validate input
                tx_hash = tx_hash.strip().lower()
                if not tx_hash.startswith('0x'):
                    tx_hash = f'0x{tx_hash}'
                
                # First check if transaction exists
                params = {
                    'module': 'proxy',
                    'action': 'eth_getTransactionByHash',
                    'txhash': tx_hash,
                    'apikey': self.arb_api_key
                }

                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"❌ خطأ في الاتصال: {response.status}")
                        return None

                    data = await response.json()
                    logger.info(f"Transaction details response: {data}")
                    
                    if not data.get('result'):
                        logger.error("❌ لم يتم العثور على المعاملة")
                        return None

                    # Verify transaction is to USDT contract
                    tx_data = data['result']
                    if tx_data.get('to', '').lower() != USDT_CONTRACT.lower():
                        logger.error("❌ المعاملة ليست إلى عقد USDT")
                        return None

                    # Then check if transaction is confirmed
                    params = {
                        'module': 'proxy',
                        'action': 'eth_getTransactionReceipt',
                        'txhash': tx_hash,
                        'apikey': self.arb_api_key
                    }

                    async with session.get(url, params=params) as response:
                        if response.status != 200:
                            logger.error(f"❌ خطأ في الاتصال: {response.status}")
                            return None

                        data = await response.json()
                        logger.info(f"Transaction receipt response: {data}")
                        
                        result = data.get('result', {})
                        if not result:
                            logger.error("❌ لم يتم العثور على إيصال المعاملة")
                            return None
                            
                        status = result.get('status')
                        if status != '0x1':
                            logger.error("❌ المعاملة غير مؤكدة أو فاشلة")
                            logger.error(f"الحالة: {status}")
                            return None

                    # Finally check token transfer details from input data
                    input_data = tx_data.get('input', '')
                    if not input_data.startswith('0xa9059cbb'):  # Transfer method signature
                        logger.error("❌ ليست معاملة تحويل USDT")
                        return None

                    try:
                        # Extract recipient and amount from input data
                        recipient = '0x' + input_data[34:74]
                        amount_hex = input_data[74:]
                        amount_int = int(amount_hex, 16)
                        amount = Decimal(amount_int) / Decimal('1000000')  # 6 decimals for USDT on Arbitrum

                        logger.info("\n📦 تفاصيل التحويل من البيانات:")
                        logger.info(f"💰 القيمة: {amount} USDT")
                        logger.info(f"📝 العقد: {USDT_CONTRACT}")
                        logger.info(f"👤 من: {tx_data['from']}")
                        logger.info(f"📫 إلى: {recipient}")

                        # Verify recipient address
                        if recipient.lower() != expected_address.lower():
                            logger.error("❌ عنوان المستلم غير صحيح")
                            logger.error(f"المتوقع: {expected_address.lower()}")
                            logger.error(f"الفعلي: {recipient.lower()}")
                            return None

                        # Verify amount with tolerance
                        if abs(float(amount) - float(expected_amount)) >= 0.01:
                            logger.error("❌ المبلغ غير مطابق")
                            logger.error(f"المتوقع: {expected_amount}")
                            logger.error(f"الفعلي: {amount}")
                            return None

                        # Get block info for timestamp
                        params = {
                            'module': 'proxy',
                            'action': 'eth_getBlockByNumber',
                            'tag': tx_data['blockNumber'],
                            'boolean': 'true',
                            'apikey': self.arb_api_key
                        }

                        async with session.get(url, params=params) as response:
                            if response.status == 200:
                                block_data = await response.json()
                                block = block_data.get('result', {})
                                timestamp = int(block.get('timestamp', '0'), 16)
                            else:
                                timestamp = int(time_module.time())

                        # All checks passed
                        logger.info("✅ تم التحقق من المعاملة بنجاح!")
                        return {
                            'txid': tx_hash,
                            'amount': float(amount),
                            'timestamp': datetime.fromtimestamp(timestamp),
                            'from_address': tx_data['from'],
                            'to_address': recipient,
                            'confirmed': True,
                            'block_number': tx_data['blockNumber'],
                            'contract_address': USDT_CONTRACT,
                            'network': 'ARB20'
                        }

                    except (ValueError, TypeError, KeyError, IndexError) as e:
                        logger.error(f"❌ خطأ في تحليل بيانات المعاملة: {str(e)}")
                        return None

        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من المعاملة: {str(e)}")
            logger.error("Stack trace:", exc_info=True)
            return None

    async def verify_transaction(self, network: str, address: str, expected_amount: Decimal, 
                               start_time: datetime) -> Optional[Dict]:
        """Legacy method for backward compatibility."""
        logger.info("Using legacy verification method")
        logger.info(f"Searching for transaction to {address} with amount {expected_amount}")
        
        # For now, just return None as we want users to use the new hash-based verification
        logger.info("❌ الرجاء استخدام خيار إدخال رمز المعاملة يدوياً للتحقق")
        return None
