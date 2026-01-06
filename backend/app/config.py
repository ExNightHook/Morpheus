from pydantic_settings import BaseSettings
from pydantic import Field


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

    # Anypay
    anypay_project_id: str = Field("", env="ANYPAY_PROJECT_ID")
    anypay_api_id: str = Field("", env="ANYPAY_API_ID")
    anypay_api_key: str = Field("", env="ANYPAY_API_KEY")
    anypay_currency: str = Field("RUB", env="ANYPAY_CURRENCY")
    anypay_method: str = Field("card", env="ANYPAY_METHOD")
    anypay_success_url: str = Field("http://localhost/success", env="ANYPAY_SUCCESS_URL")
    anypay_fail_url: str = Field("http://localhost/fail", env="ANYPAY_FAIL_URL")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

