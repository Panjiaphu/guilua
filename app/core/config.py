from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Guilua"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = Field(default="dev-only-change-me")
    database_url: str = "sqlite:///./guilua.db"
    use_sqlite: bool = True
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    session_cookie_name: str = "guilua_session"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 60 * 60 * 24 * 7

    default_locale: str = "vi"
    supported_locales: list[str] = ["vi", "zh-TW"]

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str = "no-reply@guilua.local"
    smtp_use_tls: bool = True
    email_webhook_api_key: str | None = None
    admin_notification_email: str | None = "panjiaphu@gmail.com"
    admin_line_id: str = "@827sxbki"
    admin_phone: str = "0906938893"
    admin_seed_email: str = "panjiaphu@gmail.com"
    admin_seed_password: str | None = None

    exchange_rate_provider_url: str | None = None
    live_rate_timeout_seconds: float = 2.5

    @field_validator("allowed_hosts", "supported_locales", mode="before")
    @classmethod
    def parse_csv(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("secret_key")
    @classmethod
    def require_secret_length(cls, value):
        weak = {"", "change-me", "dev-only-change-me"}
        if value in weak:
            return value
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_production_defaults(self):
        if self.is_production and self.secret_key in {"", "change-me", "dev-only-change-me"}:
            raise ValueError("SECRET_KEY must be set to a strong value when DEBUG=false or APP_ENV=production")
        if self.is_production and self.admin_seed_password and len(self.admin_seed_password) < 14:
            raise ValueError("ADMIN_SEED_PASSWORD must be at least 14 characters in production")
        if self.use_sqlite:
            self.database_url = "sqlite:///./guilua.db"
        elif self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production" or not self.debug


@lru_cache
def get_settings() -> Settings:
    return Settings()
