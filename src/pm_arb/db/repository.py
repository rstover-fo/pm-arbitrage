"""Repository for paper trade persistence."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg
import structlog

logger = structlog.get_logger()


class PaperTradeRepository:
    """Repository for paper trade CRUD operations."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def insert_trade(
        self,
        *,
        opportunity_id: str,
        opportunity_type: str,
        market_id: str,
        venue: str,
        side: str,
        outcome: str,
        quantity: Decimal,
        price: Decimal,
        fees: Decimal,
        expected_edge: Decimal,
        strategy_id: str | None = None,
        risk_approved: bool = True,
        risk_rejection_reason: str | None = None,
    ) -> UUID | None:
        """Insert a new paper trade and return its ID.

        Returns None if trade already exists (duplicate).
        """
        async with self._pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO paper_trades (
                        opportunity_id, opportunity_type, market_id, venue,
                        side, outcome, quantity, price, fees, expected_edge,
                        strategy_id, risk_approved, risk_rejection_reason
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    RETURNING id
                    """,
                    opportunity_id,
                    opportunity_type,
                    market_id,
                    venue,
                    side,
                    outcome,
                    quantity,
                    price,
                    fees,
                    expected_edge,
                    strategy_id,
                    risk_approved,
                    risk_rejection_reason,
                )
                return row["id"]
            except asyncpg.UniqueViolationError:
                logger.warning(
                    "duplicate_trade_skipped",
                    opportunity_id=opportunity_id,
                    market_id=market_id,
                    side=side,
                )
                return None

    async def get_trade(self, trade_id: UUID) -> dict[str, Any] | None:
        """Get a single trade by ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM paper_trades WHERE id = $1",
                trade_id,
            )
            return dict(row) if row else None

    async def get_trades_since_days(self, days: int = 1) -> list[dict[str, Any]]:
        """Get all trades from the last N days."""
        since = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM paper_trades
                WHERE created_at >= $1
                ORDER BY created_at DESC
                """,
                since,
            )
            return [dict(row) for row in rows]

    async def get_open_trades(self) -> list[dict[str, Any]]:
        """Get all open trades (for state recovery on restart)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM paper_trades
                WHERE status = 'open' AND risk_approved = true
                ORDER BY created_at DESC
                """
            )
            return [dict(row) for row in rows]

    async def update_trade_result(
        self,
        trade_id: UUID,
        *,
        status: str,
        exit_price: Decimal | None = None,
        realized_pnl: Decimal | None = None,
    ) -> None:
        """Update trade with exit information."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE paper_trades
                SET status = $2, exit_price = $3, realized_pnl = $4, resolved_at = $5
                WHERE id = $1
                """,
                trade_id,
                status,
                exit_price,
                realized_pnl,
                datetime.now(UTC) if status in ("closed", "resolved") else None,
            )

    async def get_daily_summary(self, days: int = 1) -> dict[str, Any]:
        """Get aggregated summary for the last N days."""
        since = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.acquire() as conn:
            # Total trades and P&L
            totals = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_trades,
                    COUNT(*) FILTER (WHERE status = 'open') as open_trades,
                    COUNT(*) FILTER (WHERE status IN ('closed', 'resolved')) as closed_trades,
                    COALESCE(SUM(realized_pnl) FILTER (WHERE realized_pnl IS NOT NULL), 0) as realized_pnl,
                    COUNT(*) FILTER (WHERE realized_pnl > 0) as wins,
                    COUNT(*) FILTER (WHERE realized_pnl < 0) as losses,
                    COUNT(*) FILTER (WHERE NOT risk_approved) as rejections
                FROM paper_trades
                WHERE created_at >= $1
                """,
                since,
            )

            # By opportunity type
            by_type = await conn.fetch(
                """
                SELECT
                    opportunity_type,
                    COUNT(*) as trades,
                    COALESCE(SUM(realized_pnl), 0) as pnl
                FROM paper_trades
                WHERE created_at >= $1 AND risk_approved = true
                GROUP BY opportunity_type
                ORDER BY trades DESC
                """,
                since,
            )

            # Risk rejections by reason
            rejections = await conn.fetch(
                """
                SELECT
                    risk_rejection_reason,
                    COUNT(*) as count
                FROM paper_trades
                WHERE created_at >= $1 AND NOT risk_approved
                GROUP BY risk_rejection_reason
                """,
                since,
            )

            closed = totals["closed_trades"] or 0
            wins = totals["wins"] or 0

            return {
                "total_trades": totals["total_trades"],
                "open_trades": totals["open_trades"],
                "closed_trades": closed,
                "realized_pnl": float(totals["realized_pnl"]),
                "wins": wins,
                "losses": totals["losses"] or 0,
                "win_rate": wins / closed if closed > 0 else 0.0,
                "rejections": totals["rejections"] or 0,
                "by_opportunity_type": [
                    {
                        "type": row["opportunity_type"],
                        "trades": row["trades"],
                        "pnl": float(row["pnl"]),
                    }
                    for row in by_type
                ],
                "risk_rejections": [
                    {"reason": row["risk_rejection_reason"], "count": row["count"]}
                    for row in rejections
                ],
            }
