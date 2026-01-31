"""Integration test for Sprint 4: Risk Guardian + Paper Executor."""

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import TradeStatus


@pytest.mark.asyncio
async def test_opportunity_to_paper_trade_flow() -> None:
    """Full flow: opportunity detected → trade request → risk check → paper execution."""
    redis_url = "redis://localhost:6379"

    # Create agents
    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.20"),
    )

    executor = PaperExecutorAgent(redis_url=redis_url)

    # Track results
    trade_results: list[dict[str, Any]] = []

    original_executor_publish = executor.publish

    async def capture_results(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            trade_results.append(data)
        return await original_executor_publish(channel, data)

    executor.publish = capture_results  # type: ignore[method-assign]

    # Start agents
    guardian_task = asyncio.create_task(guardian.run())
    executor_task = asyncio.create_task(executor.run())

    await asyncio.sleep(0.2)

    # Simulate trade request (normally from Strategy agent)
    trade_request = {
        "id": "req-test-001",
        "opportunity_id": "opp-001",
        "strategy": "oracle-sniper",
        "market_id": "polymarket:btc-100k-jan",
        "side": "buy",
        "outcome": "YES",
        "amount": "50",
        "max_price": "0.55",
    }

    # Store request in executor and send to guardian
    executor._pending_requests["req-test-001"] = trade_request
    await guardian._evaluate_request(trade_request)

    # Wait for processing
    await asyncio.sleep(0.5)

    # Stop agents
    await guardian.stop()
    await executor.stop()
    await asyncio.gather(guardian_task, executor_task, return_exceptions=True)

    # Verify paper trade was executed
    assert len(trade_results) >= 1

    # Find the filled trade
    filled = [r for r in trade_results if r.get("status") == TradeStatus.FILLED.value]
    assert len(filled) == 1
    assert filled[0]["request_id"] == "req-test-001"
    assert filled[0]["paper_trade"] is True
    assert Decimal(filled[0]["amount"]) == Decimal("50")

    print(f"\nTrade results: {trade_results}")
