"""Tests for Capital Allocator agent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.core.models import TradeStatus


@pytest.mark.asyncio
async def test_allocator_subscribes_to_trade_results() -> None:
    """Allocator should subscribe to trade results channel."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )

    subs = allocator.get_subscriptions()

    assert "trade.results" in subs


@pytest.mark.asyncio
async def test_allocator_tracks_strategy_pnl() -> None:
    """Allocator should track P&L per strategy."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )

    # Register strategies
    allocator.register_strategy("oracle-sniper")
    allocator.register_strategy("cross-arb")

    # Simulate profitable trade for oracle-sniper
    await allocator.handle_message(
        "trade.results",
        {
            "id": "trade-001",
            "request_id": "req-001",
            "strategy": "oracle-sniper",
            "status": TradeStatus.FILLED.value,
            "amount": "100",
            "price": "0.50",
            "pnl": "20",  # $20 profit
            "paper_trade": True,
        },
    )

    performance = allocator.get_strategy_performance("oracle-sniper")
    assert performance["total_pnl"] == Decimal("20")
    assert performance["trades"] == 1
    assert performance["wins"] == 1


@pytest.mark.asyncio
async def test_allocator_updates_allocations() -> None:
    """Allocator should adjust allocations based on performance."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    allocator.publish = capture_publish  # type: ignore[method-assign]

    # Register strategies
    allocator.register_strategy("oracle-sniper")
    allocator.register_strategy("cross-arb")

    # Oracle-sniper wins, cross-arb loses
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("100")
    allocator._strategy_performance["oracle-sniper"]["trades"] = 5
    allocator._strategy_performance["cross-arb"]["total_pnl"] = Decimal("-50")
    allocator._strategy_performance["cross-arb"]["trades"] = 5

    # Trigger reallocation
    await allocator.rebalance_allocations()

    # Oracle-sniper should get more allocation
    oracle_alloc = allocator.get_allocation("oracle-sniper")
    cross_alloc = allocator.get_allocation("cross-arb")

    assert oracle_alloc > cross_alloc
    assert oracle_alloc + cross_alloc <= Decimal("1.0")  # Total <= 100%
