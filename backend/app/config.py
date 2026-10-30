from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    No secret has a production default. Values are read from a local
    ``.env`` file during development and from the deployment environment
    in production. The ``.env`` file itself is never committed.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "crypto-intelligence-backend"
    environment: str = "development"
    debug: bool = False

    database_url: str = "postgresql+psycopg://crypto:crypto@localhost:5432/crypto_intelligence"
    redis_url: str = "redis://localhost:6379/0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60

    telegram_bot_token: str | None = None
    telegram_group_id: str | None = None

    binance_spot_base_url: str = "https://api.binance.com"
    binance_futures_base_url: str = "https://fapi.binance.com"
    # Public market data only; no API key is required for the Phase 2
    # endpoints. Where api.binance.com is restricted by location, the
    # spot base URL can be pointed at https://data-api.binance.vision
    # instead, without changing any client code.
    binance_request_timeout_seconds: float = 10.0
    binance_max_retries: int = 3
    tracked_symbols: str = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT"

    # Announcement monitoring (Phase 3). The base URL is the
    # official Binance website; the CMS endpoint below is the
    # website's own announcement feed, not a documented public
    # API, so it is labelled as such in the documentation.
    binance_announcements_base_url: str = "https://www.binance.com"
    binance_announcements_endpoint: str = "/bapi/composite/v1/public/cms/article/list/query"
    announcement_polling_interval_seconds: int = 300
    # Comma-separated categories to notify about. Empty means
    # all categories. See docs/ANNOUNCEMENT_MONITOR.md.
    announcement_notification_categories: str = ""
    # Phase 4 intelligence processing interval, in seconds.
    intelligence_processing_interval_seconds: int = 600

    # Phase 6 competition volume tracker. The scheduler
    # interval is 30 minutes to match the interval
    # boundaries; only completed intervals are ever
    # collected, so APScheduler not firing exactly on
    # :00/:30 is safe. Backfill is capped per pair per
    # run to bound Binance API usage. Volume Telegram
    # reports follow the Phase 3 pattern: they are sent
    # only when this flag is on AND a bot token and
    # group id are configured; without them, sending is
    # skipped (not marked sent) and live delivery stays
    # unverified.
    volume_tracking_interval_minutes: int = 30
    volume_backfill_max_intervals_per_pair: int = 48
    volume_max_pages_per_interval: int = 50
    volume_notifications_enabled: bool = True

    # Phase 7 market, futures, and news intelligence.
    # Market snapshot and news/listing jobs run every 5
    # minutes; funding every 5 minutes; open interest
    # every 15 minutes; movement detection every 5
    # minutes. Gainers/losers exclude symbols below the
    # minimum 24h quote volume, so low-liquidity tokens
    # are never presented as reliable opportunities.
    # An alert fires once per symbol + alert type per
    # cooldown window. Market data older than the
    # freshness window is flagged stale in API output.
    market_snapshot_interval_minutes: int = 5
    market_min_quote_volume_usdt: int = 1000000
    market_alert_cooldown_minutes: int = 60
    market_price_alert_threshold_percent: float = 5.0
    market_volume_spike_multiplier: float = 2.0
    market_freshness_minutes: int = 10
    futures_funding_interval_minutes: int = 5
    futures_open_interest_interval_minutes: int = 15
    futures_funding_alert_threshold: float = 0.001
    news_collection_interval_minutes: int = 5
    market_notifications_enabled: bool = True

    # Phase 8 administration and security. Sessions are
    # server-side only: the browser holds an opaque session
    # token in an HttpOnly cookie, never a long-lived access
    # token in localStorage. The CSRF token lives in a
    # separate non-HttpOnly cookie and must be echoed back
    # as X-CSRF-Token on state-changing requests.
    session_inactivity_minutes: int = 60
    session_absolute_hours: int = 12
    session_cookie_name: str = "admin_session"
    csrf_cookie_name: str = "admin_csrf"
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    login_rate_limit_per_minute: int = 30
    password_reset_token_minutes: int = 60
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65536
    argon2_parallelism: int = 4
    # Base64-encoded 32-byte AES-GCM key for credential
    # encryption at rest. No default: production startup
    # fails without it (see the validator below), and in
    # non-production credential writes fail clearly.
    credential_encryption_key: str | None = None
    credential_encryption_key_previous: str | None = None
    # Stable key-version identifiers (Phase 9 audit fix).
    # Rows keep the key id they were encrypted under, so
    # rotation never orphans existing credentials: rotate
    # by giving the new key a new id and moving the old id
    # to credential_encryption_key_previous_id. The legacy
    # ids "current" and "previous" are still honoured on
    # decrypt for rows written before this change.
    credential_encryption_key_id: str = "v1"
    credential_encryption_key_previous_id: str | None = None
    dashboard_refresh_interval_seconds: int = 60

    @model_validator(mode="after")
    def _validate_production_secret(self):
        if self.environment == "production" and (
            not self.secret_key or self.secret_key == "change-me-in-production"
        ):
            raise ValueError("SECRET_KEY must be set to a real value when ENVIRONMENT=production")
        if self.environment == "production" and not self.credential_encryption_key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY must be set when ENVIRONMENT=production")
        # A malformed key must fail fast in every
        # environment, not only at first credential write:
        # a key that is set but does not decode to 32
        # bytes can never encrypt or decrypt anything.
        for _label, _value in (
            ("CREDENTIAL_ENCRYPTION_KEY", self.credential_encryption_key),
            ("CREDENTIAL_ENCRYPTION_KEY_PREVIOUS", self.credential_encryption_key_previous),
        ):
            if _value:
                import base64 as _base64

                try:
                    _decoded = _base64.b64decode(_value, validate=True)
                except Exception as exc:
                    raise ValueError(f"{_label} is not valid base64") from exc
                if len(_decoded) != 32:
                    raise ValueError(f"{_label} must decode to 32 bytes")
        return self

    @property
    def tracked_symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.tracked_symbols.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
