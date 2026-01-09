from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus, KeyStatus
from app.services.bot import bot_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/anypay/webhook")
async def anypay_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.form()
    pay_id = data.get("pay_id")
    status = data.get("status")
    if not pay_id:
        raise HTTPException(status_code=400, detail="Missing pay_id")
    order = db.query(Order).filter_by(id=int(pay_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if status == "paid":
        order.status = OrderStatus.paid
        if order.key:
            order.key.status = KeyStatus.activated
        db.commit()
        if bot_service:
            await bot_service.send_order_delivery(order.id)
    elif status in {"fail", "cancel"}:
        order.status = OrderStatus.failed
        db.commit()
    return {"ok": True}

