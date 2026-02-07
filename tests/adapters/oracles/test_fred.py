"""Tests for FRED oracle adapter."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pm_arb.adapters.oracles.fred import FredOracle, SYMBOL_TO_SERIES


@pytest.mark.asyncio
async def test_connect_disconnect_lifecycle() -> None:
    """Should track connection state through connect/disconnect cycle."""
    oracle = FredOracle()

    assert not oracle.is_connected

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    assert oracle.is_connected
    assert oracle._client is not None

    await oracle.disconnect()
    assert not oracle.is_connected


@pytest.mark.asyncio
async def test_supports_streaming_is_false() -> None:
    """FRED is polling-only, no streaming support."""
    oracle = FredOracle()
    assert oracle.supports_streaming is False


@pytest.mark.asyncio
async def test_subscribe_stores_symbols() -> None:
    """Subscribe should store the symbol list for polling."""
    oracle = FredOracle()
    await oracle.subscribe(["FED_RATE", "CPI", "UNEMPLOYMENT"])
    assert oracle._subscribed_symbols == ["FED_RATE", "CPI", "UNEMPLOYMENT"]


@pytest.mark.asyncio
async def test_get_current_fed_rate() -> None:
    """Should fetch and parse the federal funds rate."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={
            "observations": [
                {
                    "date": "2024-12-01",
                    "value": "5.33",
                }
            ]
        },
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    data = await oracle.get_current("FED_RATE")

    assert data is not None
    assert data.source == "fred"
    assert data.symbol == "FED_RATE"
    assert data.value == Decimal("5.33")
    assert data.metadata["series_id"] == "FEDFUNDS"
    assert data.metadata["date"] == "2024-12-01"


@pytest.mark.asyncio
async def test_get_current_cpi() -> None:
    """Should fetch and parse CPI data."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={
            "observations": [
                {
                    "date": "2024-11-01",
                    "value": "315.493",
                }
            ]
        },
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    data = await oracle.get_current("CPI")

    assert data is not None
    assert data.source == "fred"
    assert data.symbol == "CPI"
    assert data.value == Decimal("315.493")
    assert data.metadata["series_id"] == "CPIAUCSL"


@pytest.mark.asyncio
async def test_get_current_unemployment() -> None:
    """Should fetch and parse unemployment rate."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={
            "observations": [
                {
                    "date": "2024-12-01",
                    "value": "4.2",
                }
            ]
        },
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    data = await oracle.get_current("UNEMPLOYMENT")

    assert data is not None
    assert data.symbol == "UNEMPLOYMENT"
    assert data.value == Decimal("4.2")
    assert data.metadata["series_id"] == "UNRATE"


@pytest.mark.asyncio
async def test_get_current_unknown_symbol_returns_none() -> None:
    """Unknown symbols should return None, not raise."""
    oracle = FredOracle()

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    data = await oracle.get_current("FAKE_INDICATOR")
    assert data is None


@pytest.mark.asyncio
async def test_get_current_api_error_returns_none() -> None:
    """HTTP errors should log and return None, not crash."""
    oracle = FredOracle()

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Server Error",
            request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
            response=httpx.Response(500),
        )
    )

    data = await oracle.get_current("FED_RATE")
    assert data is None


@pytest.mark.asyncio
async def test_get_current_empty_observations_returns_none() -> None:
    """Empty observations array should return None."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={"observations": []},
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    data = await oracle.get_current("FED_RATE")
    assert data is None


@pytest.mark.asyncio
async def test_get_current_missing_value_dot_returns_none() -> None:
    """FRED uses '.' for missing/unavailable data - should return None."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={
            "observations": [
                {
                    "date": "2024-12-01",
                    "value": ".",
                }
            ]
        },
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    data = await oracle.get_current("FED_RATE")
    assert data is None


@pytest.mark.asyncio
async def test_get_current_not_connected_returns_none() -> None:
    """Calling get_current before connect should return None."""
    oracle = FredOracle()
    data = await oracle.get_current("FED_RATE")
    assert data is None


@pytest.mark.asyncio
async def test_get_current_case_insensitive() -> None:
    """Symbol lookup should be case-insensitive."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={
            "observations": [
                {
                    "date": "2024-12-01",
                    "value": "5.33",
                }
            ]
        },
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    data = await oracle.get_current("fed_rate")

    assert data is not None
    assert data.symbol == "FED_RATE"


@pytest.mark.asyncio
async def test_get_current_passes_correct_params() -> None:
    """Should pass the correct query parameters to the FRED API."""
    oracle = FredOracle()

    mock_response = httpx.Response(
        200,
        json={
            "observations": [
                {
                    "date": "2024-12-01",
                    "value": "5.33",
                }
            ]
        },
        request=httpx.Request("GET", "https://api.stlouisfed.org/fred/series/observations"),
    )

    with patch("pm_arb.adapters.oracles.fred.settings") as mock_settings:
        mock_settings.fred_api_key = "test-key-123"
        await oracle.connect()

    oracle._client = AsyncMock(spec=httpx.AsyncClient)
    oracle._client.get = AsyncMock(return_value=mock_response)

    await oracle.get_current("GDP")

    oracle._client.get.assert_called_once()
    call_kwargs = oracle._client.get.call_args
    params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")

    assert params["series_id"] == "GDP"
    assert params["sort_order"] == "desc"
    assert params["limit"] == 1
    assert params["file_type"] == "json"
    assert params["api_key"] == "test-key-123"


def test_symbol_mapping_completeness() -> None:
    """All documented symbols should be in the mapping."""
    expected_symbols = {"FED_RATE", "CPI", "GDP", "UNEMPLOYMENT", "INITIAL_CLAIMS"}
    assert set(SYMBOL_TO_SERIES.keys()) == expected_symbols
