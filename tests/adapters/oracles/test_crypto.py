"""Tests for crypto oracle adapter."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from pm_arb.adapters.oracles.crypto import BinanceOracle


@pytest.mark.asyncio
async def test_get_current_price() -> None:
    """Should fetch current BTC price."""
    oracle = BinanceOracle()

    mock_response = {"symbol": "BTCUSDT", "price": "65432.10"}

    with patch.object(oracle, "_fetch_price", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response
        await oracle.connect()
        data = await oracle.get_current("BTC")

    assert data is not None
    assert data.symbol == "BTC"
    assert data.value == Decimal("65432.10")
    assert data.source == "binance"
