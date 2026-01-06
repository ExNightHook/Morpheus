from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List, Optional
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
    User,
)
from app.security import create_access_token, get_password_hash
from app.utils import generate_key_value

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/login", response_class=HTMLResponse)
def login_page():
    """Страница входа в админ-панель"""
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "admin_login.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@router.get("/panel", response_class=HTMLResponse)
def admin_panel_page():
    """Главная страница админ-панели (без авторизации, проверка на клиенте)"""
    template_path = os.path.join(os.path.dirname(__file__), "..", "templates", "admin_panel.html")
    with open(template_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


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


@router.get("/products/{product_id}/prices", response_model=List[schemas.ProductPriceOut])
def list_prices(
    product_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Список цен продукта"""
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    prices = db.query(ProductPrice).filter_by(product_id=product_id).all()
    return prices


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
    # Проверяем, нет ли уже цены с такой длительностью
    existing = db.query(ProductPrice).filter_by(
        product_id=product_id, duration_days=payload.duration_days
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Price for this duration already exists")
    price = ProductPrice(
        product_id=product.id,
        duration_days=payload.duration_days,
        price_rub=payload.price_rub,
    )
    db.add(price)
    db.commit()
    db.refresh(price)
    return price


@router.get("/builds/{product_id}", response_model=List[schemas.BuildOut])
def list_builds(
    product_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Список билдов продукта"""
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    builds = db.query(Build).filter_by(product_id=product_id).all()
    return builds


@router.post("/builds/{product_id}", response_model=schemas.BuildOut)
def upload_build(
    product_id: int,
    label: str = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    uploads_dir = "/app/uploads"
    os.makedirs(uploads_dir, exist_ok=True)
    # Сохраняем файл с уникальным именем
    import uuid
    file_ext = os.path.splitext(file.filename)[1] or ".zip"
    unique_filename = f"{product.slug}_{label}_{uuid.uuid4().hex[:8]}{file_ext}"
    file_path = os.path.join(uploads_dir, unique_filename)
    with open(file_path, "wb") as f:
        f.write(file.file.read())
    build = Build(product_id=product_id, label=label, file_path=file_path)
    db.add(build)
    db.commit()
    db.refresh(build)
    return build


@router.get("/keys", response_model=List[schemas.KeyOut])
def list_keys(
    product_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Список ключей с фильтрацией по продукту"""
    query = db.query(Key)
    if product_id:
        query = query.filter_by(product_id=product_id)
    keys = query.order_by(Key.created_at.desc()).limit(500).all()
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


@router.put("/keys/{key_id}", response_model=schemas.KeyOut)
def update_key(
    key_id: int,
    payload: schemas.KeyUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Редактирование ключа"""
    key = db.query(Key).filter_by(id=key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    
    if payload.duration_days is not None:
        key.duration_days = payload.duration_days
    if payload.status is not None:
        key.status = payload.status
    if payload.activation_uuid is not None:
        key.activation_uuid = payload.activation_uuid
    if payload.expires_at is not None:
        key.expires_at = payload.expires_at
    
    db.commit()
    db.refresh(key)
    return key


@router.delete("/keys/{key_id}")
def delete_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Удаление ключа"""
    key = db.query(Key).filter_by(id=key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    db.delete(key)
    db.commit()
    return {"success": True}


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


@router.get("/users", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), _: AdminUser = Depends(get_current_admin)):
    """Список пользователей"""
    users = db.query(User).order_by(User.created_at.desc()).limit(500).all()
    return users

