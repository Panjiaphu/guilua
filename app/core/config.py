from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'Guilua Timeblock AI Assistant'
    app_env: str = 'development'
    debug: bool = True
    secret_key: str = Field(default='dev-only-change-me')
    deployment_version: str = Field(
        default_factory=lambda: os.getenv('RENDER_GIT_COMMIT', '').strip() or 'development'
    )
    public_base_url: str = 'http://127.0.0.1:8000'
    timeblock_app_url: str = 'http://127.0.0.1:5000'
    default_locale: str = 'vi'
    supported_locales: tuple[str, ...] = ('vi', 'zh-TW', 'en')

    timeblock_api_url: str | None = None
    timeblock_api_key: str | None = None
    guilua_client_id: str = 'guilua'
    guilua_session_cookie: str = 'guilua_session'
    guilua_pending_authorization_cookie: str = 'guilua_auth_nonce'
    guilua_session_ttl_seconds: int = Field(default=14400, ge=300, le=86400)
    guilua_pending_authorization_ttl_seconds: int = Field(default=120, ge=60, le=600)
    guilua_session_max_entries: int = Field(default=10000, ge=100, le=100000)
    guilua_pending_authorization_max_entries: int = Field(default=2000, ge=100, le=20000)
    guilua_authorization_start_rate_limit_count: int = Field(default=12, ge=2, le=120)
    guilua_authorization_start_rate_limit_window_seconds: int = Field(
        default=60, ge=10, le=300
    )
    allow_missing_bff_origin: bool = True
    timeblock_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    timeblock_proxy_timeout_seconds: float = Field(default=120.0, gt=1, le=300)
    allow_development_session_fallback: bool = False
    messaging_realtime_enabled: bool = True
    messaging_mailbox_lock_enabled: bool = True
    messaging_advanced_attachments_enabled: bool = True

    # Group voice translation is fail-closed until the owner explicitly
    # enables it and supplies the server-only OpenAI key in Render.
    group_translation_enabled: bool = False
    openai_api_key: str | None = None
    openai_realtime_translation_model: str = 'gpt-realtime-translate'
    openai_realtime_transcription_model: str = 'gpt-realtime-whisper'
    openai_group_transcription_model: str = 'gpt-4o-mini-transcribe'
    openai_text_translation_model: str = 'gpt-4.1-mini'
    group_translation_max_targets: int = Field(default=2, ge=1, le=3)
    group_translation_client_secret_ttl_seconds: int = Field(default=60, ge=10, le=300)
    group_translation_reservation_ttl_seconds: int = Field(default=300, ge=60, le=900)
    group_translation_max_segment_seconds: int = Field(default=300, ge=1, le=900)
    group_translation_max_audio_bytes: int = Field(default=5 * 1024 * 1024, ge=64 * 1024, le=25 * 1024 * 1024)
    group_translation_monthly_audio_target_seconds: int = Field(
        default=3600, ge=60, le=10_000_000
    )
    group_translation_monthly_video_target_seconds: int = Field(
        default=1800, ge=60, le=10_000_000
    )
    # 0 records requester-funded Chat cost without inventing a commercial cap.
    # A future approved package can set a positive monthly variant allowance.
    group_chat_translation_monthly_variant_limit: int = Field(
        default=0, ge=0, le=10_000_000
    )
    group_translation_policy_version: str = 'group-translation-v3-2026-08-31'
    group_v3_enabled: bool = False
    group_handoff_audience: str = 'ai-communication-group-v3'
    group_handoff_max_bytes: int = Field(default=8192, ge=1024, le=65536)
    database_url: str = 'sqlite:///./.data/ai-communication.db'
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=40)
    group_message_encryption_key: str | None = None
    group_attachment_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    group_invitation_ttl_seconds: int = Field(default=7 * 24 * 60 * 60, ge=300, le=30 * 24 * 60 * 60)
    group_media_enabled: bool = False
    group_livekit_url: str | None = None
    group_livekit_api_key: str | None = None
    group_livekit_api_secret: str | None = None
    group_livekit_region: str = 'Singapore'
    group_livekit_token_ttl_seconds: int = Field(default=300, ge=60, le=600)
    group_media_max_participants: int = Field(default=8, ge=2, le=50)
    group_radio_floor_lease_seconds: int = Field(default=15, ge=5, le=120)
    group_radio_v3_enabled: bool = False
    group_radio_redis_url: str | None = None
    group_radio_redis_namespace: str = 'ai-communication:group-radio:v3'
    group_radio_heartbeat_seconds: int = Field(default=5, ge=1, le=30)
    group_radio_device_lost_seconds: int = Field(default=10, ge=3, le=60)
    group_radio_max_burst_seconds: int = Field(default=30, ge=5, le=300)
    group_radio_max_rooms: int = Field(default=20, ge=1, le=1000)

    allowed_websocket_origins: str = 'http://127.0.0.1:8000,http://localhost:8000'
    allowed_timeblock_handoff_origins: str = 'http://127.0.0.1:5000,http://localhost:5000'
    allow_missing_websocket_origin: bool = True
    websocket_auth_timeout_seconds: float = Field(default=5.0, gt=0.5, le=30)
    max_auth_event_bytes: int = Field(default=16384, ge=1024, le=65536)
    connection_stale_seconds: int = Field(default=120, ge=10, le=3600)
    reconnect_token_seconds: int = Field(default=300, ge=30, le=3600)
    ended_session_cache_seconds: int = Field(default=600, ge=30, le=86400)
    idempotency_cache_seconds: int = Field(default=1800, ge=60, le=86400)
    max_room_participants: int = Field(default=2, ge=2, le=2)
    max_event_bytes: int = Field(default=131072, ge=1024, le=1048576)
    event_rate_limit_count: int = Field(default=120, ge=10, le=1000)
    event_rate_limit_window_seconds: int = Field(default=60, ge=1, le=300)
    signaling_rate_limit_count: int = Field(default=40, ge=5, le=500)
    heartbeat_rate_limit_count: int = Field(default=20, ge=2, le=120)

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == 'production' or not self.debug

    @property
    def development_session_fallback_enabled(self) -> bool:
        return (
            not self.is_production
            and self.app_env.strip().lower() in {'development', 'test'}
            and self.allow_development_session_fallback
            and not self.timeblock_api_url
        )

    @property
    def websocket_origins(self) -> set[str]:
        return {item.strip().rstrip('/') for item in self.allowed_websocket_origins.split(',') if item.strip()}

    @property
    def timeblock_handoff_origins(self) -> set[str]:
        return {item.strip().rstrip('/') for item in self.allowed_timeblock_handoff_origins.split(',') if item.strip()}

    @property
    def primary_timeblock_handoff_origin(self) -> str:
        configured = self.timeblock_app_url.strip().rstrip('/')
        return configured if configured in self.timeblock_handoff_origins else sorted(self.timeblock_handoff_origins)[0] if self.timeblock_handoff_origins else configured

    @property
    def development_query_handoff_enabled(self) -> bool:
        return self.development_session_fallback_enabled

    @model_validator(mode='before')
    @classmethod
    def prefer_render_commit_identity(cls, values):
        """Use Render's immutable source identity when it is available.

        ``DEPLOYMENT_VERSION`` is retained for local and non-Render deployments,
        but a stale manually pinned value must never override the commit that
        Render actually deployed.  Render exposes that identity through
        ``RENDER_GIT_COMMIT`` at runtime.
        """
        render_sha = os.getenv('RENDER_GIT_COMMIT', '').strip()
        if not render_sha or not isinstance(values, dict):
            return values
        if len(render_sha) < 40 or len(render_sha) > 64 or any(
            character not in '0123456789abcdefABCDEF' for character in render_sha
        ):
            return values
        normalized = dict(values)
        normalized['deployment_version'] = render_sha
        return normalized

    @model_validator(mode='after')
    def validate_production_settings(self):
        if not self.guilua_session_cookie.strip() or not self.guilua_pending_authorization_cookie.strip():
            raise ValueError('GUILUA session and pending cookie names must be non-empty')
        if self.guilua_session_cookie == self.guilua_pending_authorization_cookie:
            raise ValueError('GUILUA session and pending cookie names must be distinct')
        if self.is_production and self.secret_key in {'', 'change-me', 'dev-only-change-me'}:
            raise ValueError('SECRET_KEY must be set to a strong value in production')
        if self.is_production and self.allow_development_session_fallback:
            raise ValueError('ALLOW_DEVELOPMENT_SESSION_FALLBACK must be false in production')
        if self.is_production and self.allow_missing_bff_origin:
            self.allow_missing_bff_origin = False
        if self.is_production and self.allow_missing_websocket_origin:
            self.allow_missing_websocket_origin = False
        if self.is_production and not self.websocket_origins:
            raise ValueError('ALLOWED_WEBSOCKET_ORIGINS must be configured in production')
        if self.is_production and not self.timeblock_handoff_origins:
            raise ValueError('ALLOWED_TIMEBLOCK_HANDOFF_ORIGINS must be configured in production')
        if not self.group_handoff_audience.strip():
            raise ValueError('GROUP_HANDOFF_AUDIENCE must be non-empty')
        if self.is_production and self.group_v3_enabled:
            if self.database_url.strip().lower().startswith('sqlite'):
                raise ValueError('DATABASE_URL must use PostgreSQL when GROUP_V3_ENABLED is true in production')
            if not self.group_message_encryption_key:
                raise ValueError('GROUP_MESSAGE_ENCRYPTION_KEY is required when GROUP_V3_ENABLED is true in production')
            if self.group_media_enabled:
                if not all((self.group_livekit_url, self.group_livekit_api_key, self.group_livekit_api_secret)):
                    raise ValueError('Group LiveKit configuration is required when GROUP_MEDIA_ENABLED is true')
                if self.group_livekit_region != 'Singapore':
                    raise ValueError('GROUP_LIVEKIT_REGION must remain Singapore')
                if self.group_livekit_token_ttl_seconds != 300:
                    raise ValueError('GROUP_LIVEKIT_TOKEN_TTL_SECONDS must remain 300')
            if self.group_translation_enabled and not self.openai_api_key:
                raise ValueError('OPENAI_API_KEY is required when GROUP_TRANSLATION_ENABLED is true')
            if self.group_radio_v3_enabled:
                if not self.group_media_enabled:
                    raise ValueError('GROUP_MEDIA_ENABLED must be true when GROUP_RADIO_V3_ENABLED is true')
                radio_url = str(self.group_radio_redis_url or '')
                if not radio_url.startswith(('redis://', 'rediss://')):
                    raise ValueError('GROUP_RADIO_REDIS_URL is required when GROUP_RADIO_V3_ENABLED is true')
                if self.group_radio_floor_lease_seconds <= self.group_radio_heartbeat_seconds * 2:
                    raise ValueError('GROUP_RADIO_FLOOR_LEASE_SECONDS must exceed two heartbeat intervals')
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
