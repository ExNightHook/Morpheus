import asyncio
import logging
from typing import Callable, Optional
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from sqlalchemy.orm import Session
from datetime import datetime

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger("morpheus.bot")
from app.models import (
    BotSettings,
    Product,
    ProductPrice,
    Key,
    KeyStatus,
    User,
    Order,
    OrderStatus,
    Build,
)
from app.services.anypay import AnypayClient
from app.security import get_password_hash


class BotService:
    def __init__(self):
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is empty")
        self.bot = Bot(settings.telegram_bot_token, parse_mode="HTML")
        self.dp = Dispatcher()
        self.anypay = AnypayClient()

    async def _get_settings(self, db: Session) -> BotSettings:
        settings_obj = db.query(BotSettings).first()
        if not settings_obj:
            settings_obj = BotSettings(bot_enabled=False, maintenance_mode=False)
            db.add(settings_obj)
            db.commit()
            db.refresh(settings_obj)
        return settings_obj

    async def _require_user(self, db: Session, message: Message) -> User:
        user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
        if not user:
            admin_ids = [
                int(x.strip())
                for x in (settings.bot_admins or "").split(",")
                if x.strip().isdigit()
            ]
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username or message.from_user.full_name,
                is_admin=message.from_user.id in admin_ids,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        user.last_seen = datetime.utcnow()
        db.commit()
        return user

    def register_handlers(self):
        dp = self.dp

        @dp.message(Command(commands=["start", "help"]))
        async def cmd_start(message: Message):
            with SessionLocal() as db:
                settings_obj = await self._get_settings(db)
                if not settings_obj.bot_enabled:
                    await message.answer(
                        settings_obj.alert_message or "Бот отключен администратором."
                    )
                    return
                if settings_obj.maintenance_mode:
                    await message.answer(
                        settings_obj.technical_message or "Бот временно недоступен, попробуйте позже."
                    )
                    return
                await self._require_user(db, message)
                await message.answer(
                    "👋 Привет! Добро пожаловать в Morpheus.\n\nНажми '📋 Каталог', чтобы посмотреть продукты.",
                    reply_markup=self.main_menu(),
                )

        @dp.message(F.text == "📋 Каталог")
        async def show_products(message: Message):
            with SessionLocal() as db:
                settings_obj = await self._get_settings(db)
                if not settings_obj.bot_enabled:
                    await message.answer("Бот отключен администратором.")
                    return
                if settings_obj.maintenance_mode:
                    await message.answer("⚠️ Технические работы.")
                    return
                await self._require_user(db, message)
                products = (
                    db.query(Product)
                    .filter(Product.is_active == True)  # noqa: E712
                    .all()
                )
                if not products:
                    await message.answer("Товары временно недоступны.")
                    return
                kb = InlineKeyboardMarkup()
                for p in products:
                    kb.add(
                        InlineKeyboardButton(
                            text=f"🛒 {p.title}", callback_data=f"product:{p.slug}"
                        )
                    )
                await message.answer("Выберите продукт:", reply_markup=kb)

        @dp.callback_query(F.data.startswith("product:"))
        async def product_details(call: CallbackQuery):
            slug = call.data.split(":")[1]
            with SessionLocal() as db:
                settings_obj = await self._get_settings(db)
                if not settings_obj.bot_enabled:
                    await call.answer("Бот отключен", show_alert=True)
                    return
                product = db.query(Product).filter_by(slug=slug).first()
                if not product:
                    await call.answer("Товар не найден", show_alert=True)
                    return
                variants = (
                    db.query(ProductPrice)
                    .filter_by(product_id=product.id)
                    .order_by(ProductPrice.duration_days)
                    .all()
                )
                if not variants:
                    await call.answer("Нет вариантов подписки", show_alert=True)
                    return
                kb = InlineKeyboardMarkup(row_width=2)
                for v in variants:
                    available = (
                        db.query(Key)
                        .filter(
                            Key.product_id == product.id,
                            Key.duration_days == v.duration_days,
                            Key.status == KeyStatus.available,
                        )
                        .count()
                    )
                    if available == 0:
                        continue
                    kb.add(
                        InlineKeyboardButton(
                            text=f"{v.duration_days} дн • {int(v.price_rub)}₽",
                            callback_data=f"buy:{product.slug}:{v.duration_days}",
                        )
                    )
                kb.add(InlineKeyboardButton(text="↩️ Назад", callback_data="back"))
                text = f"<b>{product.title}</b>\n\n{product.description or 'Описание отсутствует.'}"
                await call.message.edit_text(text, reply_markup=kb)

        @dp.callback_query(F.data == "back")
        async def back_to_catalog(call: CallbackQuery):
            await show_products(call.message)

        @dp.callback_query(F.data.startswith("buy:"))
        async def start_payment(call: CallbackQuery):
            _, slug, duration_str = call.data.split(":")
            duration = int(duration_str)
            with SessionLocal() as db:
                settings_obj = await self._get_settings(db)
                if not settings_obj.bot_enabled:
                    await call.answer("Бот отключен", show_alert=True)
                    return
                if settings_obj.maintenance_mode:
                    await call.answer("Технические работы", show_alert=True)
                    return
                user = db.query(User).filter_by(telegram_id=call.from_user.id).first()
                if not user:
                    await call.answer("Перезапустите /start", show_alert=True)
                    return
                product = db.query(Product).filter_by(slug=slug).first()
                price = (
                    db.query(ProductPrice)
                    .filter_by(product_id=product.id, duration_days=duration)
                    .first()
                )
                if not price:
                    await call.answer("Нет цены для выбранной длительности", show_alert=True)
                    return
                key = (
                    db.query(Key)
                    .filter(
                        Key.product_id == product.id,
                        Key.duration_days == duration,
                        Key.status == KeyStatus.available,
                    )
                    .first()
                )
                if not key:
                    await call.answer("Ключи закончились", show_alert=True)
                    return
                key.status = KeyStatus.sold
                key.sold_at = datetime.utcnow()
                db.add(key)

                order = Order(
                    user_id=user.id,
                    product_id=product.id,
                    duration_days=duration,
                    amount=price.price_rub,
                    currency="RUB",
                    status=OrderStatus.pending,
                    key=key,
                )
                db.add(order)
                db.commit()
                db.refresh(order)

                desc = f"{product.title} {duration}d / user {user.telegram_id}"
                try:
                    resp = await self.anypay.create_payment(str(order.id), order.amount, desc)
                    payment_url = resp["result"]["payment_url"]
                    order.payment_url = payment_url
                    order.provider_pay_id = str(resp["result"]["pay_id"])
                    order.status = OrderStatus.waiting
                    db.commit()
                except Exception as e:
                    order.status = OrderStatus.failed
                    db.commit()
                    await call.answer(f"Ошибка создания платежа: {e}", show_alert=True)
                    return

                await call.message.edit_text(
                    f"Подтвердите покупку <b>{product.title}</b> на {duration} дней за {int(order.amount)}₽.\n\n"
                    f"Ссылка на оплату: {order.payment_url}\n\nПосле оплаты дождитесь сообщения с ключом.",
                    reply_markup=InlineKeyboardMarkup().add(
                        InlineKeyboardButton(text="Открыть оплату", url=order.payment_url)
                    ),
                )

    @staticmethod
    def main_menu():
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📋 Каталог")],
            ],
            resize_keyboard=True,
        )
        return kb

    async def send_order_delivery(self, order_id: int):
        with SessionLocal() as db:
            order = db.query(Order).filter_by(id=order_id).first()
            if not order or not order.key:
                return
            user = db.query(User).filter_by(id=order.user_id).first()
            product = db.query(Product).filter_by(id=order.product_id).first()
            build = (
                db.query(Build)
                .filter_by(product_id=product.id, is_active=True)
                .order_by(Build.created_at.desc())
                .first()
            )
            caption = (
                f"✅ Оплата подтверждена!\n\n"
                f"Товар: {product.title}\n"
                f"Ключ: <code>{order.key.value}</code>\n"
                f"Срок: {order.duration_days} дней"
            )
            if build:
                try:
                    await self.bot.send_document(
                        chat_id=user.telegram_id,
                        document=open(build.file_path, "rb"),
                        caption=caption,
                    )
                except Exception:
                    await self.bot.send_message(user.telegram_id, caption)
            else:
                await self.bot.send_message(user.telegram_id, caption)

    async def start(self):
        self.register_handlers()
        await self.dp.start_polling(self.bot)


bot_service: Optional[BotService] = None


async def run_bot():
    global bot_service
    try:
        if not settings.telegram_bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, bot will not start")
            return
        bot_service = BotService()
        await bot_service.start()
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)

