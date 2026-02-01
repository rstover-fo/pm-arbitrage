"""Integration test for detection enhancements."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import Side, TradeRequest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_end_to_end_mispricing_detection() -> None:
    """Full flow: detect mispricing -> generate trade -> risk check."""
    redis_url = "redis://localhost:6379"

    # Create scanner with low thresholds for testing
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.01"),
    )

    # Create risk guardian
    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("500"),
        min_profit_threshold=Decimal("0.05"),
    )

    # Capture detected opportunities
    opportunities: list[dict[str, Any]] = []

    async def capture_opp(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return "mock-id"

    scanner.publish = capture_opp  # type: ignore[method-assign]

    # Simulate mispriced market (YES + NO = 0.85)
    await scanner._handle_venue_price(
        "venue.test.prices",
        {
            "market_id": "polymarket:mispriced",
            "venue": "polymarket",
            "title": "Mispriced Market",
            "yes_price": "0.40",
            "no_price": "0.45",
        },
    )

    # Verify opportunity detected
    mispricing = [o for o in opportunities if o["type"] == "mispricing"]
    assert len(mispricing) >= 1
    assert Decimal(mispricing[0]["expected_edge"]) == Decimal("0.15")

    # Verify risk check would approve a good trade
    good_trade = TradeRequest(
        id="test-001",
        opportunity_id=mispricing[0]["id"],
        strategy="test",
        market_id="polymarket:mispriced",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("10.00"),
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.15"),  # 15% edge on $10 = $1.50 profit
    )

    decision = await guardian._check_rules(good_trade)
    assert decision.approved is True

    # Verify risk check would reject a tiny trade
    tiny_trade = TradeRequest(
        id="test-002",
        opportunity_id=mispricing[0]["id"],
        strategy="test",
        market_id="polymarket:mispriced",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("0.10"),  # $0.10 trade
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.15"),  # 15% edge on $0.10 = $0.015 profit
    )

    decision = await guardian._check_rules(tiny_trade)
    assert decision.approved is False
    assert decision.rule_triggered == "minimum_profit"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_multi_outcome_detection_and_vwap() -> None:
    """Test multi-outcome detection with VWAP calculation."""
    from pm_arb.core.models import OrderBook, OrderBookLevel

    scanner = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.01"),
    )

    opportunities: list[dict[str, Any]] = []

    async def capture_opp(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return "mock-id"

    scanner.publish = capture_opp  # type: ignore[method-assign]

    # Test multi-outcome market with 4 candidates summing to 0.92
    await scanner._handle_multi_outcome_market(
        "venue.test.multi",
        {
            "market_id": "polymarket:multi-test",
            "venue": "polymarket",
            "title": "Multi outcome test",
            "outcomes": [
                {"name": "A", "price": "0.25"},
                {"name": "B", "price": "0.22"},
                {"name": "C", "price": "0.25"},
                {"name": "D", "price": "0.20"},
            ],
        },
    )

    # Should detect 8% edge
    mispricing = [o for o in opportunities if o["type"] == "mispricing"]
    assert len(mispricing) >= 1
    assert mispricing[0]["metadata"]["arb_type"] == "multi_outcome"
    assert Decimal(mispricing[0]["expected_edge"]) == Decimal("0.08")

    # Test VWAP calculation for execution planning
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[
            OrderBookLevel(price=Decimal("0.25"), size=Decimal("500")),
            OrderBookLevel(price=Decimal("0.27"), size=Decimal("500")),
            OrderBookLevel(price=Decimal("0.30"), size=Decimal("1000")),
        ],
    )

    # Calculate VWAP for buying 1000 tokens
    vwap = book.calculate_buy_vwap(Decimal("1000"))
    # 500 @ 0.25 + 500 @ 0.27 = 125 + 135 = 260 / 1000 = 0.26
    assert vwap == Decimal("0.26")

    # Verify liquidity available at price
    liquidity = book.available_liquidity_at_price(Decimal("0.27"), side="buy")
    assert liquidity == Decimal("1000")  # 500 + 500
