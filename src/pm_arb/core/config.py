"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Infrastructure (required - set via environment variables)
    redis_url: str
    database_url: str

    # API Keys (optional for paper trading)
    anthropic_api_key: str = ""

    # Polymarket CLOB API credentials (required for live trading)
    polymarket_api_key: str = ""
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""
    polymarket_private_key: str = ""  # Ethereum private key (0x + 64 hex chars)

    # FRED (Federal Reserve Economic Data)
    fred_api_key: str = ""

    # Kalshi API credentials (RSA key-based auth, required for live trading)
    kalshi_api_key_id: str = ""
    kalshi_private_key: str = ""  # RSA PEM-formatted private key

    # Alerts (optional)
    pushover_user_key: str = ""
    pushover_api_token: str = ""

    # Risk Settings
    initial_bankroll: float = 500.0
    drawdown_limit_pct: float = 20.0
    daily_loss_limit_pct: float = 10.0
    position_limit_pct: float = 10.0
    platform_limit_pct: float = 50.0

    # Mode
    paper_trading: bool = True
    log_level: str = "INFO"


# Singleton instance
settings = Settings()
