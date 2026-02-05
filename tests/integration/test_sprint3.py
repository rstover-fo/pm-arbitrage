"""Integration test for Sprint 3: Opportunity Scanner with live data."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent


@pytest.mark.asyncio
async def test_scanner_detects_live_opportunities() -> None:
    """Scanner should detect opportunities from simulated data using handler-based testing."""
    redis_url = "redis://localhost:6379"

    # Create scanner
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.test"],
        oracle_channels=["oracle.test"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.1"),
    )

    # Register market-oracle mapping for BTC $100k threshold
    scanner.register_market_oracle_mapping(
        market_id="polymarket:btc-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),
        direction="above",
    )

    # Track detected opportunities
    opportunities_detected: list[dict[str, Any]] = []

    async def capture_opportunity(opp: dict[str, Any]) -> None:
        opportunities_detected.append(opp)

    scanner._publish_opportunity = capture_opportunity  # type: ignore[method-assign]

    # Simulate venue price update (market says 75% chance BTC hits $100k)
    # Realistic scenario: market is lagging behind oracle by ~20%
    await scanner._handle_venue_price(
        "venue.test",
        {
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "title": "Will BTC exceed $100k?",
            "yes_price": "0.75",
            "no_price": "0.25",
        },
    )

    # Simulate oracle showing BTC at $110k (10% above threshold - fair value ~95%)
    await scanner._handle_oracle_data(
        "oracle.test",
        {
            "source": "binance",
            "symbol": "BTC",
            "value": "110000",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # Process any pending matches
    await asyncio.sleep(0.1)

    # Verify opportunity was detected
    print(f"\nOpportunities detected: {len(opportunities_detected)}")
    if opportunities_detected:
        print(f"Opportunity: {opportunities_detected[0]}")

    assert len(opportunities_detected) > 0, "Should detect arbitrage opportunity"
    opp = opportunities_detected[0]
    assert opp.type.value == "oracle_lag"
    assert opp.expected_edge > Decimal("0.05"), "Expected edge should be significant"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_scanner_detects_live_opportunities_real_services() -> None:
    """Scanner with real external data sources (requires network)."""
    # Import real adapters only for integration test
    from pm_arb.adapters.oracles.crypto import BinanceOracle
    from pm_arb.adapters.venues.polymarket import PolymarketAdapter
    from pm_arb.agents.oracle_agent import OracleAgent
    from pm_arb.agents.venue_watcher import VenueWatcherAgent

    redis_url = "redis://localhost:6379"

    # Create adapters
    binance = BinanceOracle()
    polymarket = PolymarketAdapter()

    # Create data-producing agents
    oracle_agent = OracleAgent(redis_url, binance, symbols=["BTC", "ETH"], poll_interval=1.0)
    venue_agent = VenueWatcherAgent(redis_url, polymarket, poll_interval=2.0)

    # Create scanner
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC", "oracle.binance.ETH"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.1"),
    )

    # Register a test mapping
    scanner.register_market_oracle_mapping(
        market_id="polymarket:test-btc-market",
        oracle_symbol="BTC",
        threshold=Decimal("50000"),
        direction="above",
    )

    # Track received data
    oracle_data_received: list[dict[str, Any]] = []

    original_oracle_handler = scanner._handle_oracle_data

    async def capture_oracle(channel: str, data: dict[str, Any]) -> None:
        oracle_data_received.append(data)
        await original_oracle_handler(channel, data)

    scanner._handle_oracle_data = capture_oracle  # type: ignore[method-assign]

    # Start all agents
    oracle_task = asyncio.create_task(oracle_agent.run())
    venue_task = asyncio.create_task(venue_agent.run())
    scanner_task = asyncio.create_task(scanner.run())

    # Let them run
    await asyncio.sleep(5)

    # Stop agents
    await oracle_agent.stop()
    await venue_agent.stop()
    await scanner.stop()

    await asyncio.gather(oracle_task, venue_task, scanner_task, return_exceptions=True)

    # Verify data flow
    print(f"\nOracle data received: {len(oracle_data_received)}")

    assert len(oracle_data_received) > 0, "Should receive BTC/ETH prices from Binance"
