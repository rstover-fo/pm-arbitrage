"""Tests for Risk Guardian agent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import Side, TradeRequest


@pytest.mark.asyncio
async def test_guardian_subscribes_to_trade_requests() -> None:
    """Guardian should subscribe to trade request channel."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
    )

    subs = guardian.get_subscriptions()

    assert "trade.requests" in subs
