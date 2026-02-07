"""Tests for NWS weather oracle adapter."""

from decimal import Decimal

import httpx
import pytest

from pm_arb.adapters.oracles.weather import (
    CITY_TO_STATION,
    WeatherOracle,
    _celsius_to_fahrenheit,
    _parse_symbol,
)


NWS_OBS_URL = "https://api.weather.gov/stations/KNYC/observations/latest"


def _make_nws_response(temp_celsius: float | None) -> httpx.Response:
    """Build a mock NWS API response."""
    body = {
        "properties": {
            "temperature": {
                "value": temp_celsius,
                "unitCode": "wmoUnit:degC",
            }
        }
    }
    return httpx.Response(
        status_code=200,
        json=body,
        request=httpx.Request("GET", NWS_OBS_URL),
    )


def _make_error_response(status_code: int = 500) -> httpx.Response:
    """Build a mock error response."""
    return httpx.Response(
        status_code=status_code,
        json={"detail": "Internal server error"},
        request=httpx.Request("GET", NWS_OBS_URL),
    )


class MockTransport(httpx.AsyncBaseTransport):
    """Mock transport that returns a pre-configured response."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self._response


class ErrorTransport(httpx.AsyncBaseTransport):
    """Mock transport that raises a connection error."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


class TestParseSymbol:
    """Tests for _parse_symbol."""

    def test_station_code(self) -> None:
        result = _parse_symbol("TEMP_KNYC")
        assert result == ("TEMP", "KNYC")

    def test_city_alias(self) -> None:
        result = _parse_symbol("TEMP_NYC")
        assert result == ("TEMP", "KNYC")

    def test_case_insensitive(self) -> None:
        result = _parse_symbol("temp_nyc")
        assert result == ("TEMP", "KNYC")

    def test_wind_type(self) -> None:
        result = _parse_symbol("WIND_KMIA")
        assert result == ("WIND", "KMIA")

    def test_invalid_no_underscore(self) -> None:
        assert _parse_symbol("TEMPKNYC") is None

    def test_invalid_type(self) -> None:
        assert _parse_symbol("HUMIDITY_KNYC") is None

    def test_empty_string(self) -> None:
        assert _parse_symbol("") is None


class TestCelsiusToFahrenheit:
    """Tests for _celsius_to_fahrenheit."""

    def test_freezing_point(self) -> None:
        assert _celsius_to_fahrenheit(Decimal("0")) == Decimal("32")

    def test_boiling_point(self) -> None:
        assert _celsius_to_fahrenheit(Decimal("100")) == Decimal("212")

    def test_body_temp(self) -> None:
        result = _celsius_to_fahrenheit(Decimal("37"))
        assert result == Decimal("98.6")

    def test_negative(self) -> None:
        result = _celsius_to_fahrenheit(Decimal("-40"))
        assert result == Decimal("-40")

    def test_decimal_precision(self) -> None:
        result = _celsius_to_fahrenheit(Decimal("22.5"))
        assert result == Decimal("72.5")


# ---------------------------------------------------------------------------
# Integration-style tests for WeatherOracle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_disconnect_lifecycle() -> None:
    """Oracle should track connection state through lifecycle."""
    oracle = WeatherOracle()

    assert not oracle.is_connected
    await oracle.connect()
    assert oracle.is_connected
    assert oracle._client is not None

    await oracle.disconnect()
    assert not oracle.is_connected


@pytest.mark.asyncio
async def test_supports_streaming_is_false() -> None:
    """WeatherOracle does not support streaming."""
    oracle = WeatherOracle()
    assert oracle.supports_streaming is False


@pytest.mark.asyncio
async def test_subscribe_stores_symbols() -> None:
    """Subscribe should store the symbol list."""
    oracle = WeatherOracle()
    await oracle.subscribe(["TEMP_KNYC", "TEMP_KMIA"])
    assert oracle._subscribed_symbols == ["TEMP_KNYC", "TEMP_KMIA"]


@pytest.mark.asyncio
async def test_get_current_station_code() -> None:
    """Should fetch temperature in Fahrenheit for a station code."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(22.5)))
    oracle._connected = True

    data = await oracle.get_current("TEMP_KNYC")

    assert data is not None
    assert data.source == "weather"
    assert data.symbol == "TEMP_KNYC"
    assert data.value == Decimal("72.5")  # 22.5C -> 72.5F
    assert data.metadata["station"] == "KNYC"
    assert data.metadata["unit"] == "fahrenheit"
    assert data.metadata["celsius"] == 22.5

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_city_alias() -> None:
    """Should resolve city alias to station code and fetch temperature."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(22.5)))
    oracle._connected = True

    data = await oracle.get_current("TEMP_NYC")

    assert data is not None
    assert data.symbol == "TEMP_NYC"
    assert data.value == Decimal("72.5")
    assert data.metadata["station"] == "KNYC"

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_null_temperature_returns_none() -> None:
    """Should return None when NWS reports null temperature."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(None)))
    oracle._connected = True

    data = await oracle.get_current("TEMP_KNYC")
    assert data is None

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_http_error_returns_none() -> None:
    """Should return None on HTTP errors (5xx, 4xx)."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_error_response(500)))
    oracle._connected = True

    data = await oracle.get_current("TEMP_KNYC")
    assert data is None

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_connection_error_returns_none() -> None:
    """Should return None on connection errors."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=ErrorTransport())
    oracle._connected = True

    data = await oracle.get_current("TEMP_KNYC")
    assert data is None

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_invalid_symbol_returns_none() -> None:
    """Should return None for an unparseable symbol."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(22.5)))
    oracle._connected = True

    data = await oracle.get_current("INVALID")
    assert data is None

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_unsupported_type_returns_none() -> None:
    """Should return None for observation types not yet implemented (WIND, PRECIP)."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(22.5)))
    oracle._connected = True

    data = await oracle.get_current("WIND_KNYC")
    assert data is None

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_not_connected_raises() -> None:
    """Should raise RuntimeError if not connected."""
    oracle = WeatherOracle()

    with pytest.raises(RuntimeError, match="Not connected"):
        await oracle.get_current("TEMP_KNYC")


@pytest.mark.asyncio
async def test_get_current_freezing_temp() -> None:
    """Should correctly convert freezing temperature."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(0.0)))
    oracle._connected = True

    data = await oracle.get_current("TEMP_KNYC")
    assert data is not None
    assert data.value == Decimal("32")

    await oracle._client.aclose()


@pytest.mark.asyncio
async def test_get_current_negative_temp() -> None:
    """Should handle negative Celsius temperatures."""
    oracle = WeatherOracle()
    oracle._client = httpx.AsyncClient(transport=MockTransport(_make_nws_response(-10.0)))
    oracle._connected = True

    data = await oracle.get_current("TEMP_KNYC")
    assert data is not None
    assert data.value == Decimal("14")  # -10C -> 14F

    await oracle._client.aclose()


def test_city_to_station_mapping_complete() -> None:
    """All expected cities should have station mappings."""
    expected = {
        "NYC", "MIAMI", "CHICAGO", "LA", "DENVER",
        "DALLAS", "HOUSTON", "PHOENIX", "SEATTLE", "BOSTON",
    }
    assert set(CITY_TO_STATION.keys()) == expected


def test_oracle_name() -> None:
    """Oracle name should be 'weather'."""
    oracle = WeatherOracle()
    assert oracle.name == "weather"
