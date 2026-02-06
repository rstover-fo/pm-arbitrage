"""Tests for Paper Executor agent."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.core.models import TradeStatus


@pytest.mark.asyncio
async def test_executor_subscribes_to_decisions() -> None:
    """Executor should subscribe to trade decision channel."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    subs = executor.get_subscriptions()

    assert "trade.decisions" in subs


@pytest.mark.asyncio
async def test_executor_logs_approved_trade() -> None:
    """Executor should publish trade result for approved decisions."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Store the pending request
    executor._pending_requests["req-001"] = {
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "test-strategy",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "50",
        "max_price": "0.55",
    }

    # Process approved decision
    await executor.handle_message(
        "trade.decisions",
        {
            "request_id": "req-001",
            "approved": True,
            "reason": "All rules passed",
        },
    )

    assert len(published) == 1
    assert published[0][0] == "trade.results"
    result = published[0][1]
    assert result["request_id"] == "req-001"
    assert result["status"] == TradeStatus.FILLED.value
    assert Decimal(result["amount"]) == Decimal("50")
    assert result["paper_trade"] is True


@pytest.mark.asyncio
async def test_executor_ignores_rejected_trade() -> None:
    """Executor should not execute rejected trades."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Cache the request first (matches real message flow)
    await executor.handle_message(
        "trade.requests",
        {
            "id": "req-001",
            "opportunity_id": "opp-001",
            "strategy": "test-strategy",
            "market_id": "polymarket:btc-100k",
            "side": "buy",
            "outcome": "YES",
            "amount": "50",
            "max_price": "0.55",
        },
    )

    # Process rejected decision
    await executor.handle_message(
        "trade.decisions",
        {
            "request_id": "req-001",
            "approved": False,
            "reason": "Position limit exceeded",
            "rule_triggered": "position_limit",
        },
    )

    # Should publish rejection result, not a fill
    assert len(published) == 1
    assert published[0][1]["status"] == TradeStatus.REJECTED.value


@pytest.mark.asyncio
async def test_executor_includes_strategy_in_result() -> None:
    """Executor should include strategy name in trade result."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Store pending request with strategy
    executor._pending_requests["req-001"] = {
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "oracle-sniper",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "50",
        "max_price": "0.55",
    }

    await executor.handle_message(
        "trade.decisions",
        {
            "request_id": "req-001",
            "approved": True,
            "reason": "All rules passed",
        },
    )

    assert len(published) == 1
    result = published[0][1]
    assert result["strategy"] == "oracle-sniper"
    assert "pnl" in result  # Should include P&L field
