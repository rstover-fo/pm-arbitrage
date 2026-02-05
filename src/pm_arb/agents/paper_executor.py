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
        self._pending_decisions: dict[str, dict[str, Any]] = {}  # Buffered early decisions
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
        """Process trade decisions and requests.

        Handles race condition where a decision may arrive before its
        corresponding request. Decisions are buffered and matched when
        the request arrives.
        """
        if channel == "trade.requests":
            request_id = data.get("id", "")
            if request_id:
                self._pending_requests[request_id] = data
                # Check if a decision arrived early for this request
                if request_id in self._pending_decisions:
                    decision = self._pending_decisions.pop(request_id)
                    await self._process_decision(decision)
        elif channel == "trade.decisions":
            request_id = data.get("request_id", "")
            if request_id and request_id not in self._pending_requests:
                # Decision arrived before request — buffer it
                self._pending_decisions[request_id] = data
            else:
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

    def _estimate_taker_fee(self, price: Decimal) -> Decimal:
        """Estimate taker fee for 15-min crypto markets.

        Uses the same formula as the opportunity scanner:
            fee_rate = 0.0312 * (0.5 - abs(price - 0.5))
        """
        distance_from_edge = Decimal("0.5") - abs(price - Decimal("0.5"))
        return Decimal("0.0312") * distance_from_edge

    def _is_fee_market(self, market_id: str, opportunity_type: str) -> bool:
        """Check if market charges taker fees (15-min crypto markets)."""
        return opportunity_type == "oracle_lag"

    async def _execute_paper_trade(self, request_id: str) -> None:
        """Simulate trade execution with realistic fees and PnL."""
        request = self._pending_requests.get(request_id)
        if not request:
            logger.warning("no_pending_request", request_id=request_id)
            return

        max_price = Decimal(str(request.get("max_price", "0.50")))
        amount = Decimal(str(request.get("amount", "0")))
        market_id = request.get("market_id", "")
        venue = market_id.split(":")[0] if ":" in market_id else "unknown"
        strategy = request.get("strategy", "unknown")
        opportunity_id = request.get("opportunity_id", "unknown")
        opportunity_type = request.get("opportunity_type", "unknown")
        expected_edge = Decimal(str(request.get("expected_edge", "0")))

        # Simulate realistic slippage: 0.2% adverse price movement
        slippage = max_price * Decimal("0.002")
        fill_price = max_price + slippage  # Slightly worse fill for buys

        # Calculate realistic fees based on market type
        if self._is_fee_market(market_id, opportunity_type):
            fee_rate = self._estimate_taker_fee(fill_price)
        else:
            fee_rate = Decimal("0")
        fees = amount * fee_rate

        trade = Trade(
            id=f"paper-{uuid4().hex[:8]}",
            request_id=request_id,
            market_id=market_id,
            venue=venue,
            side=Side(request.get("side", "buy")),
            outcome=request.get("outcome", "YES"),
            amount=amount,
            price=fill_price,
            fees=fees,
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
                fees=fees,
                expected_edge=expected_edge,
                strategy_id=strategy,
                risk_approved=True,
            )
            persisted = db_id is not None

        # Estimated PnL based on detected edge (already net of fees from scanner)
        # Subtract slippage cost and any additional fee delta
        slippage_cost = amount * Decimal("0.002")
        estimated_pnl = (amount * abs(expected_edge)) - slippage_cost

        logger.info(
            "paper_trade_executed",
            trade_id=trade.id,
            strategy=strategy,
            market=trade.market_id,
            side=trade.side.value,
            outcome=trade.outcome,
            amount=str(trade.amount),
            price=str(trade.price),
            fees=str(fees),
            fee_rate=str(fee_rate),
            expected_edge=str(expected_edge),
            estimated_pnl=str(estimated_pnl),
            persisted=persisted,
        )

        await self._publish_trade_result(
            trade, strategy=strategy, pnl=estimated_pnl, paper_trade=True
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
