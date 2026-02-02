"""Integration test for execution flow.

Tests the full pipeline: detect opportunity → risk check → execute trade.
"""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus, Side, TradeRequest


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_full_execution_flow(mock_credentials: PolymarketCredentials) -> None:
    """Full flow: detect opportunity → risk check → execute trade."""
    redis_url = "redis://localhost:6379"

    # Create agents
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.05"),
        min_signal_strength=Decimal("0.01"),
    )

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("500"),
        min_profit_threshold=Decimal("0.05"),
    )

    executor = LiveExecutorAgent(
        redis_url=redis_url,
        credentials={"polymarket": mock_credentials},
    )

    # Track messages through the system
    opportunities: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    async def capture_scanner(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return "msg-id"

    async def capture_guardian(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.decisions":
            decisions.append(data)
        return "msg-id"

    async def capture_executor(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            results.append(data)
        return "msg-id"

    scanner.publish = capture_scanner  # type: ignore[method-assign]
    guardian.publish = capture_guardian  # type: ignore[method-assign]
    executor.publish = capture_executor  # type: ignore[method-assign]

    # Mock order execution
    mock_order = MagicMock()
    mock_order.external_id = "order-123"
    mock_order.status = OrderStatus.FILLED
    mock_order.filled_amount = Decimal("10")
    mock_order.average_price = Decimal("0.45")
    mock_order.error_message = None

    # Step 1: Detect opportunity (mispriced market)
    # YES + NO = 0.40 + 0.50 = 0.90 → 10% edge
    await scanner._handle_venue_price(
        "venue.test.prices",
        {
            "market_id": "polymarket:arb-test",
            "venue": "polymarket",
            "title": "Test Market",
            "yes_price": "0.40",
            "no_price": "0.50",  # Sum = 0.90, 10% edge
        },
    )

    assert len(opportunities) == 1
    opp = opportunities[0]
    assert opp["type"] == "mispricing"
    assert Decimal(opp["expected_edge"]) == Decimal("0.10")

    # Step 2: Risk check passes
    trade_request = TradeRequest(
        id="req-001",
        opportunity_id=opp["id"],
        strategy="test",
        market_id="polymarket:arb-test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("10"),
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.10"),
    )

    decision = await guardian._check_rules(trade_request)
    assert decision.approved is True

    # Step 3: Execute trade
    with patch.object(executor, "_get_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.place_order.return_value = mock_order
        mock_get.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-001",
                "market_id": "polymarket:arb-test",
                "token_id": "token-yes",
                "side": "buy",
                "amount": "10",
                "max_price": "0.45",
            }
        )

    # Verify result
    assert len(results) == 1
    assert results[0]["status"] == "filled"
    assert results[0]["filled_amount"] == "10"


@pytest.mark.asyncio
async def test_risk_rejection_stops_execution(mock_credentials: PolymarketCredentials) -> None:
    """When risk guardian rejects, execution should not happen."""
    redis_url = "redis://localhost:6379"

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("100"),  # Small bankroll
        position_limit_pct=Decimal("0.10"),  # 10% = $10 max per position
        min_profit_threshold=Decimal("0.05"),
    )

    # Request $50 trade - exceeds 10% position limit
    trade_request = TradeRequest(
        id="req-002",
        opportunity_id="opp-002",
        strategy="test",
        market_id="polymarket:test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("50"),  # Too large
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.10"),
    )

    decision = await guardian._check_rules(trade_request)

    assert decision.approved is False
    assert decision.rule_triggered == "position_limit"


@pytest.mark.asyncio
async def test_multi_outcome_arbitrage_detection() -> None:
    """Detect arbitrage in multi-outcome markets where sum < 1."""
    scanner = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.test.multi"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.05"),
        min_signal_strength=Decimal("0.01"),
    )

    opportunities: list[dict[str, Any]] = []

    async def capture(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return "msg-id"

    scanner.publish = capture  # type: ignore[method-assign]

    # Multi-outcome market with prices summing to 0.85 (15% edge)
    await scanner._handle_multi_outcome_market(
        "venue.test.multi",
        {
            "market_id": "polymarket:election",
            "venue": "polymarket",
            "title": "Who wins?",
            "outcomes": [
                {"name": "Candidate A", "price": "0.30"},
                {"name": "Candidate B", "price": "0.25"},
                {"name": "Candidate C", "price": "0.15"},
                {"name": "Candidate D", "price": "0.15"},
            ],
        },
    )

    assert len(opportunities) == 1
    assert opportunities[0]["type"] == "mispricing"
    assert Decimal(opportunities[0]["expected_edge"]) == Decimal("0.15")


@pytest.mark.asyncio
async def test_slippage_guard_in_flow(mock_credentials: PolymarketCredentials) -> None:
    """Slippage guard should reject trades with thin liquidity."""
    from pm_arb.core.models import OrderBook, OrderBookLevel

    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("500"),
    )

    # Thin order book
    order_book = OrderBook(
        market_id="polymarket:test",
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("5")),
            OrderBookLevel(price=Decimal("0.80"), size=Decimal("100")),
        ],
    )

    # Large order that will incur slippage
    request = TradeRequest(
        id="req-003",
        opportunity_id="opp-003",
        strategy="test",
        market_id="polymarket:test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("50"),  # Will need to fill into expensive 2nd level
        max_price=Decimal("0.55"),
        expected_edge=Decimal("0.10"),
    )

    decision = await guardian._check_slippage(request, order_book)

    assert decision.approved is False
    assert decision.rule_triggered == "slippage_guard"


@pytest.mark.asyncio
async def test_executor_handles_adapter_failure(mock_credentials: PolymarketCredentials) -> None:
    """Executor should report failure when adapter throws."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[dict[str, Any]] = []

    async def capture(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            results.append(data)
        return "msg-id"

    executor.publish = capture  # type: ignore[method-assign]

    with patch.object(executor, "_get_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.place_order.side_effect = Exception("Connection refused")
        mock_get.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-fail",
                "market_id": "polymarket:test",
                "token_id": "token-abc",
                "side": "buy",
                "amount": "10",
                "max_price": "0.50",
            }
        )

    assert len(results) == 1
    assert results[0]["status"] == "rejected"
    assert "Connection refused" in results[0]["error"]
