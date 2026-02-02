"""Tests for order lifecycle tracking."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_get_order_status(mock_credentials: PolymarketCredentials) -> None:
    """Should fetch current order status."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-123",
        "status": "MATCHED",
        "filledAmount": "8.5",
        "averagePrice": "0.51",
        "tokenID": "token-abc",
        "side": "BUY",
        "size": "10",
        "price": "0.50",
    }

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.get_order.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.get_order_status("order-123")

        assert order.status == OrderStatus.FILLED
        assert order.filled_amount == Decimal("8.5")


@pytest.mark.asyncio
async def test_cancel_order(mock_credentials: PolymarketCredentials) -> None:
    """Should cancel an open order."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.cancel.return_value = {"success": True}
        mock_clob.return_value = mock_instance

        await adapter.connect()
        success = await adapter.cancel_order("order-123")

        assert success is True
        mock_instance.cancel.assert_called_once_with("order-123")


@pytest.mark.asyncio
async def test_get_open_orders(mock_credentials: PolymarketCredentials) -> None:
    """Should list all open orders."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = [
        {
            "orderID": "order-1",
            "status": "LIVE",
            "filledAmount": "0",
            "tokenID": "token-a",
            "side": "BUY",
            "size": "10",
        },
        {
            "orderID": "order-2",
            "status": "LIVE",
            "filledAmount": "5",
            "tokenID": "token-b",
            "side": "SELL",
            "size": "20",
        },
    ]

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.get_orders.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        orders = await adapter.get_open_orders()

        assert len(orders) == 2
        assert all(o.status == OrderStatus.OPEN for o in orders)


@pytest.mark.asyncio
async def test_cancel_order_failure(mock_credentials: PolymarketCredentials) -> None:
    """Should handle cancel failure gracefully."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.cancel.side_effect = Exception("Order not found")
        mock_clob.return_value = mock_instance

        await adapter.connect()
        success = await adapter.cancel_order("order-nonexistent")

        assert success is False


@pytest.mark.asyncio
async def test_lifecycle_methods_require_auth() -> None:
    """Lifecycle methods should fail without authentication."""
    adapter = PolymarketAdapter()  # No credentials
    await adapter.connect()

    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter.get_order_status("order-123")

    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter.cancel_order("order-123")

    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter.get_open_orders()
