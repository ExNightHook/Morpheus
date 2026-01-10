import hashlib
import logging
import httpx
from typing import Optional
from app.config import settings

logger = logging.getLogger("morpheus.nicepay")


class NicepayClient:
    """Клиент для работы с NicePay API"""
    
    api_url = "https://nicepay.io/public/api/payment"
    
    def __init__(self):
        self.merchant_id = settings.nicepay_merchant_id.strip() if settings.nicepay_merchant_id else ""
        self.secret_key = settings.nicepay_secret_key.strip() if settings.nicepay_secret_key else ""
        
        logger.info(f"NicePay initialized with merchant_id: {self.merchant_id[:10]}...")
        
        if not self.merchant_id or not self.secret_key:
            logger.error("NicePay credentials not configured! Set NICEPAY_MERCHANT_ID and NICEPAY_SECRET_KEY in .env")

    async def create_payment(
        self,
        order_id: str,
        amount: float,  # Уже в копейках/центах!
        currency: str = "RUB",
        customer: str = "",
        description: str = "",
        method: Optional[str] = None,
        success_url: Optional[str] = None,
        fail_url: Optional[str] = None,
    ) -> dict:
        """
        Создает платеж через NicePay API.
        
        Args:
            order_id: ID заказа в системе
            amount: Сумма платежа в КОПЕЙКАХ/ЦЕНТАХ (250 руб = 25000)
            currency: Валюта (USD, EUR, RUB, UAH, KZT)
            customer: Email или логин клиента
            description: Описание платежа
            method: Метод оплаты (опционально)
            success_url: URL перенаправления при успешной оплате
            fail_url: URL перенаправления при ошибке
        
        Returns:
            dict с payment_id и link для оплаты
        """
        # amount уже в копейках/центах, не нужно умножать на 100!
        amount_cents = int(amount)
        
        merchant_id = str(self.merchant_id).strip()
        secret_key = str(self.secret_key).strip()
        
        # ТОЧНО как в тестовом запросе
        payload = {
            "merchant_id": merchant_id,
            "secret": secret_key,
            "order_id": str(order_id),
            "customer": str(customer),
            "amount": amount_cents,
            "currency": str(currency).upper(),
        }
        
        # Добавляем только если переданы (необязательные)
        if description:
            payload["description"] = description[:150]
        
        # Не передаем method, success_url, fail_url - как в тестовом запросе
        
        logger.debug(f"NicePay payload (без secret): merchant_id={merchant_id}, order_id={order_id}, amount={amount_cents}, currency={currency}")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Sending request to NicePay API...")
                response = await client.post(self.api_url, json=payload)
                logger.info(f"NicePay API response status: {response.status_code}")
                logger.info(f"NicePay API response text: {response.text}")
                
                response.raise_for_status()
                data = response.json()
            
            if data.get("status") == "success":
                payment_data = data.get("data", {})
                logger.info(f"Payment created successfully: order_id={order_id}, payment_id={payment_data.get('payment_id')}")
                return {
                    "success": True,
                    "payment_id": payment_data.get("payment_id"),
                    "link": payment_data.get("link"),
                    "amount": payment_data.get("amount"),
                    "currency": payment_data.get("currency"),
                    "expired": payment_data.get("expired"),
                }
            else:
                error_msg = data.get("data", {}).get("message", "Unknown error")
                error_code = data.get("data", {}).get("code")
                logger.error(f"NicePay API error: {error_msg} (code: {error_code})")
                logger.error(f"Full response: {data}")
                raise ValueError(f"NicePay API error: {error_msg}")
                
        except httpx.RequestError as e:
            logger.error(f"NicePay request error: {e}")
            raise ValueError(f"Failed to create payment: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"NicePay HTTP error: {e}")
            raise ValueError(f"Failed to create payment: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"Unexpected error in create_payment: {e}", exc_info=True)
            raise

    def verify_webhook_hash(self, params: dict) -> bool:
        """
        Проверяет подпись webhook от NicePay.
        
        Алгоритм проверки:
        1. Сортируем параметры в алфавитном порядке (без hash)
        2. Добавляем secret_key в конец
        3. Объединяем через {np}
        4. SHA256 хеш должен совпадать с переданным hash
        """
        if "hash" not in params:
            logger.warning("Webhook hash missing in params")
            return False
        
        # Создаем копию параметров без hash
        params_copy = {k: v for k, v in params.items() if k != "hash"}
        received_hash = params["hash"]
        
        # Сортируем параметры в алфавитном порядке
        sorted_params = sorted(params_copy.items())
        
        # Добавляем secret_key в конец
        sorted_params.append(("secret", self.secret_key))
        
        # Объединяем через {np}
        hash_string = "{np}".join(str(value) for _, value in sorted_params)
        
        # Вычисляем SHA256
        calculated_hash = hashlib.sha256(hash_string.encode()).hexdigest()
        
        is_valid = calculated_hash == received_hash
        
        if not is_valid:
            logger.warning(f"Invalid webhook hash. Expected: {calculated_hash}, Got: {received_hash}")
            logger.debug(f"Hash string (without secret): {hash_string.replace(self.secret_key, '***SECRET***')}")
        
        return is_valid