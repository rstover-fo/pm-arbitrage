"""Live Executor Agent - executes real trades on venues."""

from decimal import Decimal
from typing import Any

import structlog

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import Order, OrderStatus, OrderType, Side

logger = structlog.get_logger()


class LiveExecutorAgent(BaseAgent):
    """Executes real trades via venue adapters."""

    def __init__(
        self,
        redis_url: str,
        credentials: dict[str, PolymarketCredentials],
    ) -> None:
        self.name = "live-executor"
        super().__init__(redis_url)
        self._credentials = credentials
        self._adapters: dict[str, PolymarketAdapter] = {}

    def get_subscriptions(self) -> list[str]:
        """Subscribe to approved trade decisions."""
        return ["trade.approved"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Execute approved trades."""
        if channel == "trade.approved":
            await self._execute_trade(data)

    def _get_adapter(self, venue: str) -> PolymarketAdapter:
        """Get or create adapter for venue."""
        if venue not in self._adapters:
            if venue not in self._credentials:
                raise ValueError(f"No credentials for venue: {venue}")
            self._adapters[venue] = PolymarketAdapter(credentials=self._credentials[venue])
        return self._adapters[venue]

    async def _execute_trade(self, data: dict[str, Any]) -> None:
        """Execute a single trade.

        Args:
            data: Trade request data including market_id, side, amount, etc.
        """
        request_id = data.get("request_id", "unknown")
        market_id = data.get("market_id", "")

        # Extract venue from market_id (format: "venue:external_id")
        venue = market_id.split(":")[0] if ":" in market_id else "polymarket"

        logger.info(
            "executing_trade",
            request_id=request_id,
            market_id=market_id,
            venue=venue,
        )

        try:
            adapter = self._get_adapter(venue)

            if not adapter.is_connected:
                await adapter.connect()

            # Place the order
            side = Side.BUY if data.get("side", "").lower() == "buy" else Side.SELL
            amount = Decimal(str(data.get("amount", "0")))
            token_id = data.get("token_id", "")

            order = await adapter.place_order(
                token_id=token_id,
                side=side,
                amount=amount,
                order_type=OrderType.MARKET,  # Market orders for now
            )

            # Publish result
            await self._publish_result(
                request_id=request_id,
                order=order,
            )

        except Exception as e:
            logger.error(
                "trade_execution_failed",
                request_id=request_id,
                error=str(e),
            )
            await self._publish_failure(request_id, str(e))

    async def _publish_result(
        self,
        request_id: str,
        order: Order,
    ) -> None:
        """Publish trade execution result."""
        status_map = {
            OrderStatus.FILLED: "filled",
            OrderStatus.PARTIALLY_FILLED: "partial",
            OrderStatus.OPEN: "open",
            OrderStatus.REJECTED: "rejected",
            OrderStatus.CANCELLED: "cancelled",
        }

        result = {
            "request_id": request_id,
            "order_id": order.external_id,
            "status": status_map.get(order.status, "unknown"),
            "filled_amount": str(order.filled_amount),
            "average_price": str(order.average_price) if order.average_price else None,
            "error": order.error_message,
        }

        await self.publish("trade.results", result)

        logger.info(
            "trade_result_published",
            request_id=request_id,
            status=result["status"],
        )

    async def _publish_failure(self, request_id: str, error: str) -> None:
        """Publish trade execution failure."""
        await self.publish(
            "trade.results",
            {
                "request_id": request_id,
                "status": "rejected",
                "error": error,
            },
        )
