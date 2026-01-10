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
        
        # Детальное логирование для отладки
        logger.info(f"NicePay initialization:")
        logger.info(f"  Merchant ID: '{self.merchant_id}'")
        logger.info(f"  Merchant ID length: {len(self.merchant_id)}")
        logger.info(f"  Secret Key first 10 chars: '{self.secret_key[:10]}...'")
        
        if not self.merchant_id or not self.secret_key:
            logger.error("NicePay credentials not configured! Set NICEPAY_MERCHANT_ID and NICEPAY_SECRET_KEY in .env")
        else:
            logger.info(f"NicePay initialized successfully")

    async def create_payment(
        self,
        order_id: str,
        amount: float,
        currency: str = "USD",
        customer: str = "",  # Email или логин клиента
        description: str = "",
        method: Optional[str] = None,
        success_url: Optional[str] = None,
        fail_url: Optional[str] = None,
    ) -> dict:
        """
        Создает платеж через NicePay API.
        
        Args:
            order_id: ID заказа в системе
            amount: Сумма платежа (в центах/копейках, например 125.28 USD это 12528)
            currency: Валюта (USD, EUR, RUB, UAH, KZT)
            customer: Email или логин клиента (ОБЯЗАТЕЛЬНО!)
            description: Описание платежа
            method: Метод оплаты (опционально)
            success_url: URL перенаправления при успешной оплате
            fail_url: URL перенаправления при ошибке
        
        Returns:
            dict с payment_id и link для оплаты
        """
        # Конвертируем сумму в центы/копейки
        amount_cents = int(amount * 100)
        
        # Убеждаемся, что merchant_id и secret_key - строки без пробелов
        merchant_id = str(self.merchant_id).strip()
        secret_key = str(self.secret_key).strip()
        
        # Основные обязательные параметры
        payload = {
            "merchant_id": merchant_id,
            "secret": secret_key,
            "order_id": str(order_id),
            "customer": str(customer),  # Исправлено: было "account", должно быть "customer"
            "amount": amount_cents,
            "currency": str(currency).upper(),
        }
        
        # Логируем для отладки (без секретного ключа)
        debug_payload = payload.copy()
        debug_payload["secret"] = "***SECRET***"
        logger.debug(f"NicePay payment payload: {debug_payload}")
        logger.info(f"Creating payment: order_id={order_id}, amount={amount_cents} {currency}, customer={customer}")
        
        # Добавляем опциональные параметры
        if description:
            payload["description"] = description[:150]
        if method:
            payload["method"] = method
        if success_url:
            payload["success_url"] = success_url
        if fail_url:
            payload["fail_url"] = fail_url
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Sending request to NicePay API: {self.api_url}")
                response = await client.post(self.api_url, json=payload)
                logger.info(f"NicePay API response status: {response.status_code}")
                logger.info(f"NicePay API response: {response.text}")
                
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
            logger.warning(f"Invalid webhook hash.")
            logger.warning(f"Expected: {calculated_hash}")
            logger.warning(f"Received: {received_hash}")
            logger.debug(f"Hash string (without secret): {hash_string.replace(self.secret_key, '***SECRET***')}")
        
        return is_valid