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

    database_url: str = (
        "postgresql+psycopg://crypto:crypto@localhost:5432/crypto_intelligence"
    )
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

    @property
    def tracked_symbol_list(self) -> list[str]:
        return [s.strip().upper() for s in self.tracked_symbols.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
