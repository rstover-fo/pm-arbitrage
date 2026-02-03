"""CoinGecko crypto price oracle - no geo-restrictions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData

logger = structlog.get_logger()

COINGECKO_API = "https://api.coingecko.com/api/v3"

# Cache configuration
DEFAULT_CACHE_TTL_SECONDS = 30

# Map common symbols to CoinGecko IDs
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
}

ID_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_ID.items()}


class CoinGeckoOracle(OracleAdapter):
    """Real-time crypto prices from CoinGecko (free, no geo-restrictions)."""

    name = "coingecko"

    def __init__(self, cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._cached_prices: dict[str, Decimal] = {}
        self._cache_timestamp: datetime | None = None
        self._cache_ttl = timedelta(seconds=cache_ttl_seconds)
        self._symbols: list[str] = []

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)
        self._connected = True
        logger.info("coingecko_connected")

    async def disconnect(self) -> None:
        """Close connections."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("coingecko_disconnected")

    def set_symbols(self, symbols: list[str]) -> None:
        """Set symbols to track - enables batched fetching."""
        self._symbols = symbols

    def _is_cache_stale(self) -> bool:
        """Check if cache has expired based on TTL."""
        if self._cache_timestamp is None:
            return True
        age = datetime.now(UTC) - self._cache_timestamp
        return age > self._cache_ttl

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current price for symbol (e.g., BTC, ETH).

        Uses cached prices from batch fetch if available.
        Returns None if cache is stale and refresh fails.
        """
        symbol_upper = symbol.upper()

        # Check if cache is stale and needs refresh
        if self._is_cache_stale():
            logger.debug(
                "coingecko_cache_stale",
                cache_age_seconds=(
                    (datetime.now(UTC) - self._cache_timestamp).total_seconds()
                    if self._cache_timestamp
                    else None
                ),
                ttl_seconds=self._cache_ttl.total_seconds(),
            )
            await self._fetch_batch()

            # If still stale after fetch attempt (fetch failed), return None
            if self._is_cache_stale():
                logger.warning(
                    "coingecko_cache_expired",
                    symbol=symbol_upper,
                    cache_age_seconds=(
                        (datetime.now(UTC) - self._cache_timestamp).total_seconds()
                        if self._cache_timestamp
                        else None
                    ),
                )
                return None

        # Return from cache
        price = self._cached_prices.get(symbol_upper)
        if price is None:
            return None

        return OracleData(
            source="coingecko",
            symbol=symbol_upper,
            value=price,
            timestamp=self._cache_timestamp or datetime.now(UTC),
        )

    async def _fetch_batch(self) -> None:
        """Fetch all configured symbols in one API call."""
        if not self._client or not self._symbols:
            return

        # Convert symbols to CoinGecko IDs
        coin_ids = []
        for sym in self._symbols:
            coin_id = SYMBOL_TO_ID.get(sym.upper())
            if coin_id:
                coin_ids.append(coin_id)

        if not coin_ids:
            return

        try:
            response = await self._client.get(
                f"{COINGECKO_API}/simple/price",
                params={"ids": ",".join(coin_ids), "vs_currencies": "usd"},
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()

            # Update cache and timestamp on success
            fetch_time = datetime.now(UTC)
            for coin_id, prices in data.items():
                symbol = ID_TO_SYMBOL.get(coin_id)
                if symbol and "usd" in prices:
                    self._cached_prices[symbol] = Decimal(str(prices["usd"]))
                    logger.debug("coingecko_price", symbol=symbol, value=prices["usd"])

            # Only update timestamp if we got valid data
            if data:
                self._cache_timestamp = fetch_time
                logger.debug(
                    "coingecko_cache_refreshed",
                    symbols=list(self._cached_prices.keys()),
                    timestamp=fetch_time.isoformat(),
                )

        except httpx.HTTPError as e:
            logger.error(
                "coingecko_batch_fetch_error",
                error=str(e),
                cache_age_seconds=(
                    (datetime.now(UTC) - self._cache_timestamp).total_seconds()
                    if self._cache_timestamp
                    else None
                ),
            )

    async def subscribe(self, symbols: list[str]) -> None:
        """CoinGecko doesn't support WebSocket - polling only."""
        self._symbols = symbols
        logger.info("coingecko_polling_mode", symbols=symbols)

    async def stream(self):
        """Not supported - use polling via get_current()."""
        raise NotImplementedError("CoinGecko doesn't support streaming")
