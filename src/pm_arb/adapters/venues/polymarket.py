"""Polymarket venue adapter."""

from decimal import Decimal
from typing import Any

import httpx
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import Market, OrderBook, OrderBookLevel

logger = structlog.get_logger()

# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Optional: Import CLOB client if available
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    ClobClient = None  # type: ignore[misc, assignment]
    ApiCreds = None  # type: ignore[misc, assignment]


class PolymarketAdapter(VenueAdapter):
    """Adapter for Polymarket prediction market."""

    name = "polymarket"

    def __init__(
        self,
        credentials: Any | None = None,  # PolymarketCredentials
        api_key: str = "",
        private_key: str = "",
    ) -> None:
        super().__init__()
        self._credentials = credentials
        self._api_key = api_key
        self._private_key = private_key
        self._client: httpx.AsyncClient | None = None
        self._clob_client: Any = None  # ClobClient instance
        self._is_authenticated = False

    @property
    def is_authenticated(self) -> bool:
        """Whether authenticated for trading."""
        return self._is_authenticated

    async def connect(self) -> None:
        """Initialize HTTP client and optionally CLOB client."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._connected = True

        # Initialize CLOB client if credentials provided
        if self._credentials and HAS_CLOB_CLIENT:
            try:
                creds = ApiCreds(
                    api_key=self._credentials.api_key,
                    api_secret=self._credentials.secret,
                    api_passphrase=self._credentials.passphrase,
                )
                self._clob_client = ClobClient(
                    host=CLOB_API,
                    chain_id=137,  # Polygon mainnet
                    key=self._credentials.private_key,
                    creds=creds,
                )
                self._is_authenticated = True
                logger.info("polymarket_authenticated")
            except Exception as e:
                logger.error("polymarket_auth_failed", error=str(e))
                self._is_authenticated = False

        logger.info("polymarket_connected", authenticated=self._is_authenticated)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
        self._clob_client = None
        self._is_authenticated = False
        self._connected = False
        logger.info("polymarket_disconnected")

    async def get_balance(self) -> Decimal:
        """Fetch USDC balance from wallet."""
        if not self._clob_client:
            raise RuntimeError("Not authenticated - credentials required")

        balance_data = self._clob_client.get_balance()
        usdc_balance = balance_data.get("USDC", "0")
        return Decimal(str(usdc_balance))

    async def get_markets(self) -> list[Market]:
        """Fetch active markets from Polymarket."""
        raw_markets = await self._fetch_markets()
        return [self._parse_market(m) for m in raw_markets]

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """Fetch raw market data from API."""
        if not self._client:
            raise RuntimeError("Not connected")

        # Fetch active markets
        response = await self._client.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "limit": 100},
        )
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    def _parse_market(self, data: dict[str, Any]) -> Market:
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
        return [m for m in markets if any(kw in m.title.lower() for kw in crypto_keywords)]

    async def get_order_book(
        self,
        market_id: str,
        outcome: str,
    ) -> OrderBook | None:
        """Fetch order book from CLOB API."""
        raw_book = await self._fetch_order_book(market_id, outcome)
        if not raw_book:
            return None
        return self._parse_order_book(market_id, raw_book)

    async def _fetch_order_book(
        self,
        market_id: str,
        outcome: str,
    ) -> dict[str, Any] | None:
        """Fetch raw order book from CLOB API."""
        if not self._client:
            raise RuntimeError("Not connected")

        # Extract token ID from market (would need actual token ID lookup)
        # For now, use market_id as placeholder
        external_id = market_id.split(":")[-1] if ":" in market_id else market_id

        try:
            response = await self._client.get(
                f"{CLOB_API}/book",
                params={"token_id": external_id},
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
        except httpx.HTTPError as e:
            logger.error("order_book_fetch_error", market=market_id, error=str(e))
            return None

    def _parse_order_book(
        self,
        market_id: str,
        data: dict[str, Any],
    ) -> OrderBook:
        """Parse CLOB API response into OrderBook model."""
        bids = [
            OrderBookLevel(
                price=Decimal(str(b["price"])),
                size=Decimal(str(b["size"])),
            )
            for b in data.get("bids", [])
        ]

        asks = [
            OrderBookLevel(
                price=Decimal(str(a["price"])),
                size=Decimal(str(a["size"])),
            )
            for a in data.get("asks", [])
        ]

        # Sort: bids high to low, asks low to high
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return OrderBook(
            market_id=market_id,
            bids=bids,
            asks=asks,
        )
