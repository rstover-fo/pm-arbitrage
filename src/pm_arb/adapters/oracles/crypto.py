"""Binance crypto price oracle."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import structlog
import websockets

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData

logger = structlog.get_logger()

BINANCE_REST = "https://api.binance.com/api/v3"
BINANCE_WS = "wss://stream.binance.com:9443/ws"


class BinanceOracle(OracleAdapter):
    """Real-time crypto prices from Binance."""

    name = "binance"

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscribed_symbols: list[str] = []

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)
        self._connected = True
        logger.info("binance_connected")

    async def disconnect(self) -> None:
        """Close connections."""
        if self._client:
            await self._client.aclose()
        if self._ws:
            await self._ws.close()
        self._connected = False
        logger.info("binance_disconnected")

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current price for symbol (e.g., BTC, ETH)."""
        data = await self._fetch_price(symbol)
        if not data:
            return None

        return OracleData(
            source="binance",
            symbol=symbol.upper(),
            value=Decimal(str(data["price"])),
            timestamp=datetime.now(UTC),
        )

    async def _fetch_price(self, symbol: str) -> dict | None:
        """Fetch price from REST API."""
        if not self._client:
            raise RuntimeError("Not connected")

        ticker = f"{symbol.upper()}USDT"
        try:
            response = await self._client.get(
                f"{BINANCE_REST}/ticker/price",
                params={"symbol": ticker},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("binance_fetch_error", symbol=symbol, error=str(e))
            return None

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to real-time price updates via WebSocket."""
        self._subscribed_symbols = symbols
        streams = [f"{s.lower()}usdt@ticker" for s in symbols]
        stream_url = f"{BINANCE_WS}/{'/'.join(streams)}"

        self._ws = await websockets.connect(stream_url)
        logger.info("binance_ws_subscribed", symbols=symbols)

    async def stream(self) -> AsyncIterator[OracleData]:
        """Stream real-time price updates."""
        if not self._ws:
            raise RuntimeError("Not subscribed to any symbols")

        async for message in self._ws:
            data = json.loads(message)

            # Extract symbol from stream name (e.g., "btcusdt" -> "BTC")
            symbol = data.get("s", "").replace("USDT", "")

            yield OracleData(
                source="binance",
                symbol=symbol,
                value=Decimal(str(data.get("c", 0))),  # "c" is current price
                timestamp=datetime.now(UTC),
                metadata={
                    "high_24h": data.get("h"),
                    "low_24h": data.get("l"),
                    "volume_24h": data.get("v"),
                },
            )
