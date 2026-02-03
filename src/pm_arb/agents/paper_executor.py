"""Paper Executor Agent - simulates trade execution without real orders."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import asyncpg
import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Side, Trade, TradeStatus
from pm_arb.db.repository import PaperTradeRepository

logger = structlog.get_logger()


class PaperExecutorAgent(BaseAgent):
    """Simulates trade execution for paper trading mode."""

    def __init__(
        self,
        redis_url: str,
        db_pool: asyncpg.Pool | None = None,
    ) -> None:
        self.name = "paper-executor"
        super().__init__(redis_url)
        self._pending_requests: dict[str, dict[str, Any]] = {}
        self._trades: list[Trade] = []
        self._db_pool = db_pool
        self._repo: PaperTradeRepository | None = None

    async def run(self) -> None:
        """Start agent with state recovery from database."""
        if self._db_pool is not None:
            self._repo = PaperTradeRepository(self._db_pool)
            await self._recover_state()
        await super().run()

    async def _recover_state(self) -> None:
        """Load open trades from database on startup."""
        if self._repo is None:
            return

        open_trades = await self._repo.get_open_trades()
        for row in open_trades:
            trade = Trade(
                id=str(row["id"]),
                request_id=row["opportunity_id"],  # Use opportunity_id as request_id
                market_id=row["market_id"],
                venue=row["venue"],
                side=Side(row["side"]),
                outcome=row["outcome"],
                amount=Decimal(str(row["quantity"])),
                price=Decimal(str(row["price"])),
                fees=Decimal(str(row["fees"])),
                status=TradeStatus.FILLED,
            )
            self._trades.append(trade)

        if open_trades:
            logger.info(
                "state_recovered",
                open_trades=len(open_trades),
            )

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade decisions and requests."""
        return ["trade.decisions", "trade.requests"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Process trade decisions and requests."""
        if channel == "trade.requests":
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
            await self._handle_rejection(request_id, data.get("reason", "Rejected"))

    async def _handle_rejection(self, request_id: str, reason: str) -> None:
        """Handle and persist a rejected trade."""
        request = self._pending_requests.get(request_id)

        # Persist rejection if we have a repo and request
        if self._repo and request:
            await self._repo.insert_trade(
                opportunity_id=request.get("opportunity_id", "unknown"),
                opportunity_type=request.get("opportunity_type", "unknown"),
                market_id=request.get("market_id", "unknown"),
                venue=request.get("market_id", "").split(":")[0] or "unknown",
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

        await self._publish_rejection(request_id, reason)

        # Clean up
        if request_id in self._pending_requests:
            del self._pending_requests[request_id]

    async def _execute_paper_trade(self, request_id: str) -> None:
        """Simulate trade execution."""
        request = self._pending_requests.get(request_id)
        if not request:
            logger.warning("no_pending_request", request_id=request_id)
            return

        fill_price = Decimal(str(request.get("max_price", "0.50")))
        amount = Decimal(str(request.get("amount", "0")))
        market_id = request.get("market_id", "")
        venue = market_id.split(":")[0] if ":" in market_id else "unknown"
        strategy = request.get("strategy", "unknown")
        opportunity_id = request.get("opportunity_id", "unknown")
        opportunity_type = request.get("opportunity_type", "unknown")
        expected_edge = Decimal(str(request.get("expected_edge", "0")))

        trade = Trade(
            id=f"paper-{uuid4().hex[:8]}",
            request_id=request_id,
            market_id=market_id,
            venue=venue,
            side=Side(request.get("side", "buy")),
            outcome=request.get("outcome", "YES"),
            amount=amount,
            price=fill_price,
            fees=amount * Decimal("0.001"),
            status=TradeStatus.FILLED,
        )

        self._trades.append(trade)

        # Persist to database if available
        persisted = False
        if self._repo:
            db_id = await self._repo.insert_trade(
                opportunity_id=opportunity_id,
                opportunity_type=opportunity_type,
                market_id=market_id,
                venue=venue,
                side=trade.side.value,
                outcome=trade.outcome,
                quantity=amount,
                price=fill_price,
                fees=trade.fees,
                expected_edge=expected_edge,
                strategy_id=strategy,
                risk_approved=True,
            )
            persisted = db_id is not None

        simulated_pnl = amount * Decimal("0.05")

        logger.info(
            "paper_trade_executed",
            trade_id=trade.id,
            strategy=strategy,
            market=trade.market_id,
            side=trade.side.value,
            outcome=trade.outcome,
            amount=str(trade.amount),
            price=str(trade.price),
            persisted=persisted,
        )

        await self._publish_trade_result(
            trade, strategy=strategy, pnl=simulated_pnl, paper_trade=True
        )

        del self._pending_requests[request_id]
        await self.publish_state_update()

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
        recent = self._trades[-50:]
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
                for t in reversed(recent)
            ],
        }

    async def publish_state_update(self) -> None:
        """Publish current state to Redis pub/sub for real-time dashboard."""
        import json

        import redis.asyncio as aioredis

        snapshot = self.get_state_snapshot()

        serializable_trades = [
            {
                **trade,
                "amount": str(trade["amount"]),
                "price": str(trade["price"]),
                "fees": str(trade["fees"]),
            }
            for trade in snapshot["recent_trades"][:10]
        ]

        client = aioredis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.publish(
                "trade.results",
                json.dumps(
                    {
                        "agent": self.name,
                        "type": "state_update",
                        "data": {
                            "trade_count": snapshot["trade_count"],
                            "recent_trades": serializable_trades,
                        },
                    }
                ),
            )
        finally:
            await client.aclose()
