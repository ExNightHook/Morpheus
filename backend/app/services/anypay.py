import hashlib
import httpx
import logging
from app.config import settings

logger = logging.getLogger("morpheus.anypay")


class AnypayClient:
    base_url = "https://anypay.io/api"

    def __init__(self):
        self.project_id = settings.anypay_project_id
        self.api_id = settings.anypay_api_id
        self.api_key = settings.anypay_api_key

    def _sign(self, action: str, *args) -> str:
        """Формирует подпись для запроса к Anypay API."""
        payload = action + "".join(str(arg) for arg in args) + self.api_key
        return hashlib.sha256(payload.encode()).hexdigest()

    async def create_payment(self, pay_id: str, amount: float, desc: str, email: str = "client@example.com", method: str = None):
        """
        Создает платеж в Anypay.
        
        Подпись формируется как: 
        hash('sha256', 'create-payment[API_ID][project_id][pay_id][amount][currency][desc][method][API_KEY]')
        """
        # Приводим валюту к верхнему регистру (Anypay требует RUB, USD, EUR и т.д.)
        currency = settings.anypay_currency.upper().strip()
        # Используем переданный метод или берем из настроек (метод в нижнем регистре)
        payment_method = (method or settings.anypay_methods.split(",")[0] if settings.anypay_methods else "ym").strip().lower()
        
        # Форматируем сумму с точкой как разделителем десятичных знаков
        amount_str = f"{amount:.2f}"
        
        # Обрезаем описание до 150 символов
        desc_trimmed = desc[:150]
        
        # Формируем подпись согласно документации (без разделителей между значениями)
        sign_payload = (
            "create-payment" +
            str(self.api_id) +
            str(self.project_id) +
            str(pay_id) +
            amount_str +
            currency +
            desc_trimmed +
            payment_method
        )
        sign = hashlib.sha256((sign_payload + self.api_key).encode()).hexdigest()
        
        # Формируем данные для запроса
        data = {
            "project_id": str(self.project_id),
            "pay_id": str(pay_id),
            "amount": amount_str,
            "currency": currency,
            "desc": desc_trimmed,
            "email": email,
            "method": payment_method,
            "sign": sign,
        }
        
        # Добавляем опциональные параметры, если они заданы
        if settings.anypay_success_url:
            data["success_url"] = settings.anypay_success_url
        if settings.anypay_fail_url:
            data["fail_url"] = settings.anypay_fail_url
        
        # Логируем запрос для отладки (без секретных данных)
        logger.info(f"Creating payment: pay_id={pay_id}, amount={amount_str}, currency={currency}, method={payment_method}")
        logger.debug(f"Sign payload (without API_KEY): {sign_payload}")
        logger.debug(f"Request data: project_id={self.project_id}, api_id={self.api_id}")
        
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/create-payment/{self.api_id}",
                    data=data,
                    timeout=20,
                    headers={
                        "Accept": "application/json",
                    }
                )
                resp.raise_for_status()
                result = resp.json()
                
                # Логируем ответ для отладки
                logger.debug(f"Anypay response: {result}")
                
                # Проверяем наличие ошибки в ответе
                if "error" in result:
                    error_code = result["error"].get("code", "unknown")
                    error_message = result["error"].get("message", "Unknown error")
                    logger.error(f"Anypay API error {error_code}: {error_message}")
                    raise ValueError(f"Anypay API error {error_code}: {error_message}")
                
                # Проверяем наличие результата
                if "result" not in result:
                    logger.error(f"Unexpected response format: {result}")
                    raise ValueError(f"Unexpected response format: {result}")
                
                return result
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error {e.response.status_code}: {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Error creating payment: {e}", exc_info=True)
                raise

    def verify_webhook(self, action: str, sign: str) -> bool:
        expected = self._sign(action, self.api_id)
        return expected == sign

