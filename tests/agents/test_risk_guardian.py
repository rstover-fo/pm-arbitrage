"""Tests for Risk Guardian agent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.risk_guardian import RiskGuardianAgent


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
    await guardian._evaluate_request(
        {
            "id": "req-001",
            "opportunity_id": "opp-001",
            "strategy": "test-strategy",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "150",
            "max_price": "0.50",
        }
    )

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
    await guardian._evaluate_request(
        {
            "id": "req-001",
            "opportunity_id": "opp-001",
            "strategy": "test-strategy",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "80",
            "max_price": "0.50",
        }
    )

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is True


@pytest.mark.asyncio
async def test_rejects_trade_exceeding_platform_limit() -> None:
    """Should reject trade that exceeds platform exposure limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.50"),  # High position limit
        platform_limit_pct=Decimal("0.30"),  # 30% = $300 max per platform
    )

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # First trade: $200 to polymarket (within limit)
    await guardian._evaluate_request(
        {
            "id": "req-001",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "200",
            "max_price": "0.50",
        }
    )

    # Second trade: $150 more to polymarket (would exceed $300 limit)
    await guardian._evaluate_request(
        {
            "id": "req-002",
            "market_id": "polymarket:eth-5k",
            "side": "buy",
            "outcome": "YES",
            "amount": "150",
            "max_price": "0.50",
        }
    )

    assert len(decisions) == 2
    assert decisions[0][1]["approved"] is True
    assert decisions[1][1]["approved"] is False
    assert decisions[1][1]["rule_triggered"] == "platform_limit"


@pytest.mark.asyncio
async def test_rejects_trade_when_daily_loss_limit_exceeded() -> None:
    """Should reject trades when daily loss limit is hit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        daily_loss_limit_pct=Decimal("0.05"),  # 5% = $50 max daily loss
    )

    # Simulate $60 loss already today
    guardian._daily_pnl = Decimal("-60")

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Try to trade - should be rejected due to daily loss
    await guardian._evaluate_request(
        {
            "id": "req-001",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.50",
        }
    )

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is False
    assert decisions[0][1]["rule_triggered"] == "daily_loss_limit"


@pytest.mark.asyncio
async def test_resets_daily_loss_on_new_day() -> None:
    """Should reset daily loss tracking at start of new day."""
    from datetime import timedelta

    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        daily_loss_limit_pct=Decimal("0.05"),
    )

    # Simulate loss from yesterday
    guardian._daily_pnl = Decimal("-60")
    guardian._daily_reset_date = (datetime.now(UTC) - timedelta(days=1)).date()

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Trade should be approved - new day resets loss tracking
    await guardian._evaluate_request(
        {
            "id": "req-001",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.50",
        }
    )

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is True


@pytest.mark.asyncio
async def test_halts_system_on_drawdown() -> None:
    """Should halt system when drawdown exceeds limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        drawdown_limit_pct=Decimal("0.20"),  # 20% drawdown limit
    )

    # Simulate: portfolio grew to $1200, then dropped to $900 (25% drawdown)
    guardian._high_water_mark = Decimal("1200")
    guardian._current_value = Decimal("900")

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Any trade should be rejected and system should halt
    await guardian._evaluate_request(
        {
            "id": "req-001",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.50",
        }
    )

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is False
    assert decisions[0][1]["rule_triggered"] == "drawdown_halt"
    assert guardian._halted is True


@pytest.mark.asyncio
async def test_updates_high_water_mark_on_profit() -> None:
    """High water mark should ratchet up with profits."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
    )

    assert guardian._high_water_mark == Decimal("1000")

    # Record profit
    guardian.record_pnl(Decimal("100"))

    assert guardian._current_value == Decimal("1100")
    assert guardian._high_water_mark == Decimal("1100")

    # Record loss
    guardian.record_pnl(Decimal("-50"))

    assert guardian._current_value == Decimal("1050")
    assert guardian._high_water_mark == Decimal("1100")  # Should NOT drop
