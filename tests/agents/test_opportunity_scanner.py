"""Tests for Opportunity Scanner agent."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.core.models import Market, OpportunityType


@pytest.mark.asyncio
async def test_scanner_subscribes_to_channels() -> None:
    """Scanner should subscribe to venue and oracle channels."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
    )

    subs = agent.get_subscriptions()

    assert "venue.polymarket.prices" in subs
    assert "oracle.binance.BTC" in subs


@pytest.mark.asyncio
async def test_detects_oracle_lag_opportunity() -> None:
    """Should detect when PM price lags behind oracle price movement."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
        min_edge_pct=Decimal("0.01"),  # 1% edge threshold
    )

    # Register a crypto market that tracks BTC price
    agent.register_market_oracle_mapping(
        market_id="polymarket:btc-above-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),  # Market: "Will BTC be above $100k?"
        direction="above",
    )

    # Simulate: BTC jumps to $105k but market still prices YES at 50%
    # This is a buying opportunity - BTC is already above threshold
    published = []
    original_publish = agent.publish

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Feed oracle data showing BTC at $105k
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {
            "source": "binance",
            "symbol": "BTC",
            "value": "105000",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # Feed market data showing YES still at 50%
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {
            "market_id": "polymarket:btc-above-100k",
            "venue": "polymarket",
            "title": "Will BTC be above $100k?",
            "yes_price": "0.50",
            "no_price": "0.50",
        },
    )

    # Should detect opportunity
    assert len(published) == 1
    assert published[0][0] == "opportunities.detected"
    opp = published[0][1]
    assert opp["type"] == OpportunityType.ORACLE_LAG.value
    assert Decimal(opp["expected_edge"]) > Decimal("0.40")  # ~45% edge (should be ~95% not 50%)


@pytest.mark.asyncio
async def test_detects_cross_platform_opportunity() -> None:
    """Should detect price discrepancy between matched markets on different venues."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices", "venue.kalshi.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.03"),  # 3% edge threshold
        min_signal_strength=Decimal("0.1"),
    )

    # Register two markets as tracking the same event
    agent.register_matched_markets(
        market_ids=["polymarket:btc-100k-jan", "kalshi:btc-100k-jan"],
        event_id="btc-100k-jan-2026",
    )

    published = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Polymarket has YES at 60%
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {
            "market_id": "polymarket:btc-100k-jan",
            "venue": "polymarket",
            "title": "BTC above $100k in Jan?",
            "yes_price": "0.60",
            "no_price": "0.40",
        },
    )

    # Kalshi has YES at 52% - 8% discrepancy
    await agent._handle_venue_price(
        "venue.kalshi.prices",
        {
            "market_id": "kalshi:btc-100k-jan",
            "venue": "kalshi",
            "title": "BTC above $100k in Jan?",
            "yes_price": "0.52",
            "no_price": "0.48",
        },
    )

    # Should detect cross-platform opportunity
    assert len(published) == 1
    assert published[0][0] == "opportunities.detected"
    opp = published[0][1]
    assert opp["type"] == OpportunityType.CROSS_PLATFORM.value
    assert len(opp["markets"]) == 2
    assert Decimal(opp["expected_edge"]) >= Decimal("0.03")


@pytest.mark.asyncio
async def test_signal_strength_increases_with_edge() -> None:
    """Signal strength should increase with larger edge."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.1"),
    )

    agent.register_market_oracle_mapping(
        market_id="polymarket:btc-above-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),
        direction="above",
    )

    published = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Test 1: BTC at $110k (10% above threshold) - high signal
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {"source": "binance", "symbol": "BTC", "value": "110000", "timestamp": datetime.now(UTC).isoformat()},
    )
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {"market_id": "polymarket:btc-above-100k", "venue": "polymarket", "title": "BTC>100k", "yes_price": "0.50", "no_price": "0.50"},
    )

    high_edge_signal = Decimal(published[0][1]["signal_strength"])

    # Test 2: BTC at $102k (2% above threshold) - lower signal
    published.clear()
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {"source": "binance", "symbol": "BTC", "value": "102000", "timestamp": datetime.now(UTC).isoformat()},
    )
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {"market_id": "polymarket:btc-above-100k", "venue": "polymarket", "title": "BTC>100k", "yes_price": "0.50", "no_price": "0.50"},
    )

    low_edge_signal = Decimal(published[0][1]["signal_strength"])

    assert high_edge_signal > low_edge_signal


@pytest.mark.asyncio
async def test_filters_low_signal_opportunities() -> None:
    """Should not publish opportunities below signal threshold."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.8"),  # High threshold
    )

    agent.register_market_oracle_mapping(
        market_id="polymarket:btc-above-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),
        direction="above",
    )

    published = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # BTC barely above threshold - weak signal
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {"source": "binance", "symbol": "BTC", "value": "100500", "timestamp": datetime.now(UTC).isoformat()},
    )
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {"market_id": "polymarket:btc-above-100k", "venue": "polymarket", "title": "BTC>100k", "yes_price": "0.50", "no_price": "0.50"},
    )

    # Should NOT publish due to low signal
    assert len(published) == 0
