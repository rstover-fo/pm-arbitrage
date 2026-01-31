"""Tests for Strategy Agent base class."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.core.models import OpportunityType


class TestStrategy(StrategyAgent):
    """Concrete test implementation."""

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url, strategy_name="test-strategy")

    def evaluate_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any] | None:
        """Accept all opportunities for testing."""
        return {
            "market_id": opportunity["markets"][0],
            "side": "buy",
            "outcome": "YES",
            "amount": Decimal("10"),
            "max_price": Decimal("0.60"),
        }


@pytest.mark.asyncio
async def test_strategy_subscribes_to_opportunities() -> None:
    """Strategy should subscribe to opportunities channel."""
    strategy = TestStrategy(redis_url="redis://localhost:6379")

    subs = strategy.get_subscriptions()

    assert "opportunities.detected" in subs


@pytest.mark.asyncio
async def test_strategy_generates_trade_request() -> None:
    """Strategy should generate trade request from opportunity."""
    strategy = TestStrategy(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    strategy.publish = capture_publish  # type: ignore[method-assign]
    strategy._allocation_pct = Decimal("0.20")  # 20% allocation
    strategy._total_capital = Decimal("1000")

    await strategy.handle_message(
        "opportunities.detected",
        {
            "id": "opp-001",
            "type": OpportunityType.ORACLE_LAG.value,
            "markets": ["polymarket:btc-100k"],
            "expected_edge": "0.10",
            "signal_strength": "0.80",
            "metadata": {},
        },
    )

    assert len(published) == 1
    assert published[0][0] == "trade.requests"
    assert published[0][1]["strategy"] == "test-strategy"
    assert published[0][1]["opportunity_id"] == "opp-001"
