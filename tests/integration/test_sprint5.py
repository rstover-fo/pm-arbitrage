"""Integration test for Sprint 5: End-to-end paper trading flow."""

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import TradeStatus
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy


@pytest.mark.asyncio
async def test_end_to_end_paper_trading() -> None:
    """
    Full flow: Oracle update → Opportunity detected → Strategy generates request →
    Risk Guardian approves → Paper Executor fills → Capital Allocator updates score.
    """
    redis_url = "redis://localhost:6379"

    # Create agents
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.polymarket"],
        oracle_channels=["oracle.binance"],
    )

    strategy = OracleSniperStrategy(
        redis_url=redis_url,
        min_signal=Decimal("0.40"),  # Lower threshold for test
    )
    strategy._allocation_pct = Decimal("0.20")
    strategy._total_capital = Decimal("1000")

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.25"),
    )

    executor = PaperExecutorAgent(redis_url=redis_url)

    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")

    # Track results
    trade_results: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []

    # Wire up message passing (simulating Redis)
    async def scanner_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
            await strategy._handle_opportunity(data)
        return "mock-id"

    async def strategy_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.requests":
            executor._pending_requests[data["id"]] = data
            await guardian._evaluate_request(data)
        return "mock-id"

    async def guardian_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.decisions":
            await executor._process_decision(data)
        return "mock-id"

    async def executor_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            trade_results.append(data)
            await allocator._handle_trade_result(data)
        return "mock-id"

    scanner.publish = scanner_publish  # type: ignore[method-assign]
    strategy.publish = strategy_publish  # type: ignore[method-assign]
    guardian.publish = guardian_publish  # type: ignore[method-assign]
    executor.publish = executor_publish  # type: ignore[method-assign]

    # Register market-oracle mapping
    scanner.register_market_oracle_mapping(
        market_id="polymarket:btc-100k",
        oracle_symbol="BTCUSDT",
        threshold=Decimal("100000"),
        direction="above",
    )

    # Simulate market price update
    await scanner._handle_venue_price(
        "venue.polymarket",
        {
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "title": "Will BTC hit $100k?",
            "yes_price": "0.75",  # Market thinks 75% chance
            "no_price": "0.25",
        },
    )

    # Simulate oracle update showing BTC > $100k
    await scanner._handle_oracle_data(
        "oracle.binance",
        {
            "source": "binance",
            "symbol": "BTCUSDT",
            "value": "105000",  # BTC is at $105k - above threshold!
        },
    )

    # Wait for processing
    await asyncio.sleep(0.1)

    # Verify opportunity was detected
    assert len(opportunities) >= 1
    opp = opportunities[0]
    assert opp["type"] == "oracle_lag"
    assert Decimal(opp["expected_edge"]) > Decimal("0.05")

    # Verify trade was executed
    assert len(trade_results) >= 1
    result = trade_results[0]
    assert result["status"] == TradeStatus.FILLED.value
    assert result["strategy"] == "oracle-sniper"
    assert result["paper_trade"] is True

    # Verify allocator tracked the trade
    perf = allocator.get_strategy_performance("oracle-sniper")
    assert perf["trades"] >= 1

    print(f"\nOpportunities: {opportunities}")
    print(f"Trade results: {trade_results}")
    print(f"Strategy performance: {perf}")
