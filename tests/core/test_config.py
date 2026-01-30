"""Tests for configuration module."""

import pytest


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should load values from environment variables."""
    monkeypatch.setenv("REDIS_URL", "redis://testhost:6379")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("INITIAL_BANKROLL", "1000")
    monkeypatch.setenv("PAPER_TRADING", "false")

    # Import fresh to pick up env vars
    from pm_arb.core.config import Settings

    settings = Settings()

    assert settings.redis_url == "redis://testhost:6379"
    assert settings.initial_bankroll == 1000
    assert settings.paper_trading is False


def test_settings_has_defaults() -> None:
    """Settings should have sensible defaults."""
    from pm_arb.core.config import Settings

    settings = Settings()

    assert settings.drawdown_limit_pct == 20
    assert settings.daily_loss_limit_pct == 10
    assert settings.paper_trading is True  # Default to safe mode
