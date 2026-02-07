"""Live Executor Agent - executes real trades on venues."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import asyncpg
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.alerts import AlertService
from pm_arb.core.models import Side, Trade, TradeRequest, TradeStatus
from pm_arb.db.repository import PaperTradeRepository

logger = structlog.get_logger()


class LiveExecutorAgent(BaseAgent):
    """Executes real trades via venue adapters."""

    def __init__(
        self,
        redis_url: str,
        adapters: dict[str, VenueAdapter],
        db_pool: asyncpg.Pool | None = None,
    ) -> None:
        self.name = "live-executor"
        super().__init__(redis_url)
        self._adapters: dict[str, VenueAdapter] = adapters
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._pending_decisions: dict[str, dict[str, Any]] = {}  # Buffered early decisions
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
        """Process trade decisions and requests.

        Handles race condition where a decision may arrive before its
        corresponding request. Decisions are buffered and matched when
        the request arrives.
        """
        if channel == "trade.requests":
            # Cache request for later lookup
            request_id = data.get("id", "")
            if request_id:
                self._pending_requests[request_id] = data
                # Check if a decision arrived early for this request
                if request_id in self._pending_decisions:
                    decision = self._pending_decisions.pop(request_id)
                    if decision.get("approved", False):
                        await self._execute_trade(decision)
                    else:
                        await self._handle_rejection(decision)
        elif channel == "trade.decisions":
            request_id = data.get("request_id", "")
            if request_id and request_id not in self._pending_requests:
                # Decision arrived before request — buffer it
                self._pending_decisions[request_id] = data
            else:
                if data.get("approved", False):
                    await self._execute_trade(data)
                else:
                    await self._handle_rejection(data)

    def _get_adapter(self, venue: str) -> VenueAdapter:
        """Get adapter for venue.

        Raises:
            ValueError: If no adapter configured for the venue.
        """
        if venue not in self._adapters:
            raise ValueError(f"No adapter configured for venue: {venue}")
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
        """Execute a single trade via the generic VenueAdapter interface.

        Args:
            data: Risk decision data with request_id to look up original request.
        """
        request_id = data.get("request_id", "unknown")

        # Look up original request for trade details
        request = self._pending_requests.get(request_id, data)
        market_id = request.get("market_id", "")

        # Extract venue from market_id (format: "venue:external_id")
        venue = market_id.split(":")[0] if ":" in market_id else "unknown"

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

            # Build TradeRequest from the pending request data
            trade_request = TradeRequest(
                id=request_id,
                opportunity_id=request.get("opportunity_id", "unknown"),
                strategy=request.get("strategy", "unknown"),
                market_id=market_id,
                side=Side(request.get("side", "buy")),
                outcome=request.get("outcome", "YES"),
                amount=Decimal(str(request.get("amount", "0"))),
                max_price=Decimal(str(request.get("max_price", "1"))),
                expected_edge=Decimal(str(request.get("expected_edge", "0"))),
            )

            # Pre-check: Verify sufficient balance before placing order
            required_balance = trade_request.amount * trade_request.max_price

            try:
                balance = await adapter.get_balance()
                if balance < required_balance:
                    error_msg = (
                        f"Insufficient balance: ${balance:.2f} < ${required_balance:.2f} required"
                    )
                    logger.error(
                        "insufficient_balance",
                        request_id=request_id,
                        required=str(required_balance),
                        available=str(balance),
                    )
                    await self._publish_failure(
                        request_id, error_msg, market_id=market_id, request=request
                    )
                    return
            except (RuntimeError, NotImplementedError) as e:
                # Not authenticated or adapter doesn't support balance check
                logger.warning("balance_check_skipped", reason=str(e))

            # Place order via generic VenueAdapter interface
            trade = await adapter.place_order(trade_request)

            # Publish result
            await self._publish_trade_result(
                trade=trade,
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

    async def _publish_trade_result(
        self,
        trade: Trade,
        request: dict[str, Any] | None = None,
    ) -> None:
        """Publish trade execution result, persist to DB, and send alert."""
        # Persist successful trade to database
        persisted = False
        filled_statuses = (TradeStatus.FILLED, TradeStatus.PARTIAL)
        if self._repo and request and trade.status in filled_statuses:
            db_id = await self._repo.insert_trade(
                opportunity_id=request.get("opportunity_id", "unknown"),
                opportunity_type=request.get("opportunity_type", "unknown"),
                market_id=trade.market_id,
                venue=trade.venue,
                side=trade.side.value,
                outcome=trade.outcome,
                quantity=trade.amount,
                price=trade.price,
                fees=trade.fees,
                expected_edge=Decimal(str(request.get("expected_edge", "0"))),
                strategy_id=request.get("strategy"),
                risk_approved=True,
            )
            persisted = db_id is not None

        # Track trade in memory
        self._trades.append(trade)

        result = {
            "request_id": trade.request_id,
            "order_id": trade.external_id or "",
            "status": trade.status.value,
            "filled_amount": str(trade.amount),
            "average_price": str(trade.price),
            "paper_trade": False,
        }

        await self.publish("trade.results", result)

        # Send alerts for trade execution
        if trade.status in filled_statuses:
            await self._alerts.trade_executed(
                market=trade.market_id,
                side=trade.side.value,
                amount=str(trade.amount),
                price=str(trade.price),
            )
        elif trade.status == TradeStatus.FAILED:
            await self._alerts.trade_failed(
                market=trade.market_id,
                error="Trade execution failed",
            )

        logger.info(
            "trade_result_published",
            request_id=trade.request_id,
            status=trade.status.value,
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
