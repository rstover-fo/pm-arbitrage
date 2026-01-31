"""Tests for oracle adapter base class."""

import pytest

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData


class MockOracle(OracleAdapter):
    """Mock oracle for testing."""

    name = "mock-oracle"

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def subscribe(self, symbols: list[str]) -> None:
        pass

    async def get_current(self, symbol: str) -> OracleData | None:
        return None


@pytest.mark.asyncio
async def test_oracle_connection_tracking() -> None:
    """Oracle should track connection state."""
    oracle = MockOracle()

    assert not oracle.is_connected
    await oracle.connect()
    assert oracle.is_connected
