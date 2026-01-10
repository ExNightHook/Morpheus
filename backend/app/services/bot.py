import asyncio
import logging
from typing import Optional
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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
from app.services.nicepay import NicepayClient
from app.security import get_password_hash


class BotService:
    def __init__(self):
        token = settings.telegram_bot_token.strip() if settings.telegram_bot_token else ""
        logger.info(f"Bot token length: {len(token)}")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN is empty or not set in .env file")
        
        if ":" not in token:
            logger.error(f"Invalid token format: token should be 'BOT_ID:TOKEN'")
            raise ValueError("TELEGRAM_BOT_TOKEN has invalid format (should be 'BOT_ID:TOKEN')")
        
        try:
            self.bot = Bot(token, parse_mode="HTML")
            self.dp = Dispatcher()
            logger.info("Bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            raise
        
        self.nicepay = NicepayClient()

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
                    .filter(Product.is_active == True)
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
                    .filter(Product.is_active == True)
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
                
                # Проверяем минимальную сумму для СБП (200 рублей)
                if price.price_rub < 200:
                    await call.answer("Минимальная сумма для оплаты составляет 200 рублей", show_alert=True)
                    return
                
                # Получаем доступные методы оплаты
                methods_str = settings.nicepay_methods or "sbp_rub"
                available_methods = [m.strip().lower() for m in methods_str.split(",") if m.strip()]
                
                # Названия методов для отображения
                method_names = {
                    # RUB методы
                    "sbp_rub": "📱 СБП по QR",
                    "sbp": "📱 СБП",
                    "sberbank_rub": "🏦 Сбербанк на карту",
                    "sberbank_account_rub": "🏦 Сбербанк по счёту",
                    "tinkoff_rub": "🏦 Tinkoff",
                    "alfabank_rub": "🏦 Альфа-Банк",
                    "raiffeisen_rub": "🏦 Райффайзен",
                    "vtb_rub": "🏦 ВТБ",
                    "rnkbbank_rub": "🏦 РНКБ Банк",
                    "postbank_rub": "🏦 Почта Банк",
                    "yoomoney_rub": "💵 ЮMoney",
                    "advcash_rub": "💵 AdvCash",
                    "payeer_rub": "💵 Payeer",
                    "unistream_rub": "🏦 UniStream",
                    "rocketbank_rub": "🏦 Рокет Банк",
                    "mobile_rub": "📱 Перевод на мобильную связь",
                    "otpbank_rub": "🏦 ОТП Банк",
                    "rsb_rub": "🏦 Россельхозбанк",
                    "psb_rub": "🏦 Промсвязьбанк",
                    "solidaritybank_rub": "🏦 Солидарность Банк",
                    "card_tj_rub": "💳 По номеру карты (Таджикистан)",
                    "card_kg_rub": "💳 По номеру карты (Кыргызстан)",
                    "card_uz_rub": "💳 По номеру карты (Узбекистан)",
                    # USD методы
                    "paypal_usd": "💳 PayPal (USD)",
                    "advcash_usd": "💵 AdvCash (USD)",
                    "payeer_usd": "💵 Payeer (USD)",
                    # EUR методы
                    "paypal_eur": "💳 PayPal (EUR)",
                    "advcash_eur": "💵 AdvCash (EUR)",
                    "payeer_eur": "💵 Payeer (EUR)",
                    # UAH методы
                    "monobank_uah": "🏦 Monobank (UAH)",
                    "privatbank_uah": "🏦 PrivatBank (UAH)",
                    "raiffeisen_uah": "🏦 Raiffeisen (UAH)",
                    # KZT методы
                    "kaspibank_kzt": "🏦 Kaspi Bank (KZT)",
                    "halykbank_kzt": "🏦 Halyk Bank (KZT)",
                    "jysanbank_kzt": "🏦 Jysan Bank (KZT)",
                    "centercreditbank_kzt": "🏦 CenterCredit Bank (KZT)",
                    "fortebank_kzt": "🏦 ForteBank (KZT)",
                    "advcash_kzt": "💵 AdvCash (KZT)",
                    "berekebank_kzt": "🏦 Bereke Bank (KZT)",
                    "homecreditbank_kzt": "🏦 Home Credit Bank (KZT)",
                    # USDT
                    "nicewallet_usdt": "💵 NiceWallet (USDT)",
                }
                
                buttons = []
                for method in available_methods:
                    method_display = method_names.get(method, method.upper())
                    buttons.append(
                        InlineKeyboardButton(
                            text=method_display,
                            callback_data=f"method:{product.slug}:{price.duration_days}:{method}"
                        )
                    )
                
                # Группируем кнопки по 2 в ряд
                keyboard = []
                for i in range(0, len(buttons), 2):
                    row = buttons[i:i+2]
                    keyboard.append(row)
                keyboard.append([InlineKeyboardButton(text="↩️ Назад", callback_data=f"product:{product.slug}")])
                
                text = (
                    f"<b>{product.title}</b>\n\n"
                    f"📅 Срок: {price.duration_days} дней\n"
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
                
                # Проверяем минимальную сумму для СБП (200 рублей)
                if method and method.lower() in ["sbp_rub", "sbp"] and price.price_rub < 200:
                    await call.answer("Минимальная сумма для оплаты через СБП составляет 200 рублей", show_alert=True)
                    return
                
                method_names = {
                    "sbp_rub": "СБП по QR",
                    "sbp": "СБП",
                    "sberbank_rub": "Сбербанк на карту",
                    "sberbank_account_rub": "Сбербанк по счёту",
                    "tinkoff_rub": "Tinkoff",
                    "alfabank_rub": "Альфа-Банк",
                    "raiffeisen_rub": "Райффайзен",
                    "vtb_rub": "ВТБ",
                    "yoomoney_rub": "ЮMoney",
                    "advcash_rub": "AdvCash",
                    "payeer_rub": "Payeer",
                    "paypal_usd": "PayPal (USD)",
                    "advcash_usd": "AdvCash (USD)",
                    "payeer_usd": "Payeer (USD)",
                    "paypal_eur": "PayPal (EUR)",
                    "advcash_eur": "AdvCash (EUR)",
                    "payeer_eur": "Payeer (EUR)",
                    "monobank_uah": "Monobank (UAH)",
                    "privatbank_uah": "PrivatBank (UAH)",
                    "raiffeisen_uah": "Raiffeisen (UAH)",
                    "kaspibank_kzt": "Kaspi Bank (KZT)",
                    "halykbank_kzt": "Halyk Bank (KZT)",
                    "advcash_kzt": "AdvCash (KZT)",
                    "nicewallet_usdt": "NiceWallet (USDT)",
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
                
                # Проверяем минимальную сумму для СБП (200 рублей)
                if method and method.lower() in ["sbp_rub", "sbp"] and price.price_rub < 200:
                    await call.answer("Минимальная сумма для оплаты через СБП составляет 200 рублей", show_alert=True)
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
                
                # Создаем заказ
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

                desc = f"{product.title} {duration}d / Telegram ID: {user.telegram_id}"
                
                # Генерируем автоматический email для NicePay
                customer_email = f"user_{user.telegram_id}@morpheus.local"
                
                try:
                    # Определяем валюту на основе метода оплаты
                    method_lower = method.lower() if method else ""
                    if method_lower.endswith("_rub"):
                        currency = "RUB"
                        amount = order.amount / 100.0  # Конвертируем рубли в копейки для API
                    elif method_lower.endswith("_usd"):
                        currency = "USD"
                        amount = order.amount / 100.0  # Примерный курс 1 USD = 100 RUB
                    elif method_lower.endswith("_eur"):
                        currency = "EUR"
                        amount = order.amount / 110.0  # Примерный курс 1 EUR = 110 RUB
                    elif method_lower.endswith("_uah"):
                        currency = "UAH"
                        amount = order.amount * 4.0  # Примерный курс 1 RUB = 4 UAH
                    elif method_lower.endswith("_kzt"):
                        currency = "KZT"
                        amount = order.amount * 5.0  # Примерный курс 1 RUB = 5 KZT
                    elif method_lower.endswith("_usdt"):
                        currency = "USD"
                        amount = order.amount / 100.0
                    else:
                        currency = settings.nicepay_currency.upper()
                        amount = order.amount / 100.0  # По умолчанию RUB в копейки
                
                    logger.info(f"Creating payment via NicePay API:")
                    logger.info(f"  Order ID: {order.id}")
                    logger.info(f"  Amount: {amount} {currency}")
                    logger.info(f"  Customer email: {customer_email}")
                    logger.info(f"  Method: {method}")
                    
                    # Создаем платеж через NicePay API
                    payment_result = await self.nicepay.create_payment(
                        order_id=str(order.id),
                        amount=amount,
                        currency=currency,
                        customer=customer_email,  # Автоматически сгенерированный email
                        description=desc,
                        method=method.lower() if method else None,
                        success_url=settings.nicepay_success_url or f"{settings.public_base_url}/success",
                        fail_url=settings.nicepay_fail_url or f"{settings.public_base_url}/fail",
                    )
                    
                    if not payment_result.get("success") or not payment_result.get("link"):
                        raise ValueError(f"Invalid payment response: {payment_result}")
                    
                    payment_url = payment_result["link"]
                    payment_id = payment_result["payment_id"]
                    
                    logger.info(f"Payment created successfully: {payment_url[:100]}...")
                    
                    order.payment_url = payment_url
                    order.provider_pay_id = payment_id
                    order.status = OrderStatus.waiting
                    db.commit()
                    
                    logger.info(f"Order {order.id} created successfully. Key {key.id} remains available until payment confirmation.")
                    
                except Exception as e:
                    # При ошибке платежа - удаляем заказ
                    db.rollback()
                    if order.id:
                        db.delete(order)
                        db.commit()
                    logger.error(f"Payment creation error for order {order.id}: {e}", exc_info=True)
                    error_message = str(e) if str(e) else "Неизвестная ошибка"
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
        env_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        settings_token = settings.telegram_bot_token.strip() if settings.telegram_bot_token else ""
        
        token = env_token if env_token else settings_token
        
        logger.info(f"Token check: env_token length={len(env_token)}, settings_token length={len(settings_token)}")
        
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN not set, bot will not start")
            logger.warning("Please set TELEGRAM_BOT_TOKEN in /opt/Morpheus/.env file and restart container")
            return
        
        if ":" not in token:
            logger.error(f"Invalid token format: token should be 'BOT_ID:TOKEN'")
            logger.error("Please check TELEGRAM_BOT_TOKEN format in .env file")
            return
            
        bot_service = BotService()
        await bot_service.start()
    except ValueError as e:
        logger.error(f"Bot configuration error: {e}")
        logger.error("Please check TELEGRAM_BOT_TOKEN in /opt/Morpheus/.env file")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)