"""Tests for venue adapter base class."""

import pytest

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import Market


class MockVenueAdapter(VenueAdapter):
    """Mock implementation for testing."""

    name = "mock-venue"

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_markets(self) -> list[Market]:
        return []

    async def subscribe_prices(self, market_ids: list[str]) -> None:
        pass


@pytest.mark.asyncio
async def test_adapter_connects() -> None:
    """Adapter should track connection state."""
    adapter = MockVenueAdapter()

    assert not adapter.is_connected
    await adapter.connect()
    assert adapter.is_connected
    await adapter.disconnect()
    assert not adapter.is_connected
