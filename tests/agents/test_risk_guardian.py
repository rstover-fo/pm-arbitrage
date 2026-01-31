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


@pytest.mark.asyncio
async def test_rejects_trade_exceeding_position_limit() -> None:
    """Should reject trade that exceeds position limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.10"),  # 10% = $100 max per position
    )

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Request $150 trade - exceeds 10% limit
    await guardian._evaluate_request({
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "test-strategy",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "150",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][0] == "trade.decisions"
    assert decisions[0][1]["approved"] is False
    assert decisions[0][1]["rule_triggered"] == "position_limit"


@pytest.mark.asyncio
async def test_approves_trade_within_position_limit() -> None:
    """Should approve trade within position limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.10"),  # 10% = $100 max per position
    )

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Request $80 trade - within 10% limit
    await guardian._evaluate_request({
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "test-strategy",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "80",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is True
