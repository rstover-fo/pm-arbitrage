"""Paper Executor Agent - simulates trade execution without real orders."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Side, Trade, TradeStatus

logger = structlog.get_logger()


class PaperExecutorAgent(BaseAgent):
    """Simulates trade execution for paper trading mode."""

    def __init__(self, redis_url: str) -> None:
        self.name = "paper-executor"
        super().__init__(redis_url)
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._trades: list[Trade] = []

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade decisions and requests."""
        return ["trade.decisions", "trade.requests"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Process trade decisions and requests."""
        if channel == "trade.requests":
            # Store pending request for later matching
            request_id = data.get("id", "")
            if request_id:
                self._pending_requests[request_id] = data
        elif channel == "trade.decisions":
            await self._process_decision(data)

    async def _process_decision(self, data: dict[str, Any]) -> None:
        """Process a risk decision."""
        request_id = data.get("request_id", "")
        approved = data.get("approved", False)

        if approved:
            await self._execute_paper_trade(request_id)
        else:
            await self._publish_rejection(request_id, data.get("reason", "Rejected"))

    async def _execute_paper_trade(self, request_id: str) -> None:
        """Simulate trade execution."""
        request = self._pending_requests.get(request_id)
        if not request:
            logger.warning("no_pending_request", request_id=request_id)
            return

        # Simulate fill at max_price (conservative)
        fill_price = Decimal(str(request.get("max_price", "0.50")))
        amount = Decimal(str(request.get("amount", "0")))
        market_id = request.get("market_id", "")
        venue = market_id.split(":")[0] if ":" in market_id else "unknown"
        strategy = request.get("strategy", "unknown")

        trade = Trade(
            id=f"paper-{uuid4().hex[:8]}",
            request_id=request_id,
            market_id=market_id,
            venue=venue,
            side=Side(request.get("side", "buy")),
            outcome=request.get("outcome", "YES"),
            amount=amount,
            price=fill_price,
            fees=amount * Decimal("0.001"),  # Simulate 0.1% fee
            status=TradeStatus.FILLED,
        )

        self._trades.append(trade)

        # Simulate P&L (for paper trading, assume small random profit/loss)
        # In real trading, P&L would be calculated when position closes
        simulated_pnl = amount * Decimal("0.05")  # Assume 5% profit for demo

        logger.info(
            "paper_trade_executed",
            trade_id=trade.id,
            strategy=strategy,
            market=trade.market_id,
            side=trade.side.value,
            outcome=trade.outcome,
            amount=str(trade.amount),
            price=str(trade.price),
        )

        await self._publish_trade_result(
            trade, strategy=strategy, pnl=simulated_pnl, paper_trade=True
        )

        # Clean up pending request
        del self._pending_requests[request_id]

    async def _publish_rejection(self, request_id: str, reason: str) -> None:
        """Publish rejection result."""
        await self.publish(
            "trade.results",
            {
                "request_id": request_id,
                "status": TradeStatus.REJECTED.value,
                "reason": reason,
                "executed_at": datetime.now(UTC).isoformat(),
            },
        )

    async def _publish_trade_result(
        self,
        trade: Trade,
        strategy: str = "unknown",
        pnl: Decimal = Decimal("0"),
        paper_trade: bool = True,
    ) -> None:
        """Publish trade execution result."""
        await self.publish(
            "trade.results",
            {
                "id": trade.id,
                "request_id": trade.request_id,
                "strategy": strategy,
                "market_id": trade.market_id,
                "venue": trade.venue,
                "side": trade.side.value,
                "outcome": trade.outcome,
                "amount": str(trade.amount),
                "price": str(trade.price),
                "fees": str(trade.fees),
                "pnl": str(pnl),
                "status": trade.status.value,
                "executed_at": trade.executed_at.isoformat(),
                "paper_trade": paper_trade,
            },
        )

    def get_state_snapshot(self) -> dict[str, Any]:
        """Return trade history snapshot for dashboard."""
        recent = self._trades[-50:]  # Last 50 trades
        return {
            "trade_count": len(self._trades),
            "recent_trades": [
                {
                    "id": t.id,
                    "request_id": t.request_id,
                    "market_id": t.market_id,
                    "venue": t.venue,
                    "side": t.side.value,
                    "outcome": t.outcome,
                    "amount": t.amount,
                    "price": t.price,
                    "fees": t.fees,
                    "status": t.status.value,
                    "executed_at": t.executed_at.isoformat(),
                }
                for t in reversed(recent)  # Most recent first
            ],
        }

    async def publish_state_update(self) -> None:
        """Publish current state to Redis pub/sub for real-time dashboard."""
        import json

        import redis.asyncio as aioredis

        snapshot = self.get_state_snapshot()

        client = aioredis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.publish(
                "trade.results",
                json.dumps({
                    "agent": self.name,
                    "type": "state_update",
                    "data": {
                        "trade_count": snapshot["trade_count"],
                        "recent_trades": snapshot["recent_trades"][:10],
                    },
                }),
            )
        finally:
            await client.aclose()
