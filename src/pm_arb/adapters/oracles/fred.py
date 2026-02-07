"""FRED (Federal Reserve Economic Data) oracle for economic indicators."""

from decimal import Decimal, InvalidOperation
from datetime import UTC, datetime

import httpx
import structlog

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.config import settings
from pm_arb.core.models import OracleData

logger = structlog.get_logger()

FRED_API = "https://api.stlouisfed.org/fred/series/observations"

# Map human-readable symbols to FRED series IDs
SYMBOL_TO_SERIES: dict[str, str] = {
    "FED_RATE": "FEDFUNDS",
    "CPI": "CPIAUCSL",
    "GDP": "GDP",
    "UNEMPLOYMENT": "UNRATE",
    "INITIAL_CLAIMS": "ICSA",
}


class FredOracle(OracleAdapter):
    """Economic indicator data from the FRED API (St. Louis Fed)."""

    name = "fred"

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._api_key: str = ""
        self._subscribed_symbols: list[str] = []

    async def connect(self) -> None:
        """Initialize HTTP client and load API key from settings."""
        self._api_key = settings.fred_api_key
        if not self._api_key:
            logger.warning("fred_no_api_key", hint="Set FRED_API_KEY env variable")

        self._client = httpx.AsyncClient(timeout=30.0)
        self._connected = True
        logger.info("fred_connected")

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("fred_disconnected")

    async def subscribe(self, symbols: list[str]) -> None:
        """Store symbol list for polling (FRED has no streaming)."""
        self._subscribed_symbols = symbols
        logger.info("fred_subscribed", symbols=symbols)

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get the most recent observation for a FRED economic indicator.

        Args:
            symbol: Human-readable symbol (e.g., FED_RATE, CPI, UNEMPLOYMENT).

        Returns:
            OracleData with the latest value, or None if unavailable.
        """
        if not self._client:
            logger.error("fred_not_connected")
            return None

        symbol_upper = symbol.upper()
        series_id = SYMBOL_TO_SERIES.get(symbol_upper)
        if series_id is None:
            logger.warning("fred_unknown_symbol", symbol=symbol_upper)
            return None

        try:
            response = await self._client.get(
                FRED_API,
                params={
                    "series_id": series_id,
                    "sort_order": "desc",
                    "limit": 1,
                    "file_type": "json",
                    "api_key": self._api_key,
                },
            )
            response.raise_for_status()
            data = response.json()

            observations = data.get("observations", [])
            if not observations:
                logger.warning("fred_no_observations", symbol=symbol_upper, series_id=series_id)
                return None

            obs = observations[0]
            raw_value = obs.get("value", "")

            # FRED uses "." for missing/unavailable data points
            if raw_value == ".":
                logger.warning(
                    "fred_missing_value",
                    symbol=symbol_upper,
                    series_id=series_id,
                    date=obs.get("date"),
                )
                return None

            value = Decimal(raw_value)
            obs_date = obs.get("date", "")

            return OracleData(
                source="fred",
                symbol=symbol_upper,
                value=value,
                timestamp=datetime.now(UTC),
                metadata={"series_id": series_id, "date": obs_date},
            )

        except httpx.HTTPError as e:
            logger.error("fred_fetch_error", symbol=symbol_upper, series_id=series_id, error=str(e))
            return None
        except (InvalidOperation, KeyError, IndexError) as e:
            logger.error("fred_parse_error", symbol=symbol_upper, series_id=series_id, error=str(e))
            return None
