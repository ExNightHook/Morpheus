import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus, KeyStatus
from app.services.bot import bot_service
from app.services.anypay import AnypayClient

logger = logging.getLogger("morpheus.payments")

router = APIRouter(prefix="/payments", tags=["payments"])

anypay_client = AnypayClient()


@router.post("/anypay/webhook")
async def anypay_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Обработчик webhook от Anypay (SCI).
    
    Принимает POST запрос с параметрами:
    - merchant_id: ID проекта
    - transaction_id: Номер платежа
    - pay_id: Номер заказа
    - amount: Сумма платежа
    - currency: Валюта платежа
    - profit: Сумма к зачислению
    - email: Email плательщика
    - method: Метод платежа
    - status: Статус платежа (paid, waiting, canceled, expired, error)
    - test: Признак тестового режима (0 или 1)
    - created_date: Дата создания
    - completed_date: Дата завершения
    - sign: Контрольная подпись
    """
    # Получаем IP адрес клиента
    client_ip = request.client.host if request.client else None
    
    # Проверяем IP адрес (опционально, можно отключить для тестирования)
    # if client_ip and not anypay_client.verify_webhook_ip(client_ip):
    #     logger.warning(f"Webhook from untrusted IP: {client_ip}")
    #     # Не блокируем, но логируем
    
    # Получаем параметры из формы (POST)
    form_data = await request.form()
    
    merchant_id = form_data.get("merchant_id")
    transaction_id = form_data.get("transaction_id")
    pay_id = form_data.get("pay_id")
    amount = form_data.get("amount")
    currency = form_data.get("currency")
    status = form_data.get("status")
    sign = form_data.get("sign")
    
    if not pay_id:
        logger.error("Webhook missing pay_id")
        raise HTTPException(status_code=400, detail="Missing pay_id")
    
    if not sign:
        logger.error("Webhook missing sign")
        raise HTTPException(status_code=400, detail="Missing sign")
    
    # Проверяем подпись
    if not anypay_client.verify_webhook_signature(
        currency=currency or "",
        amount=amount or "",
        pay_id=pay_id,
        merchant_id=merchant_id or "",
        status=status or "",
        sign=sign
    ):
        logger.error(f"Invalid webhook signature for pay_id={pay_id}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    try:
        order = db.query(Order).filter_by(id=int(pay_id)).first()
        if not order:
            logger.warning(f"Order {pay_id} not found for webhook")
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Проверяем сумму и валюту
        if amount and float(amount) < order.amount:
            logger.warning(f"Webhook amount {amount} less than order amount {order.amount} for order {pay_id}")
            # Не блокируем, но логируем
        
        # Обрабатываем статус платежа
        if status == "paid":
            if order.status != OrderStatus.paid:  # Предотвращаем двойную обработку
                order.status = OrderStatus.paid
                if transaction_id:
                    order.provider_pay_id = str(transaction_id)
                if order.key:
                    order.key.status = KeyStatus.activated
                db.commit()
                logger.info(f"Order {order.id} marked as paid. Key {order.key.id if order.key else 'N/A'} activated.")
                if bot_service:
                    await bot_service.send_order_delivery(order.id)
            else:
                logger.info(f"Order {order.id} already paid, skipping.")
        elif status in {"canceled", "expired", "error"}:
            if order.status != OrderStatus.failed:  # Предотвращаем двойную обработку
                order.status = OrderStatus.failed
                # Возвращаем ключ в доступные, если платеж не прошел
                if order.key and order.key.status == KeyStatus.sold:
                    order.key.status = KeyStatus.available
                    order.key.sold_at = None
                    order.key.sold_to_user_id = None
                db.commit()
                logger.info(f"Order {order.id} marked as failed/cancelled. Key {order.key.id if order.key else 'N/A'} reverted to available.")
            else:
                logger.info(f"Order {order.id} already failed/cancelled, skipping.")
        elif status == "waiting":
            # Платеж в ожидании, ничего не делаем
            logger.info(f"Order {order.id} status: waiting")
        else:
            logger.warning(f"Unhandled Anypay webhook status: {status} for order {order.id}")
        
        # Возвращаем OK для подтверждения получения webhook
        return "OK"
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

