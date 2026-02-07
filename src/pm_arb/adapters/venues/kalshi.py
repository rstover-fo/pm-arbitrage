"""Kalshi venue adapter."""

import base64
import time
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.auth import KalshiCredentials
from pm_arb.core.models import (
    Market,
    OrderBook,
    OrderBookLevel,
    Side,
    Trade,
    TradeRequest,
    TradeStatus,
)

logger = structlog.get_logger()

# Kalshi API base URL (production / elections)
KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiAdapter(VenueAdapter):
    """Adapter for Kalshi prediction market."""

    name = "kalshi"

    def __init__(
        self,
        credentials: KalshiCredentials | None = None,
        base_url: str = KALSHI_API_BASE,
    ) -> None:
        super().__init__()
        self._credentials = credentials
        self._base_url = base_url
        self._client: httpx.AsyncClient | None = None
        self._is_authenticated = False
        self._rsa_private_key: Any = None  # Loaded RSA key object

    @property
    def is_authenticated(self) -> bool:
        """Whether authenticated for trading."""
        return self._is_authenticated

    def _load_rsa_key(self) -> None:
        """Load and cache the RSA private key from PEM string."""
        if self._rsa_private_key is not None:
            return
        if not self._credentials:
            raise RuntimeError("No credentials provided")

        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        self._rsa_private_key = load_pem_private_key(
            self._credentials.private_key.encode("utf-8"),
            password=None,
        )

    def _sign_request(self, method: str, path: str) -> dict[str, str]:
        """Generate RSA-PSS authentication headers for a Kalshi API request.

        Creates a signature over the message: timestamp_ms + method + path
        using RSA-PSS with SHA256 and MGF1(SHA256).

        Args:
            method: HTTP method (GET, POST, etc.)
            path: API path (e.g., /trade-api/v2/markets)

        Returns:
            Dict with KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE,
            and KALSHI-ACCESS-TIMESTAMP headers.
        """
        if not self._credentials:
            raise RuntimeError("No credentials provided")

        self._load_rsa_key()

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        timestamp_ms = str(int(time.time() * 1000))
        message = timestamp_ms + method.upper() + path
        message_bytes = message.encode("utf-8")

        signature = self._rsa_private_key.sign(
            message_bytes,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        signature_b64 = base64.b64encode(signature).decode("utf-8")

        return {
            "KALSHI-ACCESS-KEY": self._credentials.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature_b64,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make an authenticated request to the Kalshi API.

        Args:
            method: HTTP method
            path: API path relative to base (e.g., /markets)
            **kwargs: Additional args passed to httpx request (json, params, etc.)

        Returns:
            Parsed JSON response.

        Raises:
            RuntimeError: If not connected.
            httpx.HTTPStatusError: On non-2xx responses.
        """
        if not self._client:
            raise RuntimeError("Not connected")

        full_path = f"/trade-api/v2{path}"
        url = f"{self._base_url}{path}"

        headers = kwargs.pop("headers", {})

        # Add auth headers if credentials are available
        if self._credentials:
            auth_headers = self._sign_request(method.upper(), full_path)
            headers.update(auth_headers)

        response = await self._client.request(
            method,
            url,
            headers=headers,
            **kwargs,
        )
        response.raise_for_status()

        result: dict[str, Any] = response.json()
        return result

    async def connect(self) -> None:
        """Initialize HTTP client and optionally authenticate."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._connected = True

        if self._credentials:
            try:
                self._load_rsa_key()
                # Verify connectivity by checking exchange status
                await self._request("GET", "/exchange/status")
                self._is_authenticated = True
                logger.info("kalshi_authenticated")
            except Exception as e:
                logger.error("kalshi_auth_failed", error=str(e))
                self._is_authenticated = False

        logger.info("kalshi_connected", authenticated=self._is_authenticated)

    async def disconnect(self) -> None:
        """Close HTTP client and reset state."""
        if self._client:
            await self._client.aclose()
        self._client = None
        self._rsa_private_key = None
        self._is_authenticated = False
        self._connected = False
        logger.info("kalshi_disconnected")

    async def get_markets(self) -> list[Market]:
        """Fetch active markets from Kalshi.

        Retrieves open markets and converts Kalshi's cent-based pricing
        to our Decimal fraction format (0.00 - 1.00).

        Returns:
            List of Market objects with normalized pricing.
        """
        raw_markets = await self._fetch_markets()
        markets = []
        for m in raw_markets:
            parsed = self._parse_market(m)
            if parsed is not None:
                markets.append(parsed)
        return markets

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """Fetch raw market data from the Kalshi API.

        Returns:
            List of raw market dicts from the API.
        """
        response = await self._request(
            "GET",
            "/markets",
            params={
                "status": "open",
                "limit": 200,
            },
        )
        markets: list[dict[str, Any]] = response.get("markets", [])
        return markets

    def _parse_market(self, data: dict[str, Any]) -> Market | None:
        """Parse a Kalshi API market dict into a Market model.

        Kalshi prices are in cents (0-99). We convert to Decimal fractions.

        Args:
            data: Raw market dict from the Kalshi API.

        Returns:
            Market object, or None if data is invalid.
        """
        ticker = data.get("ticker", "")
        if not ticker:
            logger.warning("kalshi_market_missing_ticker", data_keys=list(data.keys()))
            return None

        # Kalshi prices: yes_price and no_price in cents (0-99)
        # yes_bid/yes_ask may also be present
        yes_price_cents = data.get("yes_bid", data.get("yes_price", 0))
        no_price_cents = data.get("no_bid", data.get("no_price", 0))

        # Fallback: if we have yes_price, no is 100 - yes
        if yes_price_cents and not no_price_cents:
            no_price_cents = 100 - yes_price_cents
        elif no_price_cents and not yes_price_cents:
            yes_price_cents = 100 - no_price_cents

        # Convert cents to Decimal fractions
        try:
            yes_price = Decimal(str(yes_price_cents)) / Decimal("100")
            no_price = Decimal(str(no_price_cents)) / Decimal("100")
        except Exception as e:
            logger.warning(
                "kalshi_price_conversion_failed",
                ticker=ticker,
                yes_cents=yes_price_cents,
                no_cents=no_price_cents,
                error=str(e),
            )
            return None

        # Volume: Kalshi reports volume in contracts
        volume_raw = data.get("volume_24h", data.get("volume", 0))
        volume_24h = Decimal(str(volume_raw)) if volume_raw else Decimal("0")

        # Liquidity: Kalshi may report open_interest
        liquidity_raw = data.get("open_interest", data.get("liquidity", 0))
        liquidity = Decimal(str(liquidity_raw)) if liquidity_raw else Decimal("0")

        return Market(
            id=f"kalshi:{ticker}",
            venue="kalshi",
            external_id=ticker,
            title=data.get("title", data.get("subtitle", "")),
            description=data.get("rules_primary", ""),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=volume_24h,
            liquidity=liquidity,
        )

    async def subscribe_prices(self, market_ids: list[str]) -> None:
        """Subscribe to price updates (polling for now).

        Args:
            market_ids: List of market IDs to subscribe to.
        """
        # TODO: Implement WebSocket subscription when available
        logger.info("kalshi_price_subscription", markets=len(market_ids))

    async def place_order(self, request: TradeRequest) -> Trade:
        """Place an order on Kalshi.

        Converts our generic TradeRequest into Kalshi's order format:
        - Prices converted from Decimal fractions to cents
        - Side mapped to Kalshi's yes/no + buy/sell model

        Args:
            request: Generic trade request from the strategy/executor pipeline.

        Returns:
            Trade result with execution details.
        """
        if not self._is_authenticated:
            raise RuntimeError("Not authenticated - credentials required")

        trade_id = f"trade-{uuid4().hex[:8]}"

        try:
            # Extract ticker from market_id (format: "kalshi:{ticker}")
            ticker = (
                request.market_id.split(":")[-1]
                if ":" in request.market_id
                else request.market_id
            )

            # Convert Decimal price to Kalshi cents (integer 1-99)
            price_cents = int(request.max_price * 100)

            # Build Kalshi order payload
            order_body: dict[str, Any] = {
                "ticker": ticker,
                "action": "buy" if request.side == Side.BUY else "sell",
                "side": request.outcome.lower(),  # "yes" or "no"
                "type": "limit",
                "count": int(request.amount),
            }

            # Set price based on outcome side
            if request.outcome.upper() == "YES":
                order_body["yes_price"] = price_cents
            else:
                order_body["no_price"] = price_cents

            response = await self._request(
                "POST",
                "/portfolio/orders",
                json=order_body,
            )

            order_data = response.get("order", response)

            # Map Kalshi status to our TradeStatus
            status_map = {
                "resting": TradeStatus.SUBMITTED,
                "pending": TradeStatus.PENDING,
                "executed": TradeStatus.FILLED,
                "canceled": TradeStatus.CANCELLED,
            }

            kalshi_status = order_data.get("status", "pending").lower()
            status = status_map.get(kalshi_status, TradeStatus.PENDING)

            return Trade(
                id=trade_id,
                request_id=request.id,
                market_id=request.market_id,
                venue=self.name,
                side=request.side,
                outcome=request.outcome,
                amount=request.amount,
                price=request.max_price,
                status=status,
                external_id=order_data.get("order_id", ""),
            )

        except Exception as e:
            logger.error(
                "kalshi_order_placement_failed",
                error=str(e),
                market_id=request.market_id,
            )
            return Trade(
                id=trade_id,
                request_id=request.id,
                market_id=request.market_id,
                venue=self.name,
                side=request.side,
                outcome=request.outcome,
                amount=request.amount,
                price=request.max_price,
                status=TradeStatus.FAILED,
            )

    async def get_balance(self) -> Decimal:
        """Get account balance in dollars.

        Kalshi returns balance in cents; we convert to dollars.

        Returns:
            Account balance as Decimal dollars.

        Raises:
            RuntimeError: If not authenticated.
        """
        if not self._is_authenticated:
            raise RuntimeError("Not authenticated - credentials required")

        response = await self._request("GET", "/portfolio/balance")
        balance_cents = response.get("balance", 0)
        return Decimal(str(balance_cents)) / Decimal("100")

    async def get_order_book(
        self,
        market_id: str,
        outcome: str,
    ) -> OrderBook | None:
        """Fetch order book for a Kalshi market.

        Args:
            market_id: Market ID in format "kalshi:{ticker}"
            outcome: "YES" or "NO"

        Returns:
            OrderBook with prices converted from cents to Decimal fractions,
            or None on error.
        """
        ticker = (
            market_id.split(":")[-1] if ":" in market_id else market_id
        )

        try:
            response = await self._request(
                "GET",
                f"/markets/{ticker}/orderbook",
            )
            return self._parse_order_book(market_id, response)
        except httpx.HTTPError as e:
            logger.error(
                "kalshi_order_book_fetch_error",
                market=market_id,
                error=str(e),
            )
            return None

    def _parse_order_book(
        self,
        market_id: str,
        data: dict[str, Any],
    ) -> OrderBook:
        """Parse Kalshi order book response into OrderBook model.

        Kalshi order book has yes/no arrays with [price_cents, size] pairs.

        Args:
            market_id: Internal market ID
            data: Raw API response

        Returns:
            Parsed OrderBook with prices in Decimal fractions.
        """
        orderbook_data = data.get("orderbook", data)

        # Kalshi format: {"yes": [[price_cents, size], ...], "no": [[price_cents, size], ...]}
        yes_levels = orderbook_data.get("yes", [])
        no_levels = orderbook_data.get("no", [])

        # Bids (people wanting to buy YES = sell NO)
        bids = [
            OrderBookLevel(
                price=Decimal(str(level[0])) / Decimal("100"),
                size=Decimal(str(level[1])),
            )
            for level in yes_levels
            if len(level) >= 2
        ]

        # Asks (people wanting to sell YES = buy NO)
        asks = [
            OrderBookLevel(
                price=Decimal(str(level[0])) / Decimal("100"),
                size=Decimal(str(level[1])),
            )
            for level in no_levels
            if len(level) >= 2
        ]

        # Sort: bids high to low, asks low to high
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        return OrderBook(
            market_id=market_id,
            bids=bids,
            asks=asks,
        )
