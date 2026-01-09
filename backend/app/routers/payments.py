import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus, KeyStatus
from app.services.bot import bot_service

logger = logging.getLogger("morpheus.payments")

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/anypay/webhook")
async def anypay_webhook(request: Request, db: Session = Depends(get_db)):
    """Обработчик webhook от Anypay (GET запрос)"""
    # Получаем параметры из query string
    pay_id = request.query_params.get("pay_id")
    status = request.query_params.get("status")
    transaction_id = request.query_params.get("transaction_id")
    
    if not pay_id:
        raise HTTPException(status_code=400, detail="Missing pay_id")
    
    try:
        order = db.query(Order).filter_by(id=int(pay_id)).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        
        if status == "paid":
            order.status = OrderStatus.paid
            if transaction_id:
                order.provider_pay_id = str(transaction_id)
            if order.key:
                order.key.status = KeyStatus.activated
            db.commit()
            if bot_service:
                await bot_service.send_order_delivery(order.id)
        elif status in {"fail", "cancel"}:
            order.status = OrderStatus.failed
            # Возвращаем ключ в доступные, если платеж не прошел
            if order.key and order.key.status == KeyStatus.sold:
                order.key.status = KeyStatus.available
                order.key.sold_at = None
                order.key.sold_to_user_id = None
            db.commit()
        
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

