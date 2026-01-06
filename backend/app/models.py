import enum
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.database import Base


class OrderStatus(str, enum.Enum):
    pending = "pending"
    waiting = "waiting"
    paid = "paid"
    failed = "failed"
    cancelled = "cancelled"


class KeyStatus(str, enum.Enum):
    available = "available"
    sold = "sold"
    activated = "activated"
    expired = "expired"


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)


class BotSettings(Base):
    __tablename__ = "bot_settings"
    id = Column(Integer, primary_key=True, default=1)
    bot_enabled = Column(Boolean, default=False)
    maintenance_mode = Column(Boolean, default=False)
    alert_message = Column(Text, nullable=True)
    technical_message = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(150))
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    orders = relationship("Order", back_populates="user")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    prices = relationship("ProductPrice", back_populates="product", cascade="all, delete-orphan")
    builds = relationship("Build", back_populates="product", cascade="all, delete-orphan")
    keys = relationship("Key", back_populates="product", cascade="all, delete-orphan")


class ProductPrice(Base):
    __tablename__ = "product_prices"
    __table_args__ = (UniqueConstraint("product_id", "duration_days", name="uq_product_duration"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"))
    duration_days = Column(Integer, nullable=False)
    price_rub = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="prices")


class Build(Base):
    __tablename__ = "builds"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"))
    label = Column(String(100), nullable=False)
    file_path = Column(String(300), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="builds")


class Key(Base):
    __tablename__ = "keys"

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    value = Column(String(100), unique=True, nullable=False, index=True)
    duration_days = Column(Integer, nullable=False)
    status = Column(Enum(KeyStatus), default=KeyStatus.available)
    sold_to_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    activation_uuid = Column(String(120), nullable=True)
    sold_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="keys")
    sold_to_user = relationship("User")
    order = relationship("Order", back_populates="key")

    def activate(self, uuid: str):
        self.activation_uuid = uuid
        if not self.expires_at:
            self.expires_at = datetime.utcnow() + timedelta(days=self.duration_days)
        if not self.activated_at:
            self.activated_at = datetime.utcnow()
        self.status = KeyStatus.activated


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    duration_days = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="RUB")
    provider = Column(String(30), default="anypay")
    provider_pay_id = Column(String(50), nullable=True)
    payment_url = Column(String(400), nullable=True)
    status = Column(Enum(OrderStatus), default=OrderStatus.pending)
    key_id = Column(Integer, ForeignKey("keys.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="orders")
    product = relationship("Product")
    key = relationship("Key", back_populates="order")

