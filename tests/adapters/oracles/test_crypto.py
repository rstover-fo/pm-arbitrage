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


@pytest.mark.asyncio
async def test_subscribe_single_symbol_uses_ws_endpoint() -> None:
    """Single symbol subscription should use /ws/<stream> endpoint."""
    oracle = BinanceOracle()

    with patch("pm_arb.adapters.oracles.crypto.websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = AsyncMock()
        await oracle.subscribe(["BTC"])

        # Verify single stream uses /ws/ endpoint
        call_url = mock_connect.call_args[0][0]
        assert "/ws/" in call_url
        assert "btcusdt@ticker" in call_url
        assert "?streams=" not in call_url


@pytest.mark.asyncio
async def test_subscribe_multiple_symbols_uses_stream_endpoint() -> None:
    """Multiple symbol subscription should use /stream?streams= endpoint."""
    oracle = BinanceOracle()

    with patch("pm_arb.adapters.oracles.crypto.websockets.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = AsyncMock()
        await oracle.subscribe(["BTC", "ETH", "SOL"])

        # Verify multiple streams use /stream?streams= endpoint
        call_url = mock_connect.call_args[0][0]
        assert "/stream?streams=" in call_url
        assert "btcusdt@ticker" in call_url
        assert "ethusdt@ticker" in call_url
        assert "solusdt@ticker" in call_url
