"""Integration test for Sprint 2: Live data streaming."""

import asyncio

import pytest

from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_data_streaming() -> None:
    """Stream live data from Polymarket and Binance."""
    redis_url = "redis://localhost:6379"

    # Create adapters
    polymarket = PolymarketAdapter()
    binance = BinanceOracle()

    # Create agents
    venue_agent = VenueWatcherAgent(redis_url, polymarket, poll_interval=2.0)
    oracle_agent = OracleAgent(redis_url, binance, symbols=["BTC", "ETH"], poll_interval=1.0)

    # Capture messages
    venue_messages = []
    oracle_messages = []

    original_venue_publish = venue_agent.publish

    async def capture_venue(channel, data):
        venue_messages.append((channel, data))
        return await original_venue_publish(channel, data)

    venue_agent.publish = capture_venue

    original_oracle_publish = oracle_agent.publish

    async def capture_oracle(channel, data):
        oracle_messages.append((channel, data))
        return await original_oracle_publish(channel, data)

    oracle_agent.publish = capture_oracle

    # Run agents
    venue_task = asyncio.create_task(venue_agent.run())
    oracle_task = asyncio.create_task(oracle_agent.run())

    # Let them run for a few seconds
    await asyncio.sleep(5)

    # Stop agents
    await venue_agent.stop()
    await oracle_agent.stop()
    await asyncio.gather(venue_task, oracle_task, return_exceptions=True)

    # Verify we got data
    print(f"\nVenue messages: {len(venue_messages)}")
    print(f"Oracle messages: {len(oracle_messages)}")

    assert len(oracle_messages) > 0, "Should receive crypto prices"
    # Note: Polymarket may have rate limits, so venue messages are optional in CI
