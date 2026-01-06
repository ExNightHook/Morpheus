from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from app.models import OrderStatus, KeyStatus


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AdminLogin(BaseModel):
    username: str
    password: str


class ProductPriceOut(BaseModel):
    id: int
    duration_days: int
    price_rub: float

    class Config:
        from_attributes = True


class BuildOut(BaseModel):
    id: int
    label: str
    file_path: str
    is_active: bool

    class Config:
        from_attributes = True


class ProductOut(BaseModel):
    id: int
    slug: str
    title: str
    description: Optional[str]
    is_active: bool
    prices: List[ProductPriceOut] = []
    builds: List[BuildOut] = []

    class Config:
        from_attributes = True


class ProductCreate(BaseModel):
    slug: str
    title: str
    description: Optional[str] = None


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


class ProductPriceCreate(BaseModel):
    duration_days: int
    price_rub: float


class BotSettingsOut(BaseModel):
    bot_enabled: bool
    maintenance_mode: bool
    alert_message: Optional[str]
    technical_message: Optional[str]

    class Config:
        from_attributes = True


class BotSettingsUpdate(BaseModel):
    bot_enabled: Optional[bool] = None
    maintenance_mode: Optional[bool] = None
    alert_message: Optional[str] = None
    technical_message: Optional[str] = None


class KeyOut(BaseModel):
    id: int
    value: str
    duration_days: int
    status: KeyStatus
    activation_uuid: Optional[str]
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class KeysGenerateRequest(BaseModel):
    product_id: int
    duration_days: int
    count: int = Field(gt=0, le=1000)


class KeyUpdate(BaseModel):
    duration_days: Optional[int] = None
    status: Optional[KeyStatus] = None
    activation_uuid: Optional[str] = None
    expires_at: Optional[datetime] = None


class OrderOut(BaseModel):
    id: int
    amount: float
    status: OrderStatus
    payment_url: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class AnypayWebhook(BaseModel):
    status: str
    pay_id: Optional[str]
    transaction_id: Optional[str]
    amount: float
    currency: str
    sign: str


class UserOut(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str]
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True

