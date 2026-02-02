"""Tests for Polymarket CLOB client integration."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    """Create mock credentials for testing."""
    return PolymarketCredentials(
        api_key="test-api-key",
        secret="test-secret",
        passphrase="test-passphrase",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_adapter_connects_with_credentials(mock_credentials: PolymarketCredentials) -> None:
    """Should initialize CLOB client with credentials."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds") as mock_creds,
    ):
        mock_instance = MagicMock()
        mock_clob.return_value = mock_instance
        mock_creds.return_value = MagicMock()

        await adapter.connect()

        mock_clob.assert_called_once()
        assert adapter.is_authenticated


@pytest.mark.asyncio
async def test_adapter_get_balance(mock_credentials: PolymarketCredentials) -> None:
    """Should fetch USDC balance from wallet."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds") as mock_creds,
    ):
        mock_instance = MagicMock()
        mock_instance.get_balance.return_value = {"USDC": "100.50"}
        mock_clob.return_value = mock_instance
        mock_creds.return_value = MagicMock()

        await adapter.connect()
        balance = await adapter.get_balance()

        assert balance == Decimal("100.50")


@pytest.mark.asyncio
async def test_adapter_without_credentials() -> None:
    """Adapter should work without credentials (read-only mode)."""
    adapter = PolymarketAdapter()

    await adapter.connect()

    assert adapter.is_connected
    assert not adapter.is_authenticated


@pytest.mark.asyncio
async def test_get_balance_requires_auth() -> None:
    """get_balance should fail without authentication."""
    adapter = PolymarketAdapter()
    await adapter.connect()

    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter.get_balance()
