"""Tests for Polymarket adapter."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter


@pytest.mark.asyncio
async def test_get_markets_parses_response() -> None:
    """Should parse Polymarket API response into Market objects."""
    mock_response = {
        "data": [
            {
                "id": "0x123",
                "question": "Will BTC be above $70k?",
                "description": "Resolves YES if...",
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.45", "0.55"],
                "volume24hr": "10000",
                "liquidity": "50000",
            }
        ]
    }

    adapter = PolymarketAdapter()

    with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response["data"]
        markets = await adapter.get_markets()

    assert len(markets) == 1
    assert markets[0].venue == "polymarket"
    assert markets[0].yes_price == Decimal("0.45")
    assert markets[0].title == "Will BTC be above $70k?"
