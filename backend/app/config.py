import logging
from pydantic_settings import BaseSettings
from pydantic import Field

logger = logging.getLogger("morpheus.config")


class Settings(BaseSettings):
    postgres_user: str = Field("morpheus", env="POSTGRES_USER")
    postgres_password: str = Field("morpheus", env="POSTGRES_PASSWORD")
    postgres_db: str = Field("morpheus", env="POSTGRES_DB")
    postgres_host: str = Field("db", env="POSTGRES_HOST")
    postgres_port: int = Field(5432, env="POSTGRES_PORT")

    secret_key: str = Field("please_change_me", env="SECRET_KEY")
    access_token_expire_minutes: int = Field(60 * 24, env="ACCESS_TOKEN_EXPIRE_MINUTES")

    telegram_bot_token: str = Field("", env="TELEGRAM_BOT_TOKEN")
    # список ID админов, разделённых запятой; парсинг делаем вручную
    bot_admins: str = Field("", env="BOT_ADMINS")

    public_base_url: str = Field("https://localhost", env="PUBLIC_BASE_URL")

    # NicePay
    nicepay_merchant_id: str = Field("", env="NICEPAY_MERCHANT_ID")
    nicepay_secret_key: str = Field("", env="NICEPAY_SECRET_KEY")
    nicepay_currency: str = Field("USD", env="NICEPAY_CURRENCY")
    # Список доступных методов оплаты, разделенных запятой (например: "paypal_usd,advcash_usd")
    nicepay_methods: str = Field("paypal_usd", env="NICEPAY_METHODS")
    nicepay_success_url: str = Field("", env="NICEPAY_SUCCESS_URL")
    nicepay_fail_url: str = Field("", env="NICEPAY_FAIL_URL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Логируем загруженные настройки (без секретных данных)
logger.debug(f"Loaded settings: POSTGRES_HOST={settings.postgres_host}, PUBLIC_BASE_URL={settings.public_base_url}")
logger.debug(f"TELEGRAM_BOT_TOKEN length: {len(settings.telegram_bot_token)}, first 10 chars: {settings.telegram_bot_token[:10] if settings.telegram_bot_token else 'EMPTY'}...")
