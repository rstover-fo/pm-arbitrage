"""National Weather Service (NWS) weather oracle."""

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import structlog

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData

logger = structlog.get_logger()

NWS_API = "https://api.weather.gov"

NWS_USER_AGENT = "pm-arbitrage/0.1.0 (contact@example.com)"

# Map city names to NWS station codes
CITY_TO_STATION: dict[str, str] = {
    "NYC": "KNYC",
    "MIAMI": "KMIA",
    "CHICAGO": "KORD",
    "LA": "KLAX",
    "DENVER": "KDEN",
    "DALLAS": "KDFW",
    "HOUSTON": "KIAH",
    "PHOENIX": "KPHX",
    "SEATTLE": "KSEA",
    "BOSTON": "KBOS",
}

# Valid observation types
VALID_TYPES = {"TEMP", "WIND", "PRECIP"}


def _parse_symbol(symbol: str) -> tuple[str, str] | None:
    """Parse a weather symbol into (observation_type, station_code).

    Supported formats:
        TEMP_KNYC  -> ("TEMP", "KNYC")
        TEMP_NYC   -> ("TEMP", "KNYC")  (city alias resolved)

    Returns None if the symbol format is invalid.
    """
    parts = symbol.upper().split("_", maxsplit=1)
    if len(parts) != 2:
        return None

    obs_type, location = parts

    if obs_type not in VALID_TYPES:
        return None

    # Resolve city alias to station code
    station = CITY_TO_STATION.get(location, location)

    return obs_type, station


def _celsius_to_fahrenheit(celsius: Decimal) -> Decimal:
    """Convert Celsius to Fahrenheit: (C * 9/5) + 32."""
    return (celsius * Decimal("9") / Decimal("5")) + Decimal("32")


class WeatherOracle(OracleAdapter):
    """Real-world weather data from the National Weather Service API."""

    name = "weather"

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._subscribed_symbols: list[str] = []

    async def connect(self) -> None:
        """Initialize HTTP client with NWS-required User-Agent header."""
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": NWS_USER_AGENT},
        )
        self._connected = True
        logger.info("weather_connected")

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("weather_disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        """Store symbols for polling (NWS does not support streaming)."""
        self._subscribed_symbols = symbols
        logger.info("weather_subscribed", symbols=symbols)

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current weather observation for a symbol.

        Symbol format: {TYPE}_{STATION_OR_CITY}
            e.g. TEMP_KNYC, TEMP_NYC, WIND_KMIA

        Currently supports TEMP observations (temperature in Fahrenheit).
        Returns None if the observation is unavailable or the API errors.
        """
        if not self._client:
            raise RuntimeError("Not connected")

        parsed = _parse_symbol(symbol)
        if parsed is None:
            logger.warning("weather_invalid_symbol", symbol=symbol)
            return None

        obs_type, station_id = parsed

        if obs_type != "TEMP":
            logger.warning("weather_unsupported_type", obs_type=obs_type, symbol=symbol)
            return None

        return await self._fetch_temperature(symbol, station_id)

    async def _fetch_temperature(self, symbol: str, station_id: str) -> OracleData | None:
        """Fetch the latest temperature observation from NWS."""
        if not self._client:
            raise RuntimeError("Not connected")

        try:
            response = await self._client.get(
                f"{NWS_API}/stations/{station_id}/observations/latest",
            )
            response.raise_for_status()
            data = response.json()

            temp_value = data["properties"]["temperature"]["value"]

            # NWS returns null when observation is unavailable
            if temp_value is None:
                logger.warning("weather_null_temperature", station=station_id)
                return None

            celsius = Decimal(str(temp_value))
            fahrenheit = _celsius_to_fahrenheit(celsius)

            return OracleData(
                source="weather",
                symbol=symbol.upper(),
                value=fahrenheit,
                timestamp=datetime.now(UTC),
                metadata={
                    "station": station_id,
                    "unit": "fahrenheit",
                    "celsius": float(celsius),
                },
            )

        except httpx.HTTPError as e:
            logger.error("weather_fetch_error", station=station_id, error=str(e))
            return None
        except (KeyError, TypeError) as e:
            logger.error("weather_parse_error", station=station_id, error=str(e))
            return None
