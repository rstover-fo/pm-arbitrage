"""Live Executor Agent - executes real trades on venues."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import asyncpg
import structlog

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.alerts import AlertService
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import Order, OrderStatus, OrderType, Side, Trade, TradeStatus
from pm_arb.db.repository import PaperTradeRepository

logger = structlog.get_logger()


class LiveExecutorAgent(BaseAgent):
    """Executes real trades via venue adapters."""

    def __init__(
        self,
        redis_url: str,
        credentials: dict[str, PolymarketCredentials],
        db_pool: asyncpg.Pool | None = None,
    ) -> None:
        self.name = "live-executor"
        super().__init__(redis_url)
        self._credentials = credentials
        self._adapters: dict[str, PolymarketAdapter] = {}
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._db_pool = db_pool
        self._repo: PaperTradeRepository | None = None
        self._alerts = AlertService()
        self._trades: list[Trade] = []

    async def run(self) -> None:
        """Start agent with database repository initialization."""
        if self._db_pool is not None:
            self._repo = PaperTradeRepository(self._db_pool)
        await super().run()

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade decisions and requests (matching paper executor)."""
        return ["trade.decisions", "trade.requests"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Process trade decisions and requests."""
        if channel == "trade.requests":
            # Cache request for later lookup
            request_id = data.get("id", "")
            if request_id:
                self._pending_requests[request_id] = data
        elif channel == "trade.decisions":
            # Only execute if approved
            if data.get("approved", False):
                await self._execute_trade(data)
            else:
                await self._handle_rejection(data)

    def _get_adapter(self, venue: str) -> PolymarketAdapter:
        """Get or create adapter for venue."""
        if venue not in self._adapters:
            if venue not in self._credentials:
                raise ValueError(f"No credentials for venue: {venue}")
            self._adapters[venue] = PolymarketAdapter(credentials=self._credentials[venue])
        return self._adapters[venue]

    async def _handle_rejection(self, data: dict[str, Any]) -> None:
        """Handle a rejected trade decision."""
        request_id = data.get("request_id", "")
        reason = data.get("reason", "Rejected")
        request = self._pending_requests.get(request_id)

        logger.info(
            "trade_rejected",
            request_id=request_id,
            reason=reason,
        )

        # Persist rejection to database
        if self._repo and request:
            await self._repo.insert_trade(
                opportunity_id=request.get("opportunity_id", "unknown"),
                opportunity_type=request.get("opportunity_type", "unknown"),
                market_id=request.get("market_id", "unknown"),
                venue=request.get("market_id", "").split(":")[0] or "polymarket",
                side=request.get("side", "buy"),
                outcome=request.get("outcome", "YES"),
                quantity=Decimal(str(request.get("amount", "0"))),
                price=Decimal(str(request.get("max_price", "0"))),
                fees=Decimal("0"),
                expected_edge=Decimal(str(request.get("expected_edge", "0"))),
                strategy_id=request.get("strategy"),
                risk_approved=False,
                risk_rejection_reason=reason,
            )

        await self.publish(
            "trade.results",
            {
                "request_id": request_id,
                "status": TradeStatus.REJECTED.value,
                "reason": reason,
                "executed_at": datetime.now(UTC).isoformat(),
            },
        )

        # Clean up pending request
        if request_id in self._pending_requests:
            del self._pending_requests[request_id]

    async def _execute_trade(self, data: dict[str, Any]) -> None:
        """Execute a single trade.

        Args:
            data: Risk decision data with request_id to look up original request.
        """
        request_id = data.get("request_id", "unknown")

        # Look up original request for trade details
        request = self._pending_requests.get(request_id, data)
        market_id = request.get("market_id", "")

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

            # Place the order - use request data for trade details
            side = Side.BUY if request.get("side", "").lower() == "buy" else Side.SELL
            amount = Decimal(str(request.get("amount", "0")))
            token_id = request.get("token_id", "")

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
                request=request,
            )

        except Exception as e:
            logger.error(
                "trade_execution_failed",
                request_id=request_id,
                error=str(e),
            )
            await self._publish_failure(request_id, str(e), market_id=market_id, request=request)

        finally:
            # Always clean up pending request
            if request_id in self._pending_requests:
                del self._pending_requests[request_id]

    async def _publish_result(
        self,
        request_id: str,
        order: Order,
        request: dict[str, Any] | None = None,
    ) -> None:
        """Publish trade execution result, persist to DB, and send alert."""
        status_map = {
            OrderStatus.FILLED: "filled",
            OrderStatus.PARTIALLY_FILLED: "partial",
            OrderStatus.OPEN: "open",
            OrderStatus.REJECTED: "rejected",
            OrderStatus.CANCELLED: "cancelled",
        }

        market_id = request.get("market_id", "unknown") if request else "unknown"
        venue = market_id.split(":")[0] if ":" in market_id else "polymarket"

        # Persist successful trade to database
        persisted = False
        filled_statuses = (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED)
        if self._repo and request and order.status in filled_statuses:
            fill_price = order.average_price or Decimal("0")
            db_id = await self._repo.insert_trade(
                opportunity_id=request.get("opportunity_id", "unknown"),
                opportunity_type=request.get("opportunity_type", "unknown"),
                market_id=market_id,
                venue=venue,
                side=order.side.value,
                outcome=request.get("outcome", "YES"),
                quantity=order.filled_amount,
                price=fill_price,
                fees=Decimal("0"),  # Polymarket fees handled in price
                expected_edge=Decimal(str(request.get("expected_edge", "0"))),
                strategy_id=request.get("strategy"),
                risk_approved=True,
            )
            persisted = db_id is not None

            # Track trade in memory
            trade = Trade(
                id=f"live-{order.external_id}",
                request_id=request_id,
                market_id=market_id,
                venue=venue,
                side=order.side,
                outcome=request.get("outcome", "YES"),
                amount=order.filled_amount,
                price=fill_price,
                fees=Decimal("0"),
                status=TradeStatus.FILLED,
                external_id=order.external_id,
            )
            self._trades.append(trade)

        result = {
            "request_id": request_id,
            "order_id": order.external_id,
            "status": status_map.get(order.status, "unknown"),
            "filled_amount": str(order.filled_amount),
            "average_price": str(order.average_price) if order.average_price else None,
            "error": order.error_message,
            "paper_trade": False,
        }

        await self.publish("trade.results", result)

        # Send alerts for trade execution
        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            await self._alerts.trade_executed(
                market=market_id,
                side=order.side.value,
                amount=str(order.filled_amount),
                price=str(order.average_price) if order.average_price else "market",
            )
        elif order.status == OrderStatus.REJECTED:
            await self._alerts.trade_failed(
                market=market_id,
                error=order.error_message or "Order rejected",
            )

        logger.info(
            "trade_result_published",
            request_id=request_id,
            status=result["status"],
            persisted=persisted,
        )

    async def _publish_failure(
        self,
        request_id: str,
        error: str,
        market_id: str = "unknown",
        request: dict[str, Any] | None = None,
    ) -> None:
        """Publish trade execution failure, persist to DB, and send alert."""
        # Persist failure to database
        if self._repo and request:
            venue = market_id.split(":")[0] if ":" in market_id else "polymarket"
            await self._repo.insert_trade(
                opportunity_id=request.get("opportunity_id", "unknown"),
                opportunity_type=request.get("opportunity_type", "unknown"),
                market_id=market_id,
                venue=venue,
                side=request.get("side", "buy"),
                outcome=request.get("outcome", "YES"),
                quantity=Decimal(str(request.get("amount", "0"))),
                price=Decimal(str(request.get("max_price", "0"))),
                fees=Decimal("0"),
                expected_edge=Decimal(str(request.get("expected_edge", "0"))),
                strategy_id=request.get("strategy"),
                risk_approved=True,
                risk_rejection_reason=f"Execution failed: {error}",
            )

        await self.publish(
            "trade.results",
            {
                "request_id": request_id,
                "status": "rejected",
                "error": error,
                "paper_trade": False,
            },
        )

        # Send alert for failure
        await self._alerts.trade_failed(
            market=market_id,
            error=error,
        )
