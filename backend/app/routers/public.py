from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict

from app.database import get_db
from app.models import Product, Key, KeyStatus, BotSettings

router = APIRouter(prefix="/api", tags=["api"])


def check_api_enabled(db: Session):
    """Проверяет, включен ли API"""
    settings = db.query(BotSettings).first()
    if not settings:
        return True  # По умолчанию включен
    return settings.api_enabled


@router.get("/products")
def products(db: Session = Depends(get_db)):
    if not check_api_enabled(db):
        raise HTTPException(status_code=503, detail="API is disabled")
    items = []
    products = db.query(Product).filter(Product.is_active == True).all()  # noqa: E712
    for p in products:
        variants: Dict[int, int] = {}
        for key in p.keys:
            if key.status == KeyStatus.available:
                variants[key.duration_days] = variants.get(key.duration_days, 0) + 1
        items.append(
            {
                "slug": p.slug,
                "title": p.title,
                "description": p.description,
                "available": variants,
            }
        )
    return {"products": items}


@router.post("/{product_slug}/auth")
def product_auth(
    product_slug: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    if not check_api_enabled(db):
        raise HTTPException(status_code=503, detail="API is disabled")
    key_value = payload.get("key")
    uuid = payload.get("uuid")
    if not key_value or not uuid:
        raise HTTPException(status_code=400, detail="Key and uuid required")
    product = db.query(Product).filter_by(slug=product_slug).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    key = db.query(Key).filter_by(value=key_value, product_id=product.id).first()
    if not key:
        return {"success": False, "error": "Key mismatch"}

    if key.status == KeyStatus.available:
        return {"success": False, "error": "Key not sold"}

    if key.activation_uuid and key.activation_uuid != uuid:
        return {"success": False, "error": "HWID mismatch"}

    if key.expires_at and key.expires_at < datetime.utcnow():
        key.status = KeyStatus.expired
        db.commit()
        return {"success": False, "error": "Key expired"}

    if not key.activation_uuid:
        key.activation_uuid = uuid
        if not key.expires_at:
            key.expires_at = datetime.utcnow() + timedelta(days=key.duration_days)
        key.status = KeyStatus.activated
        key.activated_at = datetime.utcnow()
        db.commit()

    remaining = None
    if key.expires_at:
        remaining_delta = key.expires_at - datetime.utcnow()
        remaining = {
            "days": remaining_delta.days,
            "hours": int(remaining_delta.seconds / 3600),
        }

    return {"success": True, "key": key_value, "uuid": uuid, "remaining": remaining}

