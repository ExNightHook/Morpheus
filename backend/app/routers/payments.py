import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus, KeyStatus
from app.services.bot import bot_service
from app.services.nicepay import NicepayClient

logger = logging.getLogger("morpheus.payments")

router = APIRouter(prefix="/payments", tags=["payments"])

nicepay_client = NicepayClient()


@router.get("/nicepay/webhook")
async def nicepay_webhook(
    result: str = Query(...),
    payment_id: str = Query(...),
    merchant_id: str = Query(...),
    order_id: str = Query(...),
    amount: int = Query(...),
    amount_currency: str = Query(...),
    profit: int = Query(None),
    profit_currency: str = Query(None),
    method: str = Query(None),
    hash: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Обработчик webhook от NicePay.
    
    Принимает GET запрос с параметрами:
    - result: Финальный статус (success или error)
    - payment_id: ID платежа в NicePay
    - merchant_id: ID мерчанта
    - order_id: ID заказа в нашей системе
    - amount: Сумма платежа в центах/копейках
    - amount_currency: Валюта платежа
    - profit: Сумма дохода в центах/копейках
    - profit_currency: Валюта дохода
    - method: Метод оплаты
    - hash: Цифровая подпись запроса
    """
    # Формируем словарь параметров для проверки подписи
    # Все значения должны быть строками для правильной сортировки и хеширования
    params = {
        "result": str(result),
        "payment_id": str(payment_id),
        "merchant_id": str(merchant_id),
        "order_id": str(order_id),
        "amount": str(amount),
        "amount_currency": str(amount_currency),
    }
    if profit is not None:
        params["profit"] = str(profit)
    if profit_currency:
        params["profit_currency"] = str(profit_currency)
    if method:
        params["method"] = str(method)
    params["hash"] = str(hash)
    
    # Проверяем подпись
    if not nicepay_client.verify_webhook_hash(params):
        logger.error(f"Invalid webhook hash for order_id={order_id}")
        raise HTTPException(status_code=400, detail="Invalid hash")
    
    try:
        order = db.query(Order).filter_by(id=int(order_id)).first()
        if not order:
            logger.warning(f"Order {order_id} not found for webhook")
            raise HTTPException(status_code=404, detail="Order not found")
        
        # Конвертируем amount из центов в рубли для сравнения
        # Если валюта не RUB, нужно учитывать курс (упрощенно)
        amount_rub = amount / 100.0
        if amount_currency != "RUB":
            # Примерный курс (нужно настроить реальный)
            if amount_currency == "USD":
                amount_rub = amount_rub * 100.0  # Примерный курс 1 USD = 100 RUB
        
        # Проверяем сумму (с небольшой погрешностью)
        if abs(amount_rub - order.amount) > 1.0:
            logger.warning(f"Webhook amount {amount_rub} differs from order amount {order.amount} for order {order_id}")
            # Не блокируем, но логируем
        
        # Обрабатываем статус платежа
        if result == "success":
            if order.status != OrderStatus.paid:  # Предотвращаем двойную обработку
                order.status = OrderStatus.paid
                order.provider_pay_id = payment_id
                if order.key:
                    # Только при успешной оплате помечаем ключ как проданный и привязываем к пользователю
                    if order.key.status == KeyStatus.available:
                        order.key.status = KeyStatus.sold
                        order.key.sold_at = datetime.utcnow()
                        order.key.sold_to_user_id = order.user_id
                        logger.info(f"Order {order.id} marked as paid. Key {order.key.id} marked as sold and linked to user {order.user_id}.")
                    else:
                        logger.warning(f"Order {order.id} paid, but key {order.key.id} status is {order.key.status}, not available. Skipping status change.")
                db.commit()
                if bot_service:
                    await bot_service.send_order_delivery(order.id)
            else:
                logger.info(f"Order {order.id} already paid, skipping.")
        elif result == "error":
            if order.status != OrderStatus.failed:  # Предотвращаем двойную обработку
                order.status = OrderStatus.failed
                # Возвращаем ключ в доступные, если платеж не прошел
                if order.key and order.key.status == KeyStatus.sold:
                    order.key.status = KeyStatus.available
                    order.key.sold_at = None
                    order.key.sold_to_user_id = None
                db.commit()
                logger.info(f"Order {order.id} marked as failed. Key {order.key.id if order.key else 'N/A'} reverted to available.")
            else:
                logger.info(f"Order {order.id} already failed, skipping.")
        else:
            logger.warning(f"Unhandled NicePay webhook result: {result} for order {order.id}")
        
        # Возвращаем JSON ответ согласно документации NicePay
        return {"result": {"message": "Success"}}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

