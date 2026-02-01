"""Tests for order book fetching from venues."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter


@pytest.mark.asyncio
async def test_polymarket_fetches_order_book() -> None:
    """Should fetch and parse order book from Polymarket CLOB API."""
    mock_response = {
        "bids": [
            {"price": "0.45", "size": "1000"},
            {"price": "0.44", "size": "2000"},
        ],
        "asks": [
            {"price": "0.46", "size": "1500"},
            {"price": "0.47", "size": "2500"},
        ],
    }

    adapter = PolymarketAdapter()

    with patch.object(adapter, "_fetch_order_book", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response
        await adapter.connect()
        book = await adapter.get_order_book("polymarket:test-market", "YES")
        await adapter.disconnect()

    assert book is not None
    assert book.best_bid == Decimal("0.45")
    assert book.best_ask == Decimal("0.46")
    assert len(book.bids) == 2
    assert len(book.asks) == 2


@pytest.mark.asyncio
async def test_order_book_vwap_integration() -> None:
    """Should calculate VWAP from fetched order book."""
    mock_response = {
        "bids": [],
        "asks": [
            {"price": "0.50", "size": "100"},
            {"price": "0.60", "size": "100"},
        ],
    }

    adapter = PolymarketAdapter()

    with patch.object(adapter, "_fetch_order_book", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response
        await adapter.connect()
        book = await adapter.get_order_book("test", "YES")
        await adapter.disconnect()

    # VWAP for 200 tokens = (100*0.50 + 100*0.60) / 200 = 0.55
    vwap = book.calculate_buy_vwap(Decimal("200"))
    assert vwap == Decimal("0.55")
