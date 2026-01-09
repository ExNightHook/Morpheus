import hashlib
import urllib.parse
import logging
from app.config import settings

logger = logging.getLogger("morpheus.anypay")


class AnypayClient:
    """Клиент для работы с Anypay через SCI (Simple Checkout Interface)"""
    
    merchant_url = "https://anypay.io/merchant"
    
    # IP адреса Anypay для проверки webhook
    ANYPAY_IPS = [
        "185.162.128.38",
        "185.162.128.39", 
        "185.162.128.88"
    ]

    def __init__(self):
        self.merchant_id = settings.anypay_project_id
        self.secret_key = settings.anypay_api_key  # Используем API_KEY как secret_key для SCI

    def create_payment_url(self, pay_id: str, amount: float, desc: str, email: str = "client@example.com", method: str = None):
        """
        Создает URL для оплаты через SCI (Simple Checkout Interface).
        
        Подпись формируется как SHA256:
        hash('sha256', 'merchant_id:pay_id:amount:currency:desc:success_url:fail_url:secret_key')
        
        Возвращает URL для редиректа пользователя на страницу оплаты.
        """
        # Используем переданный метод или берем из настроек (метод в нижнем регистре)
        payment_method = (method or settings.anypay_methods.split(",")[0] if settings.anypay_methods else "ym").strip().lower()
        
        # Определяем валюту в зависимости от метода оплаты
        # Для криптовалютных методов валюта должна быть в соответствующей криптовалюте
        crypto_methods = {
            "btc": "BTC",
            "eth": "ETH", 
            "usdt": "USDT",
            "ltc": "LTC",
            "etc": "ETC",
            "doge": "DOGE",
            "trx": "TRX",
            "xrp": "XRP",
            "bch": "BCH",
            "xmr": "XMR",
            "ton": "TON",
        }
        
        # Если метод оплаты - криптовалюта, используем её валюту
        if payment_method in crypto_methods:
            currency = crypto_methods[payment_method]
        else:
            # Для фиатных методов используем валюту из настроек
            # Для метода ym (ЮMoney) валюта должна быть RUB
            if payment_method == "ym":
                currency = "RUB"  # ЮMoney работает только с RUB
            else:
                currency = settings.anypay_currency.upper().strip()
                if not currency:
                    currency = "RUB"  # По умолчанию RUB
        
        # Форматируем сумму с точкой как разделителем десятичных знаков
        amount_str = f"{amount:.2f}"
        
        # Обрезаем описание до 150 символов
        desc_trimmed = (desc or "")[:150]
        
        # Получаем URL для успешной и неуспешной оплаты
        success_url = settings.anypay_success_url or ""
        fail_url = settings.anypay_fail_url or ""
        
        # Формируем подпись согласно документации SCI (SHA256 с разделителем :)
        # Порядок: merchant_id:pay_id:amount:currency:desc:success_url:fail_url:secret_key
        sign_payload = ":".join([
            str(self.merchant_id),
            str(pay_id),
            amount_str,
            currency,
            desc_trimmed,
            success_url,
            fail_url,
            self.secret_key
        ])
        sign = hashlib.sha256(sign_payload.encode()).hexdigest()
        
        # Формируем параметры для URL
        params = {
            "merchant_id": str(self.merchant_id),
            "pay_id": str(pay_id),
            "amount": amount_str,
            "currency": currency,
            "sign": sign,
        }
        
        # Добавляем опциональные параметры
        if desc_trimmed:
            params["desc"] = desc_trimmed
        if email:
            params["email"] = email
        if payment_method:
            params["method"] = payment_method
        if success_url:
            params["success_url"] = success_url
        if fail_url:
            params["fail_url"] = fail_url
        
        # Формируем URL
        payment_url = f"{self.merchant_url}?{urllib.parse.urlencode(params)}"
        
        logger.info(f"Created SCI payment URL: pay_id={pay_id}, amount={amount_str}, currency={currency}, method={payment_method}")
        logger.debug(f"Sign payload (without secret_key): {sign_payload.replace(self.secret_key, '***')}")
        
        return payment_url

    def verify_webhook_signature(self, currency: str, amount: str, pay_id: str, merchant_id: str, status: str, sign: str) -> bool:
        """
        Проверяет подпись webhook от Anypay (SCI).
        
        Подпись формируется как SHA256:
        hash('sha256', 'currency:amount:pay_id:merchant_id:status:secret_key')
        """
        # Формируем подпись согласно документации SCI
        sign_payload = ":".join([
            str(currency),
            str(amount),
            str(pay_id),
            str(merchant_id),
            str(status),
            self.secret_key
        ])
        expected_sign = hashlib.sha256(sign_payload.encode()).hexdigest()
        
        is_valid = expected_sign == sign
        if not is_valid:
            logger.warning(f"Invalid webhook signature. Expected: {expected_sign}, Got: {sign}")
            logger.debug(f"Sign payload (without secret_key): {sign_payload.replace(self.secret_key, '***')}")
        
        return is_valid

    def verify_webhook_ip(self, ip: str) -> bool:
        """Проверяет, что IP адрес принадлежит Anypay"""
        return ip in self.ANYPAY_IPS
