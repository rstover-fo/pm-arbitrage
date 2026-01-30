"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Infrastructure
    redis_url: str = "redis://localhost:6379"
    database_url: str = "postgresql://pm_arb:pm_arb@localhost:5432/pm_arb"

    # API Keys (optional for paper trading)
    anthropic_api_key: str = ""
    polymarket_api_key: str = ""
    polymarket_private_key: str = ""
    kalshi_email: str = ""
    kalshi_password: str = ""

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
