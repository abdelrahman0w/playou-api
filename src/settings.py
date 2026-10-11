import tempfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel
from pydantic import Field
from pydantic import SecretStr
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict
from sqlalchemy import URL

from src.structs.enums.together import TogetherEffects
from src.structs.enums.together import TogetherReasons


VERSION_FILE = Path(__file__).parent.parent / "VERSION"


def _built_version() -> str | None:
    if VERSION_FILE.is_file():
        return VERSION_FILE.read_text().strip() or None

    return None


class Environment(StrEnum):
    DEV = "DEV"
    PROD = "PROD"


class BaseAppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        frozen=True,
        env_file=".env",
        env_file_encoding="utf-8",
        validate_default=True,
        extra="ignore",
    )


class AppSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
    )

    environment: Environment = Environment.DEV
    version: str | None = Field(default_factory=_built_version)
    log_level: str = "INFO"
    log_json: bool = True
    web_url: str = "http://127.0.0.1:5173"


class DatabaseSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="DATABASE_",
    )

    host: str
    port: int = 5432
    user: str
    password: SecretStr
    name: str
    pool_size: int = Field(default=5, ge=1)
    max_overflow: int = Field(default=3, ge=0)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)
    pool_recycle_seconds: int = Field(default=30 * 60, ge=-1)
    pool_pre_ping: bool = True

    @property
    def url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


class RedisSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
    )

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: SecretStr | None = None
    cache_ttl_seconds: int = Field(default=300, ge=1)
    timeout_seconds: float = Field(default=1.0, gt=0)
    connect_timeout_seconds: float = Field(default=1.0, gt=0)
    retries: int = Field(default=1, ge=0)
    health_check_seconds: int = Field(default=30, ge=0)
    max_connections: int = Field(default=100, ge=1)


class ErrorTrackingSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="ERROR_TRACKING_",
    )

    dsn: SecretStr | None = None
    traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    logs_enabled: bool = False


class RateLimitSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="RATE_LIMIT_",
    )

    enabled: bool = True
    requests: int = Field(default=120, ge=1)
    window_seconds: int = Field(default=60, ge=1)
    timeout_seconds: float = Field(default=0.5, gt=0)
    client_ip_header: str = "CF-Connecting-IP"


class CorsSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="CORS_",
    )

    origins: list[str] = Field(default_factory=list)
    max_age_seconds: int = Field(default=7200, ge=0)


class AuthSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
    )

    secret: SecretStr | None = None
    session_days: int = Field(default=30, ge=1)
    session_refresh_hours: int = Field(default=24, ge=1)
    session_cache_seconds: int = Field(default=300, ge=1)
    cookie_name: str = "playou_session"
    cookie_secure: bool = True
    code_minutes: int = Field(default=10, ge=1)
    code_attempts: int = Field(default=5, ge=1)
    code_cooldown_seconds: int = Field(default=60, ge=1)
    codes_per_email_hour: int = Field(default=5, ge=1)
    codes_per_ip_hour: int = Field(default=20, ge=1)
    verifications_per_ip_hour: int = Field(default=30, ge=1)
    name_changes: int = Field(default=2, ge=1)
    name_change_days: int = Field(default=30, ge=1)


class ResendSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="RESEND_",
    )

    api_key: SecretStr | None = None
    sender: str = "PlaYou <no-reply@abdosworld.com>"
    base_url: str = "https://api.resend.com"
    timeout_seconds: float = Field(default=10.0, gt=0)


class EncryptionSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="ENCRYPTION_",
    )

    keys: list[SecretStr] = Field(default_factory=list)


class AccountsSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACCOUNTS_",
    )

    link_minutes: int = Field(default=10, ge=1)
    refresh_margin_seconds: int = Field(default=60, ge=0)
    keep_alive_days: int = Field(default=14, ge=1)
    keep_alive_batch_size: int = Field(default=500, ge=1)
    expiry_warning_days: int = Field(default=7, ge=1)
    forget_disconnected: bool = True
    forget_disconnected_days: int = Field(default=7, ge=1)


class SearchSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="SEARCH_",
    )

    platform_timeout_seconds: float = Field(default=5.0, gt=0)
    cache_seconds: int = Field(default=60, ge=1)
    shared_cache_seconds: int = Field(default=24 * 60 * 60, ge=1)


class CatalogSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="CATALOG_",
    )

    match_across_scripts: bool = False
    copy_batch_size: int = Field(default=25, ge=1, le=200)
    candidates_seconds: int = Field(default=60 * 60, ge=60)


class SyncSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNC_",
    )

    push_batch_size: int = Field(default=100, ge=1)
    max_attempts: int = Field(default=8, ge=1)
    retry_seconds: int = Field(default=30, ge=1)
    longest_retry_seconds: int = Field(default=60 * 60, ge=1)
    reconnect_retry_seconds: int = Field(default=60 * 60, ge=1)
    lease_seconds: int = Field(default=60, ge=3)
    retention_days: int = Field(default=30, ge=1)


class ImportSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="IMPORT_",
    )

    stale_minutes: int = Field(default=10, ge=1)
    check_seconds: int = Field(default=60, ge=1)
    cooldown_seconds: int = Field(default=60, ge=0)
    every_minutes: int = Field(default=30, ge=1)
    full_every_hours: int = Field(default=24, ge=1)
    lease_minutes: int = Field(default=15, ge=1)
    batch_size: int = Field(default=10, ge=1)
    schedule_batch_size: int = Field(default=500, ge=1)


class WorkerSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKER_",
    )

    concurrency: int = Field(default=4, ge=1)
    push_concurrency: int = Field(default=4, ge=1)
    sweep_seconds: int = Field(default=15, ge=1)
    heartbeat_seconds: int = Field(default=5, ge=1)
    wait_seconds: int = Field(default=5, ge=1)
    stop_seconds: int = Field(default=45, ge=0)
    health_file: Path | None = Field(
        default_factory=lambda: Path(tempfile.gettempdir()) / "playou-worker-alive",
    )


class SpotifySettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPOTIFY_",
    )

    client_id: str | None = None
    redirect_uri: str = "http://127.0.0.1:8081/accounts/spotify/callback"
    scopes: list[str] = Field(
        default_factory=lambda: [
            "user-read-email",
            "user-read-private",
            "user-library-read",
            "user-library-modify",
            "playlist-read-private",
            "playlist-read-collaborative",
            "playlist-modify-private",
            "playlist-modify-public",
            "streaming",
            "user-read-playback-state",
            "user-modify-playback-state",
        ],
    )
    refresh_token_days: int | None = Field(default=180, ge=1)
    search_max_limit: int = Field(default=10, ge=1, le=50)
    rate_limit_seconds: int = Field(default=30, ge=1)
    copy_searches: int = Field(default=4, ge=1)
    accounts_url: str = "https://accounts.spotify.com"
    api_url: str = "https://api.spotify.com/v1"
    timeout_seconds: float = Field(default=10.0, gt=0)


class YouTubeSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="YOUTUBE_",
    )

    client_id: str | None = None
    client_secret: SecretStr | None = None
    api_key: SecretStr | None = None
    redirect_uri: str = "http://127.0.0.1:8081/accounts/youtube/callback"
    scopes: list[str] = Field(
        default_factory=lambda: [
            "openid",
            "https://www.googleapis.com/auth/youtube",
        ],
    )
    search_on_demand: bool = True
    daily_quota: int = Field(default=10_000, ge=0)
    daily_push_units: int = Field(default=1_000, ge=0)
    daily_find_units: int = Field(default=1_000, ge=0)
    copy_likes: bool = False
    background_play: bool = False
    refresh_token_days: int | None = Field(default=None, ge=1)
    rate_limit_seconds: int = Field(default=30, ge=1)
    copy_searches: int = Field(default=2, ge=1)
    accounts_url: str = "https://accounts.google.com"
    oauth_url: str = "https://oauth2.googleapis.com"
    userinfo_url: str = "https://openidconnect.googleapis.com/v1"
    api_url: str = "https://www.googleapis.com/youtube/v3"
    timeout_seconds: float = Field(default=10.0, gt=0)


class DataSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="DATA_",
    )

    deletion_enabled: bool = True


class PlaybackSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="PLAYBACK_",
    )

    session_days: int = Field(default=30, ge=1)
    longest_wait_seconds: int = Field(default=20, ge=0)


class LyricsSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="LYRICS_",
    )

    enabled: bool = True
    lrclib_url: str = "https://lrclib.net/api"
    timeout_seconds: float = Field(default=5.0, gt=0)
    found_days: int = Field(default=90, ge=1)
    missing_days: int = Field(default=14, ge=1)
    hidden_days: int = Field(default=30, ge=1)
    reports_per_user_hour: int = Field(default=5, ge=1)
    hide_after_reports: int = Field(default=0, ge=0)


class MessagesSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="MESSAGES_",
    )

    per_minute: int = Field(default=120, ge=1)
    per_day: int = Field(default=170000, ge=1)
    longest_wait_seconds: int = Field(default=20, ge=0)
    push_public_key: str | None = None
    push_private_key: SecretStr | None = None
    push_contact: str = "mailto:notifications@abdosworld.com"
    push_timeout_seconds: float = Field(default=10.0, gt=0)

    @property
    def push_enabled(self) -> bool:
        return bool(
            self.push_public_key
            and self.push_private_key
            and self.push_private_key.get_secret_value(),
        )


class SharesSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="SHARES_",
    )

    per_user_hour: int = Field(default=60, ge=1)
    public_cache_seconds: int = Field(default=300, ge=0)
    image_cache_days: int = Field(default=7, ge=1)
    image_max_age_seconds: int = Field(default=24 * 60 * 60, ge=0)


class TogetherGroup(BaseModel):
    emails: list[str] = Field(min_length=2)
    effect: TogetherEffects = TogetherEffects.HEARTS

    @field_validator("emails")
    @classmethod
    def fold_emails(cls, emails: list[str]) -> list[str]:
        return [email.strip().casefold() for email in emails]

    @field_validator("effect", mode="before")
    @classmethod
    def upper_effect(cls, effect: object) -> object:
        return effect.upper() if isinstance(effect, str) else effect


class TogetherSettings(BaseAppSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOGETHER_",
    )

    groups: list[TogetherGroup] = Field(default_factory=list)
    reasons: list[TogetherReasons] = Field(
        default_factory=lambda: list(TogetherReasons)
    )

    @field_validator("reasons", mode="before")
    @classmethod
    def upper_reasons(cls, reasons: object) -> object:
        if not isinstance(reasons, list):
            return reasons

        return [
            reason.upper() if isinstance(reason, str) else reason for reason in reasons
        ]


class Settings(BaseAppSettings):
    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    error_tracking: ErrorTrackingSettings = Field(
        default_factory=ErrorTrackingSettings,
    )
    auth: AuthSettings = Field(default_factory=AuthSettings)
    resend: ResendSettings = Field(default_factory=ResendSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)
    encryption: EncryptionSettings = Field(default_factory=EncryptionSettings)
    accounts: AccountsSettings = Field(default_factory=AccountsSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    catalog: CatalogSettings = Field(default_factory=CatalogSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    imports: ImportSettings = Field(default_factory=ImportSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    spotify: SpotifySettings = Field(default_factory=SpotifySettings)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    playback: PlaybackSettings = Field(default_factory=PlaybackSettings)
    shares: SharesSettings = Field(default_factory=SharesSettings)
    lyrics: LyricsSettings = Field(default_factory=LyricsSettings)
    messages: MessagesSettings = Field(default_factory=MessagesSettings)
    together: TogetherSettings = Field(default_factory=TogetherSettings)


settings = Settings()
