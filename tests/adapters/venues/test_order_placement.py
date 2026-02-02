"""Tests for order placement on Polymarket."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import Order, OrderStatus, OrderType, Side


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_place_market_order(mock_credentials: PolymarketCredentials) -> None:
    """Should place market buy order."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-123",
        "status": "MATCHED",
        "filledAmount": "10.0",
        "averagePrice": "0.52",
    }

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.create_and_post_order.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.place_order(
            token_id="token-abc",
            side=Side.BUY,
            amount=Decimal("10"),
            order_type=OrderType.MARKET,
        )

        assert order.external_id == "order-123"
        assert order.status == OrderStatus.FILLED
        assert order.filled_amount == Decimal("10.0")
        assert order.average_price == Decimal("0.52")


@pytest.mark.asyncio
async def test_place_limit_order(mock_credentials: PolymarketCredentials) -> None:
    """Should place limit order at specified price."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-456",
        "status": "LIVE",
        "filledAmount": "0",
    }

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.create_and_post_order.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.place_order(
            token_id="token-abc",
            side=Side.BUY,
            amount=Decimal("10"),
            order_type=OrderType.LIMIT,
            price=Decimal("0.50"),
        )

        assert order.external_id == "order-456"
        assert order.status == OrderStatus.OPEN
        assert order.price == Decimal("0.50")


@pytest.mark.asyncio
async def test_place_order_requires_auth(mock_credentials: PolymarketCredentials) -> None:
    """Should fail to place order without authentication."""
    adapter = PolymarketAdapter()  # No credentials
    await adapter.connect()

    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter.place_order(
            token_id="token-abc",
            side=Side.BUY,
            amount=Decimal("10"),
            order_type=OrderType.MARKET,
        )


@pytest.mark.asyncio
async def test_limit_order_requires_price(mock_credentials: PolymarketCredentials) -> None:
    """Limit orders should require a price."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_clob.return_value = MagicMock()
        await adapter.connect()

        with pytest.raises(ValueError, match="Price required"):
            await adapter.place_order(
                token_id="token-abc",
                side=Side.BUY,
                amount=Decimal("10"),
                order_type=OrderType.LIMIT,
                # Missing price!
            )


@pytest.mark.asyncio
async def test_place_order_handles_rejection(mock_credentials: PolymarketCredentials) -> None:
    """Should handle order rejection gracefully."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with (
        patch("pm_arb.adapters.venues.polymarket.HAS_CLOB_CLIENT", True),
        patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob,
        patch("pm_arb.adapters.venues.polymarket.ApiCreds"),
    ):
        mock_instance = MagicMock()
        mock_instance.create_and_post_order.side_effect = Exception("Insufficient balance")
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.place_order(
            token_id="token-abc",
            side=Side.BUY,
            amount=Decimal("10"),
            order_type=OrderType.MARKET,
        )

        assert order.status == OrderStatus.REJECTED
        assert "Insufficient balance" in (order.error_message or "")
