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
    """
    logger.info(f"Received NicePay webhook: order_id={order_id}, result={result}, payment_id={payment_id}")
    
    # Формируем словарь параметров для проверки подписи
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
        
        # Конвертируем amount из центов/копеек в рубли
        amount_rub = amount / 100.0
        
        # Если валюта не RUB, конвертируем (упрощенно)
        if amount_currency != "RUB":
            # Примерные курсы (должны совпадать с теми, что в bot.py)
            if amount_currency == "USD":
                amount_rub = amount_rub * 100.0  # 1 USD = 100 RUB
            elif amount_currency == "EUR":
                amount_rub = amount_rub * 110.0  # 1 EUR = 110 RUB
            elif amount_currency == "UAH":
                amount_rub = amount_rub / 4.0    # 1 RUB = 4 UAH
            elif amount_currency == "KZT":
                amount_rub = amount_rub / 5.0    # 1 RUB = 5 KZT
        
        # Проверяем сумму (с погрешностью 10%)
        expected_amount = order.amount
        difference = abs(amount_rub - expected_amount)
        max_difference = expected_amount * 0.1  # 10% погрешность
        
        if difference > max_difference:
            logger.warning(f"Webhook amount {amount_rub} differs significantly from order amount {expected_amount} for order {order_id}")
        
        # Обрабатываем статус платежа
        if result == "success":
            if order.status != OrderStatus.paid:
                order.status = OrderStatus.paid
                order.provider_pay_id = payment_id
                order.paid_at = datetime.utcnow()
                
                if order.key:
                    if order.key.status == KeyStatus.available:
                        order.key.status = KeyStatus.sold
                        order.key.sold_at = datetime.utcnow()
                        order.key.sold_to_user_id = order.user_id
                        logger.info(f"Order {order.id} marked as paid. Key {order.key.id} marked as sold and linked to user {order.user_id}.")
                    else:
                        logger.warning(f"Order {order.id} paid, but key {order.key.id} status is {order.key.status}, not available. Skipping status change.")
                
                db.commit()
                
                # Отправляем ключ пользователю через бота
                if bot_service:
                    await bot_service.send_order_delivery(order.id)
                    logger.info(f"Order {order.id} delivery sent to user")
                
            else:
                logger.info(f"Order {order.id} already paid, skipping.")
                
        elif result == "error":
            if order.status != OrderStatus.failed:
                order.status = OrderStatus.failed
                order.failed_at = datetime.utcnow()
                
                # Возвращаем ключ в доступные, если платеж не прошел
                if order.key and order.key.status == KeyStatus.sold:
                    order.key.status = KeyStatus.available
                    order.key.sold_at = None
                    order.key.sold_to_user_id = None
                    logger.info(f"Order {order.id} marked as failed. Key {order.key.id} reverted to available.")
                
                db.commit()
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