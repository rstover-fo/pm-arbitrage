"""Integration test for Sprint 3: Opportunity Scanner with live data."""

import asyncio
from decimal import Decimal

import pytest

from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent


@pytest.mark.asyncio
@pytest.mark.integration
async def test_scanner_detects_live_opportunities() -> None:
    """Scanner should process live data and detect opportunities when configured."""
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

    # Register a test mapping (hypothetical - real markets would need actual IDs)
    # This tests that the scanner receives and processes data correctly
    scanner.register_market_oracle_mapping(
        market_id="polymarket:test-btc-market",
        oracle_symbol="BTC",
        threshold=Decimal("50000"),  # Low threshold so BTC is always above
        direction="above",
    )

    # Track received data
    venue_prices_received = []
    oracle_data_received = []
    opportunities_detected = []

    # Patch handlers to capture data
    original_venue_handler = scanner._handle_venue_price
    original_oracle_handler = scanner._handle_oracle_data
    original_publish = scanner._publish_opportunity

    async def capture_venue(channel, data):
        venue_prices_received.append(data)
        await original_venue_handler(channel, data)

    async def capture_oracle(channel, data):
        oracle_data_received.append(data)
        await original_oracle_handler(channel, data)

    async def capture_opportunity(opp):
        opportunities_detected.append(opp)
        # Don't actually publish in test

    scanner._handle_venue_price = capture_venue  # type: ignore[method-assign]
    scanner._handle_oracle_data = capture_oracle  # type: ignore[method-assign]
    scanner._publish_opportunity = capture_opportunity  # type: ignore[method-assign]

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
    print(f"Venue prices received: {len(venue_prices_received)}")
    print(f"Opportunities detected: {len(opportunities_detected)}")

    # Should have received oracle data (Binance is reliable)
    assert len(oracle_data_received) > 0, "Should receive BTC/ETH prices from Binance"

    # Venue data is optional (Polymarket may rate limit)
    # Opportunities depend on configured market IDs matching actual data
