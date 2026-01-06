from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List
import os

from app import schemas
from app.database import get_db
from app.dependencies import authenticate_admin, get_current_admin
from app.models import (
    AdminUser,
    BotSettings,
    Product,
    ProductPrice,
    Build,
    Key,
    KeyStatus,
)
from app.security import create_access_token, get_password_hash
from app.utils import generate_key_value

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", response_model=schemas.TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    admin = authenticate_admin(form_data.username, form_data.password, db)
    if not admin:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    token = create_access_token(admin.username)
    return schemas.TokenResponse(access_token=token)


@router.get("/products", response_model=List[schemas.ProductOut])
def list_products(db: Session = Depends(get_db), _: AdminUser = Depends(get_current_admin)):
    products = db.query(Product).all()
    return products


@router.post("/products", response_model=schemas.ProductOut)
def create_product(data: schemas.ProductCreate, db: Session = Depends(get_db), _: AdminUser = Depends(get_current_admin)):
    existing = db.query(Product).filter_by(slug=data.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")
    product = Product(slug=data.slug, title=data.title, description=data.description)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.post("/products/{product_id}/prices", response_model=schemas.ProductPriceOut)
def add_price(
    product_id: int,
    payload: schemas.ProductPriceCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    price = ProductPrice(
        product_id=product.id,
        duration_days=payload.duration_days,
        price_rub=payload.price_rub,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return price


@router.post("/builds/{product_id}", response_model=schemas.BuildOut)
def upload_build(
    product_id: int,
    label: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    uploads_dir = "/app/uploads"
    os.makedirs(uploads_dir, exist_ok=True)
    file_path = os.path.join(uploads_dir, file.filename)
    with open(file_path, "wb") as f:
        f.write(file.file.read())
    build = Build(product_id=product_id, label=label, file_path=file_path)
    db.add(build)
    db.commit()
    db.refresh(build)
    return build


@router.get("/keys", response_model=List[schemas.KeyOut])
def list_keys(db: Session = Depends(get_db), _: AdminUser = Depends(get_current_admin)):
    keys = db.query(Key).order_by(Key.created_at.desc()).limit(500).all()
    return keys


@router.post("/keys/generate", response_model=List[schemas.KeyOut])
def generate_keys(
    payload: schemas.KeysGenerateRequest,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    product = db.query(Product).filter_by(id=payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    created = []
    for _ in range(payload.count):
        key_val = generate_key_value()
        key = Key(
            product_id=product.id,
            value=key_val,
            duration_days=payload.duration_days,
            status=KeyStatus.available,
        )
        db.add(key)
        created.append(key)
    db.commit()
    return created


@router.get("/settings", response_model=schemas.BotSettingsOut)
def get_settings(db: Session = Depends(get_db), _: AdminUser = Depends(get_current_admin)):
    settings_obj = db.query(BotSettings).first()
    if not settings_obj:
        settings_obj = BotSettings()
        db.add(settings_obj)
        db.commit()
        db.refresh(settings_obj)
    return settings_obj


@router.put("/settings", response_model=schemas.BotSettingsOut)
def update_settings(
    payload: schemas.BotSettingsUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    settings_obj = db.query(BotSettings).first()
    if not settings_obj:
        settings_obj = BotSettings()
        db.add(settings_obj)
    if payload.bot_enabled is not None:
        settings_obj.bot_enabled = payload.bot_enabled
    if payload.maintenance_mode is not None:
        settings_obj.maintenance_mode = payload.maintenance_mode
    if payload.alert_message is not None:
        settings_obj.alert_message = payload.alert_message
    if payload.technical_message is not None:
        settings_obj.technical_message = payload.technical_message
    db.commit()
    db.refresh(settings_obj)
    return settings_obj

