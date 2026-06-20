from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Guilua"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = Field(default="dev-only-change-me")
    database_url: str = "sqlite:///./guilua.db"
    use_sqlite: bool = True
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]
    session_cookie_name: str = "guilua_session"
    session_cookie_secure: bool = False
    session_max_age_seconds: int = 60 * 60 * 24 * 7
    session_remember_max_age_seconds: int = 60 * 60 * 24 * 30
    password_reset_token_max_age_seconds: int = 60 * 60

    default_locale: str = "vi"
    supported_locales: Annotated[list[str], NoDecode] = ["vi", "zh-TW"]

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
    member_registration_enabled: bool = True
    member_portal_enabled: bool = True

    crypto_market_live_enabled: bool = True
    crypto_market_cache_seconds: int = 180
    crypto_market_timeout_seconds: float = 2.5
    coingecko_api_url: str = "https://api.coingecko.com/api/v3/simple/price"
    coingecko_api_key: str | None = None
    binance_api_url: str = "https://api.binance.com/api/v3/ticker/24hr"
    google_adsense_client: str | None = None
    google_adsense_slot: str | None = None
    google_adsense_publisher_id: str | None = None
    google_site_verification: str | None = None

    ai_agent_api_enabled: bool = True
    ai_agent_default_post_status: str = "draft"
    ai_agent_allow_autopublish: bool = False
    upload_max_mb: int = 5
    upload_storage_backend: str = "local"
    public_base_url: str = "http://127.0.0.1:8000"
    vpn_download_url: str | None = None
    vpn_setup_guide_url: str | None = None
    shopee_affiliate_disclosure_enabled: bool = True

    exchange_rate_provider_url: str | None = None
    live_rate_timeout_seconds: float = 2.5
    ip_service_provider_url: str | None = None
    ip_service_provider_api_key: str | None = None
    ip_service_provider_timeout_seconds: float = 5.0

    security_dashboard_enabled: bool = True
    security_logging_enabled: bool = True
    security_firewall_enabled: bool = True
    security_auto_block_enabled: bool = False
    security_log_retention_days: int = 30
    security_rate_limit_enabled: bool = True
    security_rate_limit_window_seconds: int = 60
    security_rate_limit_max_requests: int = 120
    security_login_rate_limit_window_seconds: int = 300
    security_login_rate_limit_max_attempts: int = 10
    security_admin_rate_limit_max_requests: int = 80
    security_agent_api_rate_limit_max_requests: int = 60
    security_auto_block_threshold: int = 50
    security_auto_block_minutes: int = 60
    security_geoip_enabled: bool = True
    security_geoip_provider: str = "none"
    security_geoip_api_url: str | None = None
    security_geoip_api_key: str | None = None
    security_geoip_cache_hours: int = 24
    security_ip_allowlist: Annotated[list[str], NoDecode] = []
    security_ip_blocklist: Annotated[list[str], NoDecode] = []
    security_country_allowlist: Annotated[list[str], NoDecode] = []
    security_country_blocklist: Annotated[list[str], NoDecode] = []
    security_trusted_proxy_headers: bool = True
    security_notify_on_high_risk: bool = True
    security_alert_email: str | None = None
    security_block_suspicious_payloads: bool = False
    security_log_suspicious_payloads: bool = True
    security_honeypot_enabled: bool = True
    security_admin_ip_restriction_enabled: bool = False
    security_admin_ip_allowlist: Annotated[list[str], NoDecode] = []

    @field_validator(
        "allowed_hosts",
        "supported_locales",
        "security_ip_allowlist",
        "security_ip_blocklist",
        "security_country_allowlist",
        "security_country_blocklist",
        "security_admin_ip_allowlist",
        mode="before",
    )
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
