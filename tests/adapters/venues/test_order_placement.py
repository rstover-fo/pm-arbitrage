"""Tests for order placement on Polymarket via the generic VenueAdapter interface."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import Side, TradeRequest, TradeStatus


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


def _make_trade_request(**overrides) -> TradeRequest:
    """Helper to create a TradeRequest with sensible defaults."""
    defaults = {
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "oracle-sniper",
        "market_id": "polymarket:market-abc",
        "side": Side.BUY,
        "outcome": "YES",
        "amount": Decimal("10"),
        "max_price": Decimal("0.52"),
    }
    defaults.update(overrides)
    return TradeRequest(**defaults)


@pytest.mark.asyncio
async def test_place_market_order(mock_credentials: PolymarketCredentials) -> None:
    """Should place order and return Trade via generic interface."""
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

        # Mock get_token_id since place_order now calls it internally
        adapter.get_token_id = AsyncMock(return_value="token-abc")

        request = _make_trade_request()
        trade = await adapter.place_order(request)

        assert trade.external_id == "order-123"
        assert trade.status == TradeStatus.FILLED
        assert trade.amount == Decimal("10.0")
        assert trade.price == Decimal("0.52")
        assert trade.venue == "polymarket"
        assert trade.request_id == "req-001"
        assert trade.market_id == "polymarket:market-abc"
        assert trade.side == Side.BUY
        assert trade.outcome == "YES"

        # Verify get_token_id was called with correct args
        adapter.get_token_id.assert_called_once_with("polymarket:market-abc", "YES")


@pytest.mark.asyncio
async def test_place_limit_order(mock_credentials: PolymarketCredentials) -> None:
    """Should place limit order using max_price from TradeRequest."""
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
        adapter.get_token_id = AsyncMock(return_value="token-abc")

        request = _make_trade_request(max_price=Decimal("0.50"))
        trade = await adapter.place_order(request)

        assert trade.external_id == "order-456"
        assert trade.status == TradeStatus.SUBMITTED
        assert trade.price == Decimal("0.50")

        # Verify CLOB client was called with price for limit order
        call_args = mock_instance.create_and_post_order.call_args[0][0]
        assert call_args["price"] == 0.50


@pytest.mark.asyncio
async def test_place_order_requires_auth() -> None:
    """Should fail to place order without authentication."""
    adapter = PolymarketAdapter()  # No credentials
    await adapter.connect()

    request = _make_trade_request()
    with pytest.raises(RuntimeError, match="Not authenticated"):
        await adapter.place_order(request)


@pytest.mark.asyncio
async def test_place_order_handles_rejection(mock_credentials: PolymarketCredentials) -> None:
    """Should handle order rejection gracefully, returning Trade with FAILED status."""
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
        adapter.get_token_id = AsyncMock(return_value="token-abc")

        request = _make_trade_request()
        trade = await adapter.place_order(request)

        assert trade.status == TradeStatus.FAILED
        assert trade.venue == "polymarket"
        assert trade.request_id == "req-001"


@pytest.mark.asyncio
async def test_place_order_returns_trade_not_order(
    mock_credentials: PolymarketCredentials,
) -> None:
    """Verify place_order returns a Trade (not Order) matching the VenueAdapter contract."""
    from pm_arb.core.models import Trade

    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-789",
        "status": "MATCHED",
        "filledAmount": "5.0",
        "averagePrice": "0.60",
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
        adapter.get_token_id = AsyncMock(return_value="token-xyz")

        request = _make_trade_request()
        result = await adapter.place_order(request)

        assert isinstance(result, Trade)
