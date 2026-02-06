"""Polymarket venue adapter."""

import json
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import (
    Market,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Side,
)

# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Optional: Import CLOB client if available
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, AssetType, BalanceAllowanceParams

    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    ClobClient = None
    ApiCreds = None
    AssetType = None
    BalanceAllowanceParams = None

logger = structlog.get_logger()


def _safe_decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    """Safely convert value to Decimal.

    Args:
        value: Value to convert
        default: Default to return for None/empty values (not for parse errors)

    Returns:
        Decimal value, default for None/empty, or None for parse errors (with logging)
    """
    if value is None or value == "":
        if default is not None:
            logger.debug("decimal_using_default", value=value, default=str(default))
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as e:
        logger.warning(
            "decimal_parse_failed",
            value=value,
            value_type=type(value).__name__,
            error=str(e),
        )
        return None


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
        """Fetch USDC collateral balance from wallet."""
        if not self._clob_client:
            raise RuntimeError("Not authenticated - credentials required")

        params = BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=0,  # EOA wallet
        )
        balance_data = self._clob_client.get_balance_allowance(params)
        return Decimal(str(balance_data.get("balance", "0")))

    async def get_token_id(self, market_id: str, outcome: str) -> str:
        """Resolve token_id from market_id and outcome.

        Args:
            market_id: Market ID in format "polymarket:{condition_id}"
            outcome: "YES" or "NO"

        Returns:
            Token ID for the specified outcome

        Raises:
            ValueError: If market not found or token ID unavailable
        """
        # Extract condition ID from market_id
        external_id = market_id.split(":")[-1] if ":" in market_id else market_id

        if not self._client:
            raise RuntimeError("Not connected")

        # Fetch market data from Gamma API
        response = await self._client.get(
            f"{GAMMA_API}/markets/{external_id}",
        )
        response.raise_for_status()
        data = response.json()

        # Parse clobTokenIds
        raw_token_ids = data.get("clobTokenIds", "[]")
        if isinstance(raw_token_ids, str):
            try:
                token_ids = json.loads(raw_token_ids)
            except json.JSONDecodeError:
                token_ids = []
        else:
            token_ids = raw_token_ids if isinstance(raw_token_ids, list) else []

        if len(token_ids) < 2:
            raise ValueError(f"Market {market_id} has no CLOB token IDs")

        # YES = index 0, NO = index 1
        if outcome.upper() == "YES":
            return str(token_ids[0])
        elif outcome.upper() == "NO":
            return str(token_ids[1])
        else:
            raise ValueError(f"Invalid outcome: {outcome}. Must be 'YES' or 'NO'")

    async def get_markets(self) -> list[Market]:
        """Fetch active markets from Polymarket."""
        raw_markets = await self._fetch_markets()
        markets = []
        for m in raw_markets:
            parsed = self._parse_market(m)
            if parsed is not None:
                markets.append(parsed)
        return markets

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """Fetch raw market data from API."""
        if not self._client:
            raise RuntimeError("Not connected")

        # Fetch most liquid open markets (sorted by 24h volume)
        response = await self._client.get(
            f"{GAMMA_API}/markets",
            params={
                "closed": "false",
                "limit": 200,
                "order": "volume24hr",
                "ascending": "false",
            },
        )
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result

    def _parse_market(self, data: dict[str, Any]) -> Market | None:
        """Parse API response into Market model.

        Returns None if price data is invalid (prevents phantom arbitrage signals).
        """
        market_id = data.get("id", "unknown")
        raw_prices = data.get("outcomePrices", [])

        # outcomePrices may be a JSON-encoded string (e.g., '["0.52", "0.48"]')
        # or already a list - handle both cases
        if isinstance(raw_prices, str):
            try:
                prices = json.loads(raw_prices)
            except json.JSONDecodeError as e:
                logger.warning(
                    "market_prices_json_decode_failed",
                    market_id=market_id,
                    raw_prices=raw_prices[:50] if len(raw_prices) > 50 else raw_prices,
                    error=str(e),
                )
                return None
        else:
            prices = raw_prices

        # Require both YES and NO prices to be valid
        if not isinstance(prices, list) or len(prices) < 2:
            logger.warning(
                "market_missing_prices",
                market_id=market_id,
                prices_count=len(prices) if isinstance(prices, list) else 0,
                prices_type=type(prices).__name__,
            )
            return None

        yes_price = _safe_decimal(prices[0])
        no_price = _safe_decimal(prices[1])

        # Skip market if either price failed to parse
        if yes_price is None or no_price is None:
            logger.warning(
                "market_invalid_prices",
                market_id=market_id,
                yes_raw=prices[0],
                no_raw=prices[1],
                yes_parsed=str(yes_price) if yes_price else None,
                no_parsed=str(no_price) if no_price else None,
            )
            return None

        # Extract CLOB token IDs for order placement
        # clobTokenIds is a JSON string: '["yes_token_id", "no_token_id"]'
        raw_token_ids = data.get("clobTokenIds", "[]")
        if isinstance(raw_token_ids, str):
            try:
                token_ids = json.loads(raw_token_ids)
            except json.JSONDecodeError:
                token_ids = []
        else:
            token_ids = raw_token_ids if isinstance(raw_token_ids, list) else []

        yes_token_id = token_ids[0] if len(token_ids) > 0 else ""
        no_token_id = token_ids[1] if len(token_ids) > 1 else ""

        return Market(
            id=f"polymarket:{market_id}",
            venue="polymarket",
            external_id=market_id,
            title=data.get("question", ""),
            description=data.get("description", ""),
            yes_price=yes_price,
            no_price=no_price,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            volume_24h=_safe_decimal(data.get("volume24hr", 0), Decimal("0")) or Decimal("0"),
            liquidity=_safe_decimal(data.get("liquidity", 0), Decimal("0")) or Decimal("0"),
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

    async def place_order(  # type: ignore[override]
        self,
        token_id: str,
        side: Side,
        amount: Decimal,
        order_type: OrderType,
        price: Decimal | None = None,
    ) -> Order:
        """Place an order on Polymarket.

        Args:
            token_id: The condition token ID to trade
            side: BUY or SELL
            amount: Number of tokens
            order_type: MARKET or LIMIT
            price: Required for limit orders

        Returns:
            Order object with status
        """
        if not self._clob_client:
            raise RuntimeError("Not authenticated - credentials required")

        if order_type == OrderType.LIMIT and price is None:
            raise ValueError("Price required for limit orders")

        from uuid import uuid4

        order_id = f"order-{uuid4().hex[:8]}"

        try:
            # Build order params for py-clob-client
            order_args = {
                "token_id": token_id,
                "side": "BUY" if side == Side.BUY else "SELL",
                "size": float(amount),
            }

            if order_type == OrderType.LIMIT:
                order_args["price"] = float(price)  # type: ignore[arg-type]

            # Place order via CLOB client
            response = self._clob_client.create_and_post_order(order_args)

            # Map status
            status_map = {
                "MATCHED": OrderStatus.FILLED,
                "LIVE": OrderStatus.OPEN,
                "PENDING": OrderStatus.PENDING,
                "CANCELLED": OrderStatus.CANCELLED,
                "REJECTED": OrderStatus.REJECTED,
            }

            status = status_map.get(response.get("status", ""), OrderStatus.PENDING)

            return Order(
                id=order_id,
                external_id=response.get("orderID", ""),
                venue=self.name,
                token_id=token_id,
                side=side,
                order_type=order_type,
                amount=amount,
                price=price,
                filled_amount=Decimal(str(response.get("filledAmount", "0"))),
                average_price=(
                    Decimal(str(response.get("averagePrice", "0")))
                    if response.get("averagePrice")
                    else None
                ),
                status=status,
            )

        except Exception as e:
            logger.error("order_placement_failed", error=str(e), token=token_id)
            return Order(
                id=order_id,
                external_id="",
                venue=self.name,
                token_id=token_id,
                side=side,
                order_type=order_type,
                amount=amount,
                price=price,
                status=OrderStatus.REJECTED,
                error_message=str(e),
            )

    async def get_order_status(self, order_id: str) -> Order:
        """Fetch current status of an order.

        Args:
            order_id: The venue's order ID

        Returns:
            Order with updated status
        """
        if not self._clob_client:
            raise RuntimeError("Not authenticated")

        response = self._clob_client.get_order(order_id)

        status_map = {
            "MATCHED": OrderStatus.FILLED,
            "LIVE": OrderStatus.OPEN,
            "PENDING": OrderStatus.PENDING,
            "CANCELLED": OrderStatus.CANCELLED,
        }

        return Order(
            id=order_id,
            external_id=response.get("orderID", order_id),
            venue=self.name,
            token_id=response.get("tokenID", ""),
            side=Side.BUY if response.get("side") == "BUY" else Side.SELL,
            order_type=OrderType.LIMIT,  # Assume limit for now
            amount=Decimal(str(response.get("size", "0"))),
            price=Decimal(str(response.get("price", "0"))) if response.get("price") else None,
            filled_amount=Decimal(str(response.get("filledAmount", "0"))),
            average_price=(
                Decimal(str(response.get("averagePrice", "0")))
                if response.get("averagePrice")
                else None
            ),
            status=status_map.get(response.get("status", ""), OrderStatus.PENDING),
        )

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.

        Args:
            order_id: The venue's order ID

        Returns:
            True if cancellation succeeded
        """
        if not self._clob_client:
            raise RuntimeError("Not authenticated")

        try:
            result = self._clob_client.cancel(order_id)
            return bool(result.get("success", False))
        except Exception as e:
            logger.error("order_cancel_failed", order_id=order_id, error=str(e))
            return False

    async def get_open_orders(self) -> list[Order]:
        """Get all open orders.

        Returns:
            List of open orders
        """
        if not self._clob_client:
            raise RuntimeError("Not authenticated")

        response = self._clob_client.get_orders()

        orders = []
        for data in response:
            orders.append(
                Order(
                    id=data.get("orderID", ""),
                    external_id=data.get("orderID", ""),
                    venue=self.name,
                    token_id=data.get("tokenID", ""),
                    side=Side.BUY if data.get("side") == "BUY" else Side.SELL,
                    order_type=OrderType.LIMIT,
                    amount=Decimal(str(data.get("size", "0"))),
                    price=Decimal(str(data.get("price", "0"))) if data.get("price") else None,
                    filled_amount=Decimal(str(data.get("filledAmount", "0"))),
                    status=OrderStatus.OPEN,
                )
            )

        return orders
