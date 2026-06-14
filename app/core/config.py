from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    PROJECT_NAME: str = "GestFive API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Security
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./gestfive_dev.db"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_postgres_url(cls, v: str) -> str:
        # Render fournit postgresql:// ; asyncpg exige postgresql+asyncpg://
        if isinstance(v, str) and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # Connection pool (ignoré pour SQLite)
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8080"]
    ALLOWED_HOSTS: List[str] = ["localhost", "gestfive-api.onrender.com"]

    # Pagination
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100

    # Serveur
    PORT: int = 8000
    WORKERS: int = 1
    LOG_LEVEL: str = "info"

    # Paiements
    PAYMENT_CURRENCY: str = "XOF"

    # Orange Money
    ORANGE_MONEY_BASE_URL: str = "https://api.orange.com/orange-money-webpay/dev/v1"
    ORANGE_MONEY_MERCHANT_KEY: str = "dev-om-merchant-key"
    ORANGE_MONEY_WEBHOOK_SECRET: str = "dev-om-webhook-secret"

    # Moov Money
    MOOV_MONEY_BASE_URL: str = "https://api.moov-africa.bj/v1"
    MOOV_MONEY_API_KEY: str = "dev-moov-api-key"
    MOOV_MONEY_WEBHOOK_SECRET: str = "dev-moov-webhook-secret"

    # CinetPay (paiement par carte)
    CARD_PAYMENT_BASE_URL: str = "https://api.cinetpay.com/v2"
    CARD_PAYMENT_API_KEY: str = "dev-card-api-key"
    CARD_PAYMENT_WEBHOOK_SECRET: str = "dev-card-webhook-secret"

    # URLs de retour après paiement carte
    PAYMENT_SUCCESS_URL: str = "http://localhost:3000/payment/success"
    PAYMENT_CANCEL_URL: str = "http://localhost:3000/payment/cancel"

    # Firebase Cloud Messaging
    FIREBASE_ENABLED: bool = False
    FIREBASE_PROJECT_ID: str = "gestfive-dev"
    FIREBASE_CREDENTIALS_PATH: str = ""


settings = Settings()
