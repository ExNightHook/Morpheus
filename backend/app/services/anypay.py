import hashlib
import httpx
from app.config import settings


class AnypayClient:
    base_url = "https://anypay.io/api"

    def __init__(self):
        self.project_id = settings.anypay_project_id
        self.api_id = settings.anypay_api_id
        self.api_key = settings.anypay_api_key

    def _sign(self, action: str, *args) -> str:
        payload = action + "".join(args) + self.api_key
        return hashlib.sha256(payload.encode()).hexdigest()

    async def create_payment(self, pay_id: str, amount: float, desc: str, email: str = "client@example.com"):
        sign = self._sign(
            f"create-payment{self.api_id}",
            str(self.project_id),
            str(pay_id),
            f"{amount:.2f}",
            settings.anypay_currency,
            desc,
            settings.anypay_method,
        )
        data = {
            "project_id": self.project_id,
            "pay_id": pay_id,
            "amount": f"{amount:.2f}",
            "currency": settings.anypay_currency,
            "desc": desc[:150],
            "email": email,
            "method": settings.anypay_method,
            "success_url": settings.anypay_success_url,
            "fail_url": settings.anypay_fail_url,
            "sign": sign,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{self.base_url}/create-payment/{self.api_id}", data=data, timeout=20)
            resp.raise_for_status()
            return resp.json()

    def verify_webhook(self, action: str, sign: str) -> bool:
        expected = self._sign(action, self.api_id)
        return expected == sign

