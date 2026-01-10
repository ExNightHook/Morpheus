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
    Order,
    OrderStatus,
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
    # Нормализуем slug: заменяем пробелы на дефисы и приводим к нижнему регистру
    normalized_slug = data.slug.strip().replace(" ", "-").lower()
    # Удаляем множественные дефисы
    while "--" in normalized_slug:
        normalized_slug = normalized_slug.replace("--", "-")
    # Удаляем дефисы в начале и конце
    normalized_slug = normalized_slug.strip("-")
    
    existing = db.query(Product).filter_by(slug=normalized_slug).first()
    if existing:
        raise HTTPException(status_code=400, detail="Slug already exists")
    product = Product(slug=normalized_slug, title=data.title, description=data.description)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=schemas.ProductOut)
def update_product(
    product_id: int,
    data: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Редактирование продукта"""
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if data.title is not None:
        product.title = data.title
    if data.description is not None:
        product.description = data.description
    
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Удаление продукта"""
    try:
        product = db.query(Product).filter_by(id=product_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Проверяем наличие активных заказов
        active_orders = db.query(Order).filter_by(
            product_id=product_id
        ).filter(
            Order.status.in_([OrderStatus.pending, OrderStatus.waiting])
        ).count()
        
        if active_orders > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete product: {active_orders} active orders exist"
            )
        
        # Удаляем связанные данные (каскадное удаление через БД или вручную)
        # Удаляем все заказы, связанные с продуктом (включая завершенные)
        orders = db.query(Order).filter_by(product_id=product_id).all()
        for order in orders:
            db.delete(order)
        
        # Удаляем билды и их файлы
        builds = db.query(Build).filter_by(product_id=product_id).all()
        for build in builds:
            if os.path.exists(build.file_path):
                try:
                    os.remove(build.file_path)
                except Exception:
                    pass
            db.delete(build)
        
        # Удаляем цены
        prices = db.query(ProductPrice).filter_by(product_id=product_id).all()
        for price in prices:
            db.delete(price)
        
        # Удаляем ключи (если они не использованы в завершенных заказах)
        keys = db.query(Key).filter_by(product_id=product_id).all()
        for key in keys:
            db.delete(key)
        
        # Удаляем продукт
        db.delete(product)
        db.commit()
        
        return {"success": True, "message": "Product deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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


@router.put("/products/{product_id}/prices/{price_id}", response_model=schemas.ProductPriceOut)
def update_price(
    product_id: int,
    price_id: int,
    payload: schemas.ProductPriceCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Редактирование цены"""
    product = db.query(Product).filter_by(id=product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    price = db.query(ProductPrice).filter_by(id=price_id, product_id=product_id).first()
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    
    # Если меняется длительность, проверяем на дубликаты
    if payload.duration_days != price.duration_days:
        existing = db.query(ProductPrice).filter_by(
            product_id=product_id, duration_days=payload.duration_days
        ).first()
        if existing and existing.id != price_id:
            raise HTTPException(status_code=400, detail="Price for this duration already exists")
    
    price.duration_days = payload.duration_days
    price.price_rub = payload.price_rub
    db.commit()
    db.refresh(price)
    return price


@router.delete("/products/{product_id}/prices/{price_id}")
def delete_price(
    product_id: int,
    price_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Удаление цены"""
    price = db.query(ProductPrice).filter_by(id=price_id, product_id=product_id).first()
    if not price:
        raise HTTPException(status_code=404, detail="Price not found")
    db.delete(price)
    db.commit()
    return {"success": True}


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
    
    # Проверяем, есть ли уже билд с такой версией
    existing_build = db.query(Build).filter_by(product_id=product_id, label=label).first()
    
    # Деактивируем все старые билды этого продукта
    old_builds = db.query(Build).filter_by(product_id=product_id, is_active=True).all()
    for old_build in old_builds:
        old_build.is_active = False
    
    # Если билд с такой версией существует - удаляем старый файл
    if existing_build:
        if os.path.exists(existing_build.file_path):
            try:
                os.remove(existing_build.file_path)
            except Exception:
                pass  # Игнорируем ошибки удаления
        # Обновляем существующий билд
        file_ext = os.path.splitext(file.filename)[1] or ".zip"
        file_path = os.path.join(uploads_dir, f"{product.slug}_{label}{file_ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        existing_build.file_path = file_path
        existing_build.is_active = True
        db.commit()
        db.refresh(existing_build)
        return existing_build
    else:
        # Создаем новый билд
        file_ext = os.path.splitext(file.filename)[1] or ".zip"
        file_path = os.path.join(uploads_dir, f"{product.slug}_{label}{file_ext}")
        with open(file_path, "wb") as f:
            f.write(file.file.read())
        build = Build(product_id=product_id, label=label, file_path=file_path, is_active=True)
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
        settings_obj = BotSettings(bot_enabled=False, api_enabled=True, maintenance_mode=False)
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
    if payload.api_enabled is not None:
        settings_obj.api_enabled = payload.api_enabled
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


@router.get("/export/data")
def export_data(db: Session = Depends(get_db), _: AdminUser = Depends(get_current_admin)):
    """Экспорт всех данных (пользователи, ключи, продукты)"""
    from fastapi.responses import JSONResponse
    import json
    
    # Экспортируем пользователей
    users = db.query(User).all()
    users_data = [{
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.username,
        "is_admin": u.is_admin,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_seen": u.last_seen.isoformat() if u.last_seen else None,
    } for u in users]
    
    # Экспортируем продукты
    products = db.query(Product).all()
    products_data = []
    for p in products:
        prices = db.query(ProductPrice).filter_by(product_id=p.id).all()
        builds = db.query(Build).filter_by(product_id=p.id).all()
        products_data.append({
            "id": p.id,
            "slug": p.slug,
            "title": p.title,
            "description": p.description,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "prices": [{
                "id": pr.id,
                "duration_days": pr.duration_days,
                "price_rub": pr.price_rub,
            } for pr in prices],
            "builds": [{
                "id": b.id,
                "label": b.label,
                "file_path": b.file_path,
                "is_active": b.is_active,
            } for b in builds],
        })
    
    # Экспортируем ключи
    keys = db.query(Key).all()
    keys_data = [{
        "id": k.id,
        "product_id": k.product_id,
        "value": k.value,
        "duration_days": k.duration_days,
        "status": k.status.value if k.status else None,
        "sold_to_user_id": k.sold_to_user_id,
        "activation_uuid": k.activation_uuid,
        "sold_at": k.sold_at.isoformat() if k.sold_at else None,
        "activated_at": k.activated_at.isoformat() if k.activated_at else None,
        "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    } for k in keys]
    
    export_data = {
        "version": "1.0",
        "exported_at": datetime.utcnow().isoformat(),
        "users": users_data,
        "products": products_data,
        "keys": keys_data,
    }
    
    return JSONResponse(content=export_data)


@router.post("/import/data")
def import_data(
    data: dict,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(get_current_admin),
):
    """Импорт данных (пользователи, ключи, продукты)"""
    from datetime import datetime
    
    imported_counts = {"users": 0, "products": 0, "keys": 0, "errors": []}
    
    try:
        # Импортируем пользователей
        if "users" in data:
            for user_data in data["users"]:
                try:
                    existing = db.query(User).filter_by(telegram_id=user_data["telegram_id"]).first()
                    if not existing:
                        user = User(
                            telegram_id=user_data["telegram_id"],
                            username=user_data.get("username"),
                            is_admin=user_data.get("is_admin", False),
                        )
                        if user_data.get("created_at"):
                            user.created_at = datetime.fromisoformat(user_data["created_at"])
                        if user_data.get("last_seen"):
                            user.last_seen = datetime.fromisoformat(user_data["last_seen"])
                        db.add(user)
                        imported_counts["users"] += 1
                except Exception as e:
                    imported_counts["errors"].append(f"User import error: {e}")
        
        # Импортируем продукты
        if "products" in data:
            for product_data in data["products"]:
                try:
                    existing = db.query(Product).filter_by(slug=product_data["slug"]).first()
                    if not existing:
                        product = Product(
                            slug=product_data["slug"],
                            title=product_data["title"],
                            description=product_data.get("description"),
                            is_active=product_data.get("is_active", True),
                        )
                        if product_data.get("created_at"):
                            product.created_at = datetime.fromisoformat(product_data["created_at"])
                        db.add(product)
                        db.flush()  # Чтобы получить ID продукта
                        
                        # Импортируем цены
                        for price_data in product_data.get("prices", []):
                            price = ProductPrice(
                                product_id=product.id,
                                duration_days=price_data["duration_days"],
                                price_rub=price_data["price_rub"],
                            )
                            db.add(price)
                        
                        imported_counts["products"] += 1
                except Exception as e:
                    imported_counts["errors"].append(f"Product import error: {e}")
        
        # Импортируем ключи
        if "keys" in data:
            for key_data in data["keys"]:
                try:
                    existing = db.query(Key).filter_by(value=key_data["value"]).first()
                    if not existing:
                        key = Key(
                            product_id=key_data["product_id"],
                            value=key_data["value"],
                            duration_days=key_data["duration_days"],
                            status=KeyStatus(key_data["status"]) if key_data.get("status") else KeyStatus.available,
                            sold_to_user_id=key_data.get("sold_to_user_id"),
                            activation_uuid=key_data.get("activation_uuid"),
                        )
                        if key_data.get("sold_at"):
                            key.sold_at = datetime.fromisoformat(key_data["sold_at"])
                        if key_data.get("activated_at"):
                            key.activated_at = datetime.fromisoformat(key_data["activated_at"])
                        if key_data.get("expires_at"):
                            key.expires_at = datetime.fromisoformat(key_data["expires_at"])
                        if key_data.get("created_at"):
                            key.created_at = datetime.fromisoformat(key_data["created_at"])
                        db.add(key)
                        imported_counts["keys"] += 1
                except Exception as e:
                    imported_counts["errors"].append(f"Key import error: {e}")
        
        db.commit()
        
        return {
            "success": True,
            "imported": imported_counts,
            "message": f"Imported {imported_counts['users']} users, {imported_counts['products']} products, {imported_counts['keys']} keys"
        }
    except Exception as e:
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "imported": imported_counts,
        }

