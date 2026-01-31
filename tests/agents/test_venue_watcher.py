"""Tests for Venue Watcher agent."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.agents.venue_watcher import VenueWatcherAgent
from pm_arb.core.models import Market


@pytest.mark.asyncio
async def test_venue_watcher_publishes_prices() -> None:
    """Venue watcher should publish market prices to message bus."""
    mock_adapter = MagicMock()
    mock_adapter.name = "test-venue"
    mock_adapter.connect = AsyncMock()
    mock_adapter.disconnect = AsyncMock()
    mock_adapter.get_markets = AsyncMock(return_value=[
        Market(
            id="test:market1",
            venue="test",
            external_id="m1",
            title="Test Market",
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
        )
    ])

    agent = VenueWatcherAgent(
        redis_url="redis://localhost:6379",
        adapter=mock_adapter,
        poll_interval=0.1,
    )

    # Capture published messages
    published = []
    original_publish = agent.publish
    async def capture_publish(channel, data):
        published.append((channel, data))
        return await original_publish(channel, data)
    agent.publish = capture_publish

    # Run agent briefly
    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.3)
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Verify prices were published
    price_messages = [p for p in published if "prices" in p[0]]
    assert len(price_messages) > 0
    assert price_messages[0][0] == "venue.test-venue.prices"
