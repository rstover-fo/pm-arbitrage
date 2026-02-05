"""Integration test for Sprint 2: Live data streaming."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent
from pm_arb.core.models import Market, OracleData


@pytest.mark.asyncio
async def test_live_data_streaming() -> None:
    """Test data streaming pipeline with mocked adapters."""
    redis_url = "redis://localhost:6379"

    # Create mock Polymarket adapter
    mock_polymarket = AsyncMock()
    mock_polymarket.name = "polymarket"
    mock_polymarket.is_connected = True
    mock_polymarket.connect = AsyncMock()
    mock_polymarket.disconnect = AsyncMock()
    mock_polymarket.get_markets = AsyncMock(
        return_value=[
            Market(
                id="polymarket:btc-100k",
                venue="polymarket",
                external_id="0x123",
                title="Will BTC exceed $100k?",
                yes_price=Decimal("0.45"),
                no_price=Decimal("0.55"),
                last_updated=datetime.now(UTC),
            )
        ]
    )

    # Create mock Binance oracle
    mock_binance = MagicMock()
    mock_binance.name = "binance"
    mock_binance.is_connected = True
    mock_binance.connect = AsyncMock()
    mock_binance.disconnect = AsyncMock()
    mock_binance.get_current = AsyncMock(
        return_value=OracleData(
            source="binance",
            symbol="BTC",
            value=Decimal("50000"),
            timestamp=datetime.now(UTC),
        )
    )

    # Create agents with mocked adapters
    venue_agent = VenueWatcherAgent(redis_url, mock_polymarket, poll_interval=0.1)
    oracle_agent = OracleAgent(redis_url, mock_binance, symbols=["BTC"], poll_interval=0.1)

    # Capture published messages
    venue_messages: list[tuple[str, dict[str, Any]]] = []
    oracle_messages: list[tuple[str, dict[str, Any]]] = []

    async def capture_venue(channel: str, data: dict[str, Any]) -> str:
        venue_messages.append((channel, data))
        return "mock-id"

    async def capture_oracle(channel: str, data: dict[str, Any]) -> str:
        oracle_messages.append((channel, data))
        return "mock-id"

    venue_agent.publish = capture_venue  # type: ignore[method-assign]
    oracle_agent.publish = capture_oracle  # type: ignore[method-assign]

    # Run agents briefly
    venue_task = asyncio.create_task(venue_agent.run())
    oracle_task = asyncio.create_task(oracle_agent.run())

    # Let them run for a short time (poll interval is 0.1s, so 0.5s should get multiple polls)
    await asyncio.sleep(0.5)

    # Stop agents
    await venue_agent.stop()
    await oracle_agent.stop()
    await asyncio.gather(venue_task, oracle_task, return_exceptions=True)

    # Verify we got data
    print(f"\nVenue messages: {len(venue_messages)}")
    print(f"Oracle messages: {len(oracle_messages)}")

    assert len(oracle_messages) > 0, "Should receive crypto prices"
    assert len(venue_messages) > 0, "Should receive venue prices"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_data_streaming_real_services() -> None:
    """Stream live data from real Polymarket and Binance (requires network)."""
    # Import real adapters only for integration test
    from pm_arb.adapters.oracles.crypto import BinanceOracle
    from pm_arb.adapters.venues.polymarket import PolymarketAdapter

    redis_url = "redis://localhost:6379"

    # Create real adapters
    polymarket = PolymarketAdapter()
    binance = BinanceOracle()

    # Create agents
    venue_agent = VenueWatcherAgent(redis_url, polymarket, poll_interval=2.0)
    oracle_agent = OracleAgent(redis_url, binance, symbols=["BTC", "ETH"], poll_interval=1.0)

    # Capture messages
    venue_messages: list[tuple[str, Any]] = []
    oracle_messages: list[tuple[str, Any]] = []

    original_venue_publish = venue_agent.publish

    async def capture_venue(channel: str, data: Any) -> str:
        venue_messages.append((channel, data))
        return await original_venue_publish(channel, data)

    venue_agent.publish = capture_venue  # type: ignore[method-assign]

    original_oracle_publish = oracle_agent.publish

    async def capture_oracle(channel: str, data: Any) -> str:
        oracle_messages.append((channel, data))
        return await original_oracle_publish(channel, data)

    oracle_agent.publish = capture_oracle  # type: ignore[method-assign]

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
