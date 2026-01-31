"""Tests for Oracle Sniper strategy."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.core.models import OpportunityType
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy


@pytest.mark.asyncio
async def test_oracle_sniper_accepts_oracle_lag() -> None:
    """Should accept oracle lag opportunities with sufficient edge."""
    strategy = OracleSniperStrategy(redis_url="redis://localhost:6379")

    opportunity = {
        "id": "opp-001",
        "type": OpportunityType.ORACLE_LAG.value,
        "markets": ["polymarket:btc-100k"],
        "oracle_source": "binance",
        "oracle_value": "105000",
        "expected_edge": "0.15",
        "signal_strength": "0.85",
        "metadata": {
            "threshold": "100000",
            "direction": "above",
            "fair_yes_price": "0.95",
            "current_yes_price": "0.80",
        },
    }

    trade_params = strategy.evaluate_opportunity(opportunity)

    assert trade_params is not None
    assert trade_params["market_id"] == "polymarket:btc-100k"
    assert trade_params["side"] == "buy"
    assert trade_params["outcome"] == "YES"
    assert trade_params["max_price"] == Decimal("0.80")  # Current price


@pytest.mark.asyncio
async def test_oracle_sniper_rejects_cross_platform() -> None:
    """Should reject non-oracle-lag opportunities."""
    strategy = OracleSniperStrategy(redis_url="redis://localhost:6379")

    opportunity = {
        "id": "opp-002",
        "type": OpportunityType.CROSS_PLATFORM.value,
        "markets": ["polymarket:btc-100k", "kalshi:btc-100k"],
        "expected_edge": "0.10",
        "signal_strength": "0.70",
        "metadata": {},
    }

    trade_params = strategy.evaluate_opportunity(opportunity)

    assert trade_params is None


@pytest.mark.asyncio
async def test_oracle_sniper_sizes_by_signal() -> None:
    """Should size position based on signal strength."""
    strategy = OracleSniperStrategy(
        redis_url="redis://localhost:6379",
        max_position_pct=Decimal("1.0"),  # Use full allocation for test
    )
    strategy._allocation_pct = Decimal("0.20")
    strategy._total_capital = Decimal("1000")

    # High signal = larger position
    opportunity = {
        "id": "opp-001",
        "type": OpportunityType.ORACLE_LAG.value,
        "markets": ["polymarket:btc-100k"],
        "expected_edge": "0.20",
        "signal_strength": "0.90",  # 90% confidence
        "metadata": {
            "fair_yes_price": "0.95",
            "current_yes_price": "0.75",
        },
    }

    trade_params = strategy.evaluate_opportunity(opportunity)

    # Max position = 1000 * 0.20 = 200
    # Signal scaling: 200 * 0.90 = 180
    assert trade_params is not None
    assert trade_params["amount"] == Decimal("180")
