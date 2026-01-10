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
        # ЗАХАРДКОДИМ данные, которые точно работают в тестовом скрипте
        self.merchant_id = "696179391f37cffbecb0afbd"
        self.secret_key = "b4UaD-BPAK9-sinXx-41W3q-ZNctr"
        
        # Для отладки: сравниваем с настройками
        settings_merchant = settings.nicepay_merchant_id.strip() if settings.nicepay_merchant_id else ""
        settings_secret = settings.nicepay_secret_key.strip() if settings.nicepay_secret_key else ""
        
        logger.info(f"=== NICE PAY INIT DEBUG ===")
        logger.info(f"Hardcoded merchant_id: {self.merchant_id}")
        logger.info(f"Hardcoded secret: {self.secret_key[:5]}...{self.secret_key[-5:]}")
        logger.info(f"Settings merchant_id: {settings_merchant}")
        logger.info(f"Settings secret: {settings_secret[:5] if settings_secret else ''}...")
        
        if settings_merchant != self.merchant_id or settings_secret != self.secret_key:
            logger.error(f"!!! ВНИМАНИЕ: Данные из настроек не совпадают с работающими!")
            logger.error(f"Проверьте файл .env: NICEPAY_MERCHANT_ID и NICEPAY_SECRET_KEY")

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
        """
        # amount уже в копейках/центах
        amount_cents = int(amount)
        
        merchant_id = str(self.merchant_id).strip()
        secret_key = str(self.secret_key).strip()
        
        # ТОЧНО как в тестовом запросе
        payload = {
            "merchant_id": merchant_id,
            "secret": secret_key,
            "order_id": str(order_id),
            "customer": str(customer),  # В тестовом скрипте использует "customer", а не "account"
            "amount": amount_cents,
            "currency": str(currency).upper(),
        }
        
        # Добавляем только если переданы
        if description:
            payload["description"] = description[:150]
        
        # НЕ передаем method, success_url, fail_url - как в тестовом запросе
        
        logger.info(f"=== SENDING TO NICE PAY ===")
        logger.info(f"URL: {self.api_url}")
        logger.info(f"Payload (без secret): { {k: v if k != 'secret' else '***' for k, v in payload.items()} }")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"Sending POST request...")
                response = await client.post(self.api_url, json=payload)
                
                logger.info(f"Response status: {response.status_code}")
                logger.info(f"Response text: {response.text}")
                
                response.raise_for_status()
                data = response.json()
            
            if data.get("status") == "success":
                payment_data = data.get("data", {})
                logger.info(f"✅ Payment created successfully!")
                logger.info(f"Order ID: {order_id}, Payment ID: {payment_data.get('payment_id')}")
                logger.info(f"Link: {payment_data.get('link')}")
                
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
                logger.error(f"❌ NicePay API error: {error_msg} (code: {error_code})")
                logger.error(f"Full error response: {data}")
                raise ValueError(f"NicePay API error: {error_msg}")
                
        except httpx.RequestError as e:
            logger.error(f"❌ NicePay request error: {e}")
            raise ValueError(f"Failed to create payment: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ NicePay HTTP error: {e}")
            raise ValueError(f"Failed to create payment: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"❌ Unexpected error in create_payment: {e}", exc_info=True)
            raise

    def verify_webhook_hash(self, params: dict) -> bool:
        """
        Проверяет подпись webhook от NicePay.
        """
        if "hash" not in params:
            logger.warning("Webhook hash missing in params")
            return False
        
        params_copy = {k: v for k, v in params.items() if k != "hash"}
        received_hash = params["hash"]
        
        sorted_params = sorted(params_copy.items())
        sorted_params.append(("secret", self.secret_key))
        
        hash_string = "{np}".join(str(value) for _, value in sorted_params)
        calculated_hash = hashlib.sha256(hash_string.encode()).hexdigest()
        
        is_valid = calculated_hash == received_hash
        
        if not is_valid:
            logger.warning(f"Invalid webhook hash. Expected: {calculated_hash}, Got: {received_hash}")
        
        return is_valid