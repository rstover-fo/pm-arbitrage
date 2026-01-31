"""Polymarket venue adapter."""

from decimal import Decimal

import httpx
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import Market

logger = structlog.get_logger()

# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class PolymarketAdapter(VenueAdapter):
    """Adapter for Polymarket prediction market."""

    name = "polymarket"

    def __init__(self, api_key: str = "", private_key: str = "") -> None:
        super().__init__()
        self._api_key = api_key
        self._private_key = private_key
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._connected = True
        logger.info("polymarket_connected")

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("polymarket_disconnected")

    async def get_markets(self) -> list[Market]:
        """Fetch active markets from Polymarket."""
        raw_markets = await self._fetch_markets()
        return [self._parse_market(m) for m in raw_markets]

    async def _fetch_markets(self) -> list[dict]:
        """Fetch raw market data from API."""
        if not self._client:
            raise RuntimeError("Not connected")

        # Fetch active markets
        response = await self._client.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "limit": 100},
        )
        response.raise_for_status()
        return response.json()

    def _parse_market(self, data: dict) -> Market:
        """Parse API response into Market model."""
        prices = data.get("outcomePrices", ["0.5", "0.5"])
        yes_price = Decimal(str(prices[0])) if prices else Decimal("0.5")
        no_price = Decimal(str(prices[1])) if len(prices) > 1 else Decimal("0.5")

        return Market(
            id=f"polymarket:{data['id']}",
            venue="polymarket",
            external_id=data["id"],
            title=data.get("question", ""),
            description=data.get("description", ""),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume24hr", 0))),
            liquidity=Decimal(str(data.get("liquidity", 0))),
        )

    async def subscribe_prices(self, market_ids: list[str]) -> None:
        """Subscribe to price updates (polling for now)."""
        # TODO: Implement WebSocket subscription when available
        logger.info("polymarket_price_subscription", markets=len(market_ids))

    async def get_crypto_markets(self) -> list[Market]:
        """Fetch specifically crypto-related markets (BTC up/down, etc.)."""
        markets = await self.get_markets()
        crypto_keywords = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "crypto"]
        return [
            m for m in markets
            if any(kw in m.title.lower() for kw in crypto_keywords)
        ]
