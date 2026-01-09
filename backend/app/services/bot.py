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
        token = settings.telegram_bot_token.strip() if settings.telegram_bot_token else ""
        logger.info(f"Bot token length: {len(token)}, first 10 chars: {token[:10] if token else 'EMPTY'}...")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is empty or not set in .env file")
        # Проверяем формат токена (должен быть вида "число:строка")
        if ":" not in token:
            logger.error(f"Invalid token format: token should be 'BOT_ID:TOKEN', got: {token[:20]}...")
            raise ValueError("TELEGRAM_BOT_TOKEN has invalid format (should be 'BOT_ID:TOKEN')")
        try:
            self.bot = Bot(token, parse_mode="HTML")
            logger.info("Bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize bot with token: {token[:20]}... Error: {e}")
            raise
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
        try:
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
            else:
                user.last_seen = datetime.utcnow()
                db.commit()
            return user
        except Exception as e:
            logger.error(f"Error in _require_user: {e}", exc_info=True)
            db.rollback()
            # Пытаемся получить пользователя еще раз
            user = db.query(User).filter_by(telegram_id=message.from_user.id).first()
            if user:
                user.last_seen = datetime.utcnow()
                db.commit()
                return user
            raise

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
                buttons = [
                    InlineKeyboardButton(
                        text=f"🛒 {p.title}", callback_data=f"product:{p.slug}"
                    )
                    for p in products
                ]
                kb = InlineKeyboardMarkup(inline_keyboard=[[btn] for btn in buttons])
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
                buttons = []
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
                    buttons.append(
                        InlineKeyboardButton(
                            text=f"{v.duration_days} дн • {int(v.price_rub)}₽",
                            callback_data=f"buy:{product.slug}:{v.duration_days}",
                        )
                    )
                # Группируем кнопки по 2 в ряд
                keyboard = []
                for i in range(0, len(buttons), 2):
                    row = buttons[i:i+2]
                    keyboard.append(row)
                if not buttons:
                    await call.answer("Нет доступных вариантов подписки", show_alert=True)
                    return
                keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back")])
                kb = InlineKeyboardMarkup(inline_keyboard=keyboard)
                text = f"<b>{product.title}</b>\n\n{product.description or 'Описание отсутствует.'}"
                try:
                    await call.message.edit_text(text, reply_markup=kb)
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    await call.message.answer(text, reply_markup=kb)

        @dp.callback_query(F.data == "back")
        async def back_to_catalog(call: CallbackQuery):
            with SessionLocal() as db:
                settings_obj = await self._get_settings(db)
                if not settings_obj.bot_enabled:
                    await call.answer("Бот отключен", show_alert=True)
                    return
                if settings_obj.maintenance_mode:
                    await call.answer("⚠️ Технические работы.")
                    return
                products = (
                    db.query(Product)
                    .filter(Product.is_active == True)  # noqa: E712
                    .all()
                )
                if not products:
                    try:
                        await call.message.edit_text("Товары временно недоступны.")
                    except Exception:
                        await call.message.answer("Товары временно недоступны.")
                    return
                buttons = [
                    InlineKeyboardButton(
                        text=f"🛒 {p.title}", callback_data=f"product:{p.slug}"
                    )
                    for p in products
                ]
                kb = InlineKeyboardMarkup(inline_keyboard=[[btn] for btn in buttons])
                try:
                    await call.message.edit_text("Выберите продукт:", reply_markup=kb)
                except Exception:
                    await call.message.answer("Выберите продукт:", reply_markup=kb)

        @dp.callback_query(F.data.startswith("buy:"))
        async def select_payment_method(call: CallbackQuery):
            """Шаг 1: Выбор метода оплаты"""
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
                if not product:
                    await call.answer("Товар не найден", show_alert=True)
                    return
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
                
                # Получаем доступные методы оплаты
                methods_str = settings.anypay_methods or "ym,btc,eth,qiwi"
                available_methods = [m.strip().lower() for m in methods_str.split(",") if m.strip()]
                
                # Названия методов для отображения
                method_names = {
                    "ym": "💳 ЮMoney",
                    "btc": "₿ Bitcoin",
                    "eth": "Ξ Ethereum",
                    "qiwi": "💸 Qiwi",
                    "card": "💳 Банковская карта",
                    "sbp": "📱 СБП",
                    "usdt": "💵 USDT",
                    "ltc": "Ł Litecoin",
                }
                
                buttons = []
                for method in available_methods:
                    method_display = method_names.get(method, method.upper())
                    buttons.append(
                        InlineKeyboardButton(
                            text=method_display,
                            callback_data=f"method:{slug}:{duration}:{method}"
                        )
                    )
                
                # Группируем кнопки по 2 в ряд
                keyboard = []
                for i in range(0, len(buttons), 2):
                    row = buttons[i:i+2]
                    keyboard.append(row)
                keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"product:{slug}")])
                
                text = (
                    f"<b>{product.title}</b>\n\n"
                    f"📅 Срок: {duration} дней\n"
                    f"💰 Сумма: {int(price.price_rub)}₽\n\n"
                    f"Выберите метод оплаты:"
                )
                
                try:
                    await call.message.edit_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                    )
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    await call.message.answer(
                        text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                    )

        @dp.callback_query(F.data.startswith("method:"))
        async def confirm_payment(call: CallbackQuery):
            """Шаг 2: Подтверждение покупки"""
            _, slug, duration_str, method = call.data.split(":")
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
                if not product:
                    await call.answer("Товар не найден", show_alert=True)
                    return
                price = (
                    db.query(ProductPrice)
                    .filter_by(product_id=product.id, duration_days=duration)
                    .first()
                )
                if not price:
                    await call.answer("Нет цены для выбранной длительности", show_alert=True)
                    return
                
                method_names = {
                    "ym": "ЮMoney",
                    "btc": "Bitcoin",
                    "eth": "Ethereum",
                    "qiwi": "Qiwi",
                    "card": "Банковская карта",
                    "sbp": "СБП",
                    "usdt": "USDT",
                    "ltc": "Litecoin",
                }
                method_display = method_names.get(method.lower(), method.upper())
                
                text = (
                    f"<b>Подтверждение покупки</b>\n\n"
                    f"📦 Товар: {product.title}\n"
                    f"📅 Срок: {duration} дней\n"
                    f"💰 Сумма: {int(price.price_rub)}₽\n"
                    f"💳 Метод оплаты: {method_display}\n\n"
                    f"Подтвердите покупку:"
                )
                
                keyboard = [
                    [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm:{slug}:{duration}:{method}")],
                    [InlineKeyboardButton(text="❌ Отмена", callback_data=f"product:{slug}")]
                ]
                
                try:
                    await call.message.edit_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                    )
                except Exception as e:
                    logger.error(f"Error editing message: {e}")
                    await call.message.answer(
                        text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
                    )

        @dp.callback_query(F.data.startswith("confirm:"))
        async def create_payment(call: CallbackQuery):
            """Шаг 3: Создание платежа"""
            _, slug, duration_str, method = call.data.split(":")
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
                if not product:
                    await call.answer("Товар не найден", show_alert=True)
                    return
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
                
                # Создаем заказ БЕЗ изменения статуса ключа
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
                    # Создаем URL для оплаты через SCI (не API!)
                    logger.info(f"Creating payment URL via SCI for order {order.id}, amount {order.amount}, method {method}")
                    payment_url = self.anypay.create_payment_url(
                        str(order.id), 
                        order.amount, 
                        desc,
                        email=f"user_{user.telegram_id}@morpheus.local",
                        method=method.lower()
                    )
                    
                    if not payment_url or not payment_url.startswith("https://anypay.io/merchant"):
                        raise ValueError(f"Invalid payment URL generated: {payment_url}")
                    
                    logger.info(f"Payment URL created successfully: {payment_url[:100]}...")
                    
                    order.payment_url = payment_url
                    order.provider_pay_id = str(order.id)  # Используем order.id как pay_id
                    order.status = OrderStatus.waiting
                    # Только после успешного создания платежа меняем статус ключа
                    key.status = KeyStatus.sold
                    key.sold_at = datetime.utcnow()
                    key.sold_to_user_id = user.id
                    db.commit()
                    logger.info(f"Order {order.id} created successfully, key {key.id} marked as sold")
                except Exception as e:
                    # При ошибке платежа - удаляем заказ и НЕ меняем статус ключа
                    db.rollback()
                    if order.id:
                        db.delete(order)
                        db.commit()
                    logger.error(f"Payment creation error for order {order.id}: {e}", exc_info=True)
                    error_message = str(e) if str(e) else "Неизвестная ошибка"
                    # Убираем упоминание "Anypay API error" из сообщения, так как мы используем SCI
                    if "Anypay API error" in error_message:
                        error_message = "Ошибка создания платежа. Попробуйте позже или выберите другой метод оплаты."
                    await call.answer(f"Ошибка создания платежа: {error_message}", show_alert=True)
                    return

                try:
                    await call.message.edit_text(
                        f"✅ <b>Платеж создан!</b>\n\n"
                        f"📦 Товар: {product.title}\n"
                        f"📅 Срок: {duration} дней\n"
                        f"💰 Сумма: {int(order.amount)}₽\n\n"
                        f"Перейдите по ссылке для оплаты:\n{order.payment_url}\n\n"
                        f"После успешной оплаты вы получите ключ и файл.",
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", url=order.payment_url)]]
                        ),
                    )
                except Exception as e:
                    logger.error(f"Error editing payment message: {e}")
                    await call.message.answer(
                        f"✅ <b>Платеж создан!</b>\n\n"
                        f"📦 Товар: {product.title}\n"
                        f"📅 Срок: {duration} дней\n"
                        f"💰 Сумма: {int(order.amount)}₽\n\n"
                        f"Перейдите по ссылке для оплаты:\n{order.payment_url}\n\n"
                        f"После успешной оплаты вы получите ключ и файл.",
                        reply_markup=InlineKeyboardMarkup(
                            inline_keyboard=[[InlineKeyboardButton(text="💳 Перейти к оплате", url=order.payment_url)]]
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
        import os
        # Проверяем токен из переменных окружения напрямую
        env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        settings_token = settings.telegram_bot_token.strip() if settings.telegram_bot_token else ""
        
        # Используем токен из переменных окружения, если он есть, иначе из settings
        token = env_token if env_token else settings_token
        
        logger.info(f"Token check: env_token length={len(env_token)}, settings_token length={len(settings_token)}")
        
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, bot will not start")
            logger.warning("Please set TELEGRAM_BOT_TOKEN in /opt/Morpheus/.env file and restart container")
            return
        
        # Проверяем формат токена
        if ":" not in token:
            logger.error(f"Invalid token format: token should be 'BOT_ID:TOKEN', got: {token[:20]}...")
            logger.error("Please check TELEGRAM_BOT_TOKEN format in .env file")
            return
            
        bot_service = BotService()
        await bot_service.start()
    except ValueError as e:
        logger.error(f"Bot configuration error: {e}")
        logger.error("Please check TELEGRAM_BOT_TOKEN in /opt/Morpheus/.env file")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)

