# Paper Trading Pilot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable running all agents together with persistent trade storage and real-time monitoring to validate the arbitrage system over days/weeks before live trading.

**Architecture:** Add PostgreSQL persistence layer to `PaperExecutorAgent`, create an orchestrator that manages all agents with health checks and auto-restart, add a CLI report command, and extend the Streamlit dashboard with a Pilot Monitor tab and How It Works explainer.

**Tech Stack:** asyncpg (async Postgres), click (CLI), rich (formatting), Streamlit, Plotly

---

## Review Notes

**Plan reviewed by:** Cassandra (architecture/security) and Marie Kondo (task sizing)

**Key fixes incorporated:**
- Unique constraint on `(opportunity_id, market_id, side)` to prevent duplicate trades
- State recovery on agent restart (load open trades from DB)
- Dashboard pool lifecycle via `@st.cache_resource`
- Cross-platform signal handling (Windows compatibility)
- Proper pool cleanup with try/finally in CLI

**Task breakdown:** Original 8 tasks split into 13 focused tasks with clear dependencies.

---

## Dependency Graph

```
Task 1 (schema)
    │
    ▼
Task 2 (repo core)
    │
    ├──────────────────────────┐
    ▼                          ▼
Task 3 (repo tests)      Task 4 (repo summary)
                               │
                               ▼
                         Task 5 (executor persistence)
                               │
                               ▼
                         Task 6 (executor tests)
                               │
                               ▼
                         Task 7 (orchestrator)
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              Task 10 (CLI pilot)   Task 13 (integration)

Task 8 (CLI scaffold) ──▶ Task 9 (CLI report) ◀── Task 4
                     └──▶ Task 10 (CLI pilot)

Task 4 ──▶ Task 11 (dashboard pilot monitor)

Task 12 (how it works) — independent, can run anytime
```

---

## Task 1: Database Schema & Connection Module

**Priority**: P0 | **Complexity**: Small | **Blocked By**: None

**Files:**
- Create: `src/pm_arb/db/__init__.py`
- Create: `src/pm_arb/db/schema.sql`
- Create: `src/pm_arb/db/connection.py`

**Step 1: Create the db module init**

```python
# src/pm_arb/db/__init__.py
"""Database module for paper trade persistence."""

from pm_arb.db.connection import close_pool, get_pool, init_db

__all__ = ["close_pool", "get_pool", "init_db"]
```

**Step 2: Create the schema file**

```sql
-- src/pm_arb/db/schema.sql
-- Paper trades table for pilot persistence

CREATE TABLE IF NOT EXISTS paper_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Opportunity context
    opportunity_id TEXT NOT NULL,
    opportunity_type TEXT NOT NULL,
    market_id TEXT NOT NULL,
    venue TEXT NOT NULL,

    -- Trade details
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    quantity DECIMAL NOT NULL,
    price DECIMAL NOT NULL,
    fees DECIMAL NOT NULL DEFAULT 0,
    expected_edge DECIMAL NOT NULL,

    -- Risk context
    strategy_id TEXT,
    risk_approved BOOLEAN NOT NULL DEFAULT true,
    risk_rejection_reason TEXT,

    -- Simulated result
    status TEXT NOT NULL DEFAULT 'open',
    exit_price DECIMAL,
    realized_pnl DECIMAL,
    resolved_at TIMESTAMPTZ
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_paper_trades_created ON paper_trades(created_at);
CREATE INDEX IF NOT EXISTS idx_paper_trades_market ON paper_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_opportunity_type ON paper_trades(opportunity_type);

-- Prevent duplicate trades from same opportunity (race condition protection)
CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_trades_opportunity_unique
ON paper_trades(opportunity_id, market_id, side);
```

**Step 3: Create the connection module**

```python
# src/pm_arb/db/connection.py
"""Database connection management."""

from pathlib import Path

import asyncpg

from pm_arb.core.config import settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the database connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
        )
    return _pool


async def init_db() -> None:
    """Initialize database schema."""
    pool = await get_pool()
    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)


async def close_pool() -> None:
    """Close the database connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
```

**Step 4: Verify schema manually**

Run: `docker-compose up -d postgres`
Run: `psql postgresql://pm_arb:pm_arb@localhost:5432/pm_arb -f src/pm_arb/db/schema.sql`

Expected: Tables and indexes created successfully

**Step 5: Commit**

```bash
git add src/pm_arb/db/
git commit -m "feat: add database schema for paper trade persistence"
```

---

## Task 2: Paper Trade Repository (Core CRUD)

**Priority**: P0 | **Complexity**: Small | **Blocked By**: Task 1

**Files:**
- Create: `src/pm_arb/db/repository.py`

**Step 1: Create the repository**

```python
# src/pm_arb/db/repository.py
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
```

**Step 2: Commit**

```bash
git add src/pm_arb/db/repository.py
git commit -m "feat: add paper trade repository with core CRUD"
```

---

## Task 3: Repository Tests & Fixtures

**Priority**: P0 | **Complexity**: Small | **Blocked By**: Task 2

**Files:**
- Create: `tests/db/__init__.py`
- Create: `tests/db/test_repository.py`
- Modify: `tests/conftest.py`

**Step 1: Create test init**

```python
# tests/db/__init__.py
"""Database tests."""
```

**Step 2: Add database fixture to conftest**

```python
# tests/conftest.py — add these imports and fixture
from pathlib import Path

import asyncpg
import pytest_asyncio

from pm_arb.core.config import settings


@pytest_asyncio.fixture
async def test_db_pool():
    """Create a test database pool with clean state."""
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=5,
    )

    # Initialize schema
    schema_path = Path(__file__).parent.parent / "src/pm_arb/db/schema.sql"
    schema_sql = schema_path.read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)

    yield pool

    # Clean up test data
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM paper_trades")

    await pool.close()
```

**Step 3: Write repository tests**

```python
# tests/db/test_repository.py
"""Tests for paper trade repository."""

from decimal import Decimal
from uuid import uuid4

import pytest

from pm_arb.db.repository import PaperTradeRepository


@pytest.fixture
def repo(test_db_pool):
    """Create repository with test pool."""
    return PaperTradeRepository(test_db_pool)


@pytest.mark.asyncio
async def test_insert_and_get_trade(repo):
    """Test inserting and retrieving a paper trade."""
    trade_id = await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
        strategy_id="oracle-sniper",
    )

    assert trade_id is not None

    trade = await repo.get_trade(trade_id)
    assert trade is not None
    assert trade["opportunity_type"] == "oracle_lag"
    assert trade["market_id"] == "polymarket:btc-100k"
    assert trade["status"] == "open"


@pytest.mark.asyncio
async def test_duplicate_trade_returns_none(repo):
    """Test that duplicate trades are handled gracefully."""
    opp_id = f"opp-{uuid4().hex[:8]}"

    # First insert succeeds
    trade_id_1 = await repo.insert_trade(
        opportunity_id=opp_id,
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )
    assert trade_id_1 is not None

    # Duplicate returns None (same opportunity_id + market_id + side)
    trade_id_2 = await repo.insert_trade(
        opportunity_id=opp_id,
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )
    assert trade_id_2 is None


@pytest.mark.asyncio
async def test_get_trades_by_date_range(repo):
    """Test retrieving trades within a date range."""
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="mispricing",
        market_id="polymarket:eth-5k",
        venue="polymarket",
        side="sell",
        outcome="NO",
        quantity=Decimal("5.00"),
        price=Decimal("0.48"),
        fees=Decimal("0.005"),
        expected_edge=Decimal("0.03"),
        strategy_id="mispricing-hunter",
    )

    trades = await repo.get_trades_since_days(days=1)
    assert len(trades) >= 1
    assert trades[0]["opportunity_type"] == "mispricing"


@pytest.mark.asyncio
async def test_get_open_trades(repo):
    """Test retrieving open trades for state recovery."""
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )

    open_trades = await repo.get_open_trades()
    assert len(open_trades) >= 1
    assert open_trades[0]["status"] == "open"
```

**Step 4: Run tests**

Run: `pytest tests/db/test_repository.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
git add tests/db/ tests/conftest.py
git commit -m "test: add repository tests and database fixtures"
```

---

## Task 4: Repository Summary Queries

**Priority**: P0 | **Complexity**: Small | **Blocked By**: Task 2

**Files:**
- Modify: `src/pm_arb/db/repository.py`
- Modify: `tests/db/test_repository.py`

**Step 1: Add summary method to repository**

```python
# Add to src/pm_arb/db/repository.py

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
```

**Step 2: Add summary test**

```python
# Add to tests/db/test_repository.py

@pytest.mark.asyncio
async def test_get_daily_summary(repo):
    """Test daily summary aggregation."""
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
        strategy_id="oracle-sniper",
    )

    summary = await repo.get_daily_summary(days=1)
    assert summary["total_trades"] >= 1
    assert "by_opportunity_type" in summary
    assert "win_rate" in summary
```

**Step 3: Run tests**

Run: `pytest tests/db/test_repository.py -v`

Expected: All tests PASS

**Step 4: Commit**

```bash
git add src/pm_arb/db/repository.py tests/db/test_repository.py
git commit -m "feat: add summary queries to repository"
```

---

## Task 5: PaperExecutorAgent Persistence

**Priority**: P0 | **Complexity**: Medium | **Blocked By**: Task 2

**Files:**
- Modify: `src/pm_arb/agents/paper_executor.py`

**Step 1: Update PaperExecutorAgent with persistence and state recovery**

```python
# src/pm_arb/agents/paper_executor.py
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
```

**Step 2: Run existing tests to ensure no regressions**

Run: `pytest tests/agents/test_paper_executor.py -v`

Expected: Existing tests still PASS

**Step 3: Commit**

```bash
git add src/pm_arb/agents/paper_executor.py
git commit -m "feat: add database persistence and state recovery to PaperExecutorAgent"
```

---

## Task 6: PaperExecutorAgent Persistence Tests

**Priority**: P0 | **Complexity**: Small | **Blocked By**: Task 5

**Files:**
- Create: `tests/agents/test_paper_executor_persistence.py`

**Step 1: Write persistence tests**

```python
# tests/agents/test_paper_executor_persistence.py
"""Tests for paper executor persistence."""

from decimal import Decimal
from uuid import uuid4

import pytest

from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.db.repository import PaperTradeRepository


@pytest.mark.asyncio
async def test_paper_executor_persists_trade(test_db_pool, redis_url):
    """Test that paper executor writes trades to database."""
    repo = PaperTradeRepository(test_db_pool)
    agent = PaperExecutorAgent(redis_url, db_pool=test_db_pool)
    agent._repo = repo  # Set repo directly for test

    # Simulate a trade request
    request_id = f"req-{uuid4().hex[:8]}"
    agent._pending_requests[request_id] = {
        "id": request_id,
        "opportunity_id": f"opp-{uuid4().hex[:8]}",
        "opportunity_type": "oracle_lag",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10.00",
        "max_price": "0.52",
        "expected_edge": "0.05",
        "strategy": "oracle-sniper",
    }

    # Execute paper trade
    await agent._execute_paper_trade(request_id)

    # Verify it was persisted
    trades = await repo.get_trades_since_days(1)
    assert len(trades) >= 1

    trade = trades[0]
    assert trade["opportunity_type"] == "oracle_lag"
    assert trade["market_id"] == "polymarket:btc-100k"
    assert trade["side"] == "buy"
    assert trade["risk_approved"] is True


@pytest.mark.asyncio
async def test_paper_executor_persists_rejection(test_db_pool, redis_url):
    """Test that paper executor writes rejections to database."""
    repo = PaperTradeRepository(test_db_pool)
    agent = PaperExecutorAgent(redis_url, db_pool=test_db_pool)
    agent._repo = repo

    # Simulate a trade request
    request_id = f"req-{uuid4().hex[:8]}"
    agent._pending_requests[request_id] = {
        "id": request_id,
        "opportunity_id": f"opp-{uuid4().hex[:8]}",
        "opportunity_type": "oracle_lag",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10.00",
        "max_price": "0.52",
        "expected_edge": "0.05",
        "strategy": "oracle-sniper",
    }

    # Handle rejection
    await agent._handle_rejection(request_id, "position_limit_exceeded")

    # Verify rejection was persisted
    trades = await repo.get_trades_since_days(1)
    assert len(trades) >= 1

    trade = trades[0]
    assert trade["risk_approved"] is False
    assert trade["risk_rejection_reason"] == "position_limit_exceeded"


@pytest.mark.asyncio
async def test_paper_executor_state_recovery(test_db_pool, redis_url):
    """Test that paper executor recovers state from database."""
    repo = PaperTradeRepository(test_db_pool)

    # Insert a trade directly
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )

    # Create agent and recover state
    agent = PaperExecutorAgent(redis_url, db_pool=test_db_pool)
    agent._repo = repo
    await agent._recover_state()

    # Verify state was recovered
    assert len(agent._trades) == 1
    assert agent._trades[0].market_id == "polymarket:btc-100k"
```

**Step 2: Run tests**

Run: `pytest tests/agents/test_paper_executor_persistence.py -v`

Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/agents/test_paper_executor_persistence.py
git commit -m "test: add persistence tests for PaperExecutorAgent"
```

---

## Task 7: Pilot Orchestrator

**Priority**: P0 | **Complexity**: Medium | **Blocked By**: Task 5

**Files:**
- Create: `src/pm_arb/pilot.py`
- Create: `tests/test_pilot.py`

**Step 1: Write orchestrator tests**

```python
# tests/test_pilot.py
"""Tests for pilot orchestrator."""

import asyncio

import pytest

from pm_arb.pilot import PilotOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_starts_agents(redis_url, test_db_pool):
    """Test that orchestrator starts all agents."""
    orchestrator = PilotOrchestrator(
        redis_url=redis_url,
        db_pool=test_db_pool,
    )

    # Start in background
    task = asyncio.create_task(orchestrator.run())

    # Give agents time to start
    await asyncio.sleep(0.5)

    # Verify agents are running
    assert orchestrator.is_running
    assert len(orchestrator.agents) >= 5

    # Stop gracefully
    await orchestrator.stop()
    await task


@pytest.mark.asyncio
async def test_orchestrator_health_check(redis_url, test_db_pool):
    """Test that orchestrator reports health status."""
    orchestrator = PilotOrchestrator(
        redis_url=redis_url,
        db_pool=test_db_pool,
    )

    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.5)

    health = orchestrator.get_health()
    assert "agents" in health
    assert "uptime_seconds" in health

    await orchestrator.stop()
    await task
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pilot.py -v`

Expected: FAIL with "No module named 'pm_arb.pilot'"

**Step 3: Write the orchestrator**

```python
# src/pm_arb/pilot.py
"""Pilot Orchestrator - runs all agents with health monitoring."""

import asyncio
import signal
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent
from pm_arb.core.config import settings
from pm_arb.db import get_pool, init_db

logger = structlog.get_logger()


class PilotOrchestrator:
    """Orchestrates all agents with health monitoring and auto-restart."""

    def __init__(
        self,
        redis_url: str | None = None,
        db_pool: asyncpg.Pool | None = None,
    ) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._db_pool = db_pool
        self._agents: list[BaseAgent] = []
        self._agent_tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._stop_event = asyncio.Event()
        self._start_time: datetime | None = None
        self._restart_counts: dict[str, int] = {}
        self._last_heartbeats: dict[str, datetime] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def agents(self) -> list[BaseAgent]:
        return self._agents

    async def run(self) -> None:
        """Start all agents and monitor them."""
        self._running = True
        self._start_time = datetime.now(UTC)
        self._stop_event.clear()

        # Initialize database if pool not provided
        if self._db_pool is None:
            await init_db()
            self._db_pool = await get_pool()

        logger.info("pilot_starting")

        # Create agents in startup order
        self._agents = self._create_agents()

        # Start all agents
        for agent in self._agents:
            await self._start_agent(agent)

        logger.info("pilot_started", agent_count=len(self._agents))

        # Monitor loop
        try:
            while self._running and not self._stop_event.is_set():
                await self._health_check()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("pilot_cancelled")
        finally:
            await self._shutdown()

    def _create_agents(self) -> list[BaseAgent]:
        """Create all agents in startup order."""
        return [
            VenueWatcherAgent(self._redis_url, venue="polymarket"),
            OracleAgent(self._redis_url, source="binance"),
            OpportunityScannerAgent(self._redis_url),
            RiskGuardianAgent(self._redis_url),
            PaperExecutorAgent(self._redis_url, db_pool=self._db_pool),
            StrategyAgent(self._redis_url, strategy_name="oracle-sniper"),
            CapitalAllocatorAgent(self._redis_url),
        ]

    async def _start_agent(self, agent: BaseAgent) -> None:
        """Start a single agent with error handling and auto-restart."""

        async def run_with_restart() -> None:
            backoff = 1
            max_backoff = 60
            max_failures = 5
            failures = 0

            while self._running and failures < max_failures:
                try:
                    self._last_heartbeats[agent.name] = datetime.now(UTC)
                    await agent.run()
                    break  # Clean exit
                except Exception as e:
                    failures += 1
                    self._restart_counts[agent.name] = (
                        self._restart_counts.get(agent.name, 0) + 1
                    )
                    logger.error(
                        "agent_crashed",
                        agent=agent.name,
                        error=str(e),
                        failures=failures,
                        backoff=backoff,
                    )
                    if failures < max_failures:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                    else:
                        logger.error("agent_max_failures", agent=agent.name)

        task = asyncio.create_task(run_with_restart())
        self._agent_tasks[agent.name] = task
        logger.info("agent_started", agent=agent.name)

    async def _health_check(self) -> None:
        """Check agent health and log warnings for stale agents."""
        now = datetime.now(UTC)
        stale_threshold = 120  # 2 minutes

        for agent in self._agents:
            last_beat = self._last_heartbeats.get(agent.name)
            if last_beat and (now - last_beat).total_seconds() > stale_threshold:
                logger.warning(
                    "agent_stale",
                    agent=agent.name,
                    last_beat=last_beat.isoformat(),
                )

            # Update heartbeat if agent is running
            if agent.is_running:
                self._last_heartbeats[agent.name] = now

    def get_health(self) -> dict[str, Any]:
        """Get current health status."""
        now = datetime.now(UTC)
        uptime = (now - self._start_time).total_seconds() if self._start_time else 0

        return {
            "running": self._running,
            "uptime_seconds": uptime,
            "agents": {
                agent.name: {
                    "running": agent.is_running,
                    "restarts": self._restart_counts.get(agent.name, 0),
                    "last_heartbeat": self._last_heartbeats.get(agent.name, now).isoformat(),
                }
                for agent in self._agents
            },
        }

    async def stop(self) -> None:
        """Signal graceful shutdown."""
        logger.info("pilot_stopping")
        self._running = False
        self._stop_event.set()

        # Stop agents in reverse order
        for agent in reversed(self._agents):
            await agent.stop()

        # Cancel tasks
        for task in self._agent_tasks.values():
            task.cancel()

        # Wait for tasks to complete
        if self._agent_tasks:
            await asyncio.gather(*self._agent_tasks.values(), return_exceptions=True)

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("pilot_shutdown_complete")


async def main() -> None:
    """Entry point for running the pilot."""
    orchestrator = PilotOrchestrator()

    # Handle signals (cross-platform)
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(orchestrator.stop())
            )
    else:
        # Windows fallback - just run and rely on KeyboardInterrupt
        pass

    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4: Run tests**

Run: `pytest tests/test_pilot.py -v`

Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/pm_arb/pilot.py tests/test_pilot.py
git commit -m "feat: add pilot orchestrator with health monitoring and auto-restart"
```

---

## Task 8: CLI Scaffolding & Dependencies

**Priority**: P1 | **Complexity**: Small | **Blocked By**: None

**Files:**
- Modify: `pyproject.toml`
- Create: `src/pm_arb/cli.py` (skeleton)

**Step 1: Update pyproject.toml**

```toml
# In pyproject.toml, update dependencies list to add:
    "click>=8.1.0",
    "rich>=13.0.0",

# Add entry point section:
[project.scripts]
pm-arb = "pm_arb.cli:cli"
```

**Step 2: Create CLI skeleton**

```python
# src/pm_arb/cli.py
"""CLI for PM Arbitrage pilot."""

import click


@click.group()
def cli() -> None:
    """PM Arbitrage CLI."""
    pass


@cli.command()
def version() -> None:
    """Show version."""
    click.echo("pm-arbitrage 0.1.0")


if __name__ == "__main__":
    cli()
```

**Step 3: Install and verify**

Run: `pip install -e ".[dev]"`
Run: `pm-arb --help`

Expected: Shows available commands

**Step 4: Commit**

```bash
git add pyproject.toml src/pm_arb/cli.py
git commit -m "feat: add CLI scaffolding with click"
```

---

## Task 9: CLI Report Command

**Priority**: P1 | **Complexity**: Small | **Blocked By**: Task 4, Task 8

**Files:**
- Modify: `src/pm_arb/cli.py`

**Step 1: Add report command**

```python
# src/pm_arb/cli.py
"""CLI for PM Arbitrage pilot."""

import asyncio
from datetime import datetime

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from pm_arb.db import close_pool, get_pool, init_db
from pm_arb.db.repository import PaperTradeRepository

console = Console()


@click.group()
def cli() -> None:
    """PM Arbitrage CLI."""
    pass


@cli.command()
@click.option("--days", default=1, help="Number of days to include in report")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def report(days: int, as_json: bool) -> None:
    """Generate daily summary report."""
    asyncio.run(_report(days, as_json))


async def _report(days: int, as_json: bool) -> None:
    """Async report generation."""
    pool = None
    try:
        await init_db()
        pool = await get_pool()
        repo = PaperTradeRepository(pool)

        summary = await repo.get_daily_summary(days)

        if as_json:
            import json

            click.echo(json.dumps(summary, indent=2, default=str))
            return

        # Header
        console.print(
            Panel(
                f"[bold]PM Arbitrage - Daily Summary[/bold]\n"
                f"[dim]{datetime.now().strftime('%Y-%m-%d')} | Last {days} day(s)[/dim]",
                style="blue",
            )
        )

        # Trades summary
        trades_table = Table(title="TRADES", show_header=False, box=None)
        trades_table.add_column("Metric", style="dim")
        trades_table.add_column("Value", style="bold")
        trades_table.add_row("Total trades", str(summary["total_trades"]))
        trades_table.add_row("Open positions", str(summary["open_trades"]))
        trades_table.add_row("Closed", str(summary["closed_trades"]))
        console.print(trades_table)
        console.print()

        # P&L summary
        pnl = summary["realized_pnl"]
        pnl_color = "green" if pnl >= 0 else "red"
        win_rate = summary["win_rate"] * 100
        wins = summary["wins"]
        losses = summary["losses"]

        pnl_table = Table(title="P&L (Paper)", show_header=False, box=None)
        pnl_table.add_column("Metric", style="dim")
        pnl_table.add_column("Value")
        pnl_table.add_row("Realized P&L", f"[{pnl_color}]${pnl:+,.2f}[/{pnl_color}]")
        pnl_table.add_row("Win rate", f"{win_rate:.0f}% ({wins}/{wins + losses})")
        console.print(pnl_table)
        console.print()

        # By opportunity type
        if summary["by_opportunity_type"]:
            type_table = Table(title="BY OPPORTUNITY TYPE")
            type_table.add_column("Type")
            type_table.add_column("Trades", justify="right")
            type_table.add_column("P&L", justify="right")
            for row in summary["by_opportunity_type"]:
                pnl_val = row["pnl"]
                pnl_str = (
                    f"[green]${pnl_val:+,.2f}[/green]"
                    if pnl_val >= 0
                    else f"[red]${pnl_val:+,.2f}[/red]"
                )
                type_table.add_row(row["type"], str(row["trades"]), pnl_str)
            console.print(type_table)
            console.print()

        # Risk rejections
        if summary["risk_rejections"]:
            reject_table = Table(title="RISK EVENTS")
            reject_table.add_column("Reason")
            reject_table.add_column("Count", justify="right")
            for row in summary["risk_rejections"]:
                reject_table.add_row(row["reason"] or "unknown", str(row["count"]))
            console.print(reject_table)

    finally:
        if pool:
            await close_pool()


@cli.command()
def version() -> None:
    """Show version."""
    click.echo("pm-arbitrage 0.1.0")


if __name__ == "__main__":
    cli()
```

**Step 2: Test the command**

Run: `pm-arb report --days 1`
Run: `pm-arb report --json`

Expected: Report displays (may show zeros if no trades yet)

**Step 3: Commit**

```bash
git add src/pm_arb/cli.py
git commit -m "feat: add report command to CLI"
```

---

## Task 10: CLI Pilot Command

**Priority**: P1 | **Complexity**: Small | **Blocked By**: Task 7, Task 8

**Files:**
- Modify: `src/pm_arb/cli.py`

**Step 1: Add pilot command**

```python
# Add to src/pm_arb/cli.py

@cli.command()
def pilot() -> None:
    """Start the pilot orchestrator."""
    from pm_arb.pilot import main

    asyncio.run(main())
```

**Step 2: Test the command**

Run: `pm-arb pilot` (then Ctrl+C to stop)

Expected: Pilot starts, agents begin running, Ctrl+C stops gracefully

**Step 3: Commit**

```bash
git add src/pm_arb/cli.py
git commit -m "feat: add pilot command to CLI"
```

---

## Task 11: Pilot Monitor Dashboard Tab

**Priority**: P1 | **Complexity**: Medium | **Blocked By**: Task 4

**Files:**
- Modify: `src/pm_arb/dashboard/app.py`

**Step 1: Add imports and cached pool**

```python
# Add at top of src/pm_arb/dashboard/app.py
import asyncio
from datetime import datetime

# Add after imports
@st.cache_resource
def get_cached_db_pool():
    """Get cached database pool for dashboard."""
    from pm_arb.db import get_pool, init_db

    async def _get_pool():
        await init_db()
        return await get_pool()

    return asyncio.run(_get_pool())
```

**Step 2: Update navigation**

```python
# Update the page navigation in main()
page = st.sidebar.radio(
    "Select Page",
    ["Overview", "Pilot Monitor", "Strategies", "Trades", "Risk", "System", "How It Works"],
)

# Update page routing
if page == "Overview":
    render_overview()
elif page == "Pilot Monitor":
    render_pilot_monitor()
elif page == "Strategies":
    render_strategies()
elif page == "Trades":
    render_trades()
elif page == "Risk":
    render_risk()
elif page == "System":
    render_system()
elif page == "How It Works":
    render_how_it_works()
```

**Step 3: Add Pilot Monitor page**

```python
# Add to src/pm_arb/dashboard/app.py

def render_pilot_monitor() -> None:
    """Render pilot monitoring page with real-time metrics."""
    st.header("Pilot Monitor")

    # Connection status indicator
    col_status, col_refresh = st.columns([3, 1])
    with col_status:
        st.markdown("🟢 **Live** - Connected to database")
    with col_refresh:
        if st.button("Refresh"):
            st.rerun()

    # Get data
    try:
        summary = asyncio.run(_get_pilot_summary())
    except Exception as e:
        st.error(f"Database error: {e}")
        summary = _get_mock_pilot_summary()

    # Key metrics row
    col1, col2, col3 = st.columns(3)

    with col1:
        pnl = summary.get("realized_pnl", 0)
        st.metric(
            label="Cumulative P&L",
            value=f"${pnl:,.2f}",
        )

    with col2:
        st.metric(
            label="Trades Today",
            value=str(summary.get("total_trades", 0)),
        )

    with col3:
        win_rate = summary.get("win_rate", 0) * 100
        st.metric(
            label="Win Rate",
            value=f"{win_rate:.0f}%",
        )

    st.markdown("---")

    # Two columns: recent trades and breakdown
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Recent Trades")
        trades = summary.get("recent_trades", [])
        if trades:
            df = pd.DataFrame(trades[:20])
            if "created_at" in df.columns:
                df["time"] = pd.to_datetime(df["created_at"]).dt.strftime("%H:%M")
            else:
                df["time"] = "N/A"
            display_cols = ["time", "market_id", "side", "price", "expected_edge", "status"]
            available_cols = [c for c in display_cols if c in df.columns]
            if available_cols:
                st.dataframe(df[available_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No trades yet. Start the pilot to see results.")

    with col2:
        st.subheader("By Opportunity Type")
        by_type = summary.get("by_opportunity_type", [])
        if by_type:
            for row in by_type:
                pnl = row.get("pnl", 0)
                pnl_color = "green" if pnl >= 0 else "red"
                st.markdown(
                    f"**{row['type']}**  \n"
                    f"{row['trades']} trades · "
                    f":{pnl_color}[${pnl:+,.2f}]"
                )
        else:
            st.info("No data yet.")


async def _get_pilot_summary() -> dict:
    """Fetch summary from database."""
    from pm_arb.db.repository import PaperTradeRepository

    pool = get_cached_db_pool()
    repo = PaperTradeRepository(pool)

    summary = await repo.get_daily_summary(days=7)
    trades = await repo.get_trades_since_days(days=1)

    return {
        "realized_pnl": summary["realized_pnl"],
        "total_trades": summary["total_trades"],
        "win_rate": summary["win_rate"],
        "by_opportunity_type": summary["by_opportunity_type"],
        "recent_trades": trades,
    }


def _get_mock_pilot_summary() -> dict:
    """Mock data for when database isn't available."""
    return {
        "realized_pnl": 0,
        "total_trades": 0,
        "win_rate": 0,
        "by_opportunity_type": [],
        "recent_trades": [],
    }
```

**Step 4: Run dashboard**

Run: `streamlit run src/pm_arb/dashboard/app.py`

Expected: "Pilot Monitor" tab appears and displays metrics

**Step 5: Commit**

```bash
git add src/pm_arb/dashboard/app.py
git commit -m "feat: add Pilot Monitor tab to dashboard"
```

---

## Task 12: How It Works Dashboard Tab

**Priority**: P2 | **Complexity**: Small | **Blocked By**: None

**Files:**
- Modify: `src/pm_arb/dashboard/app.py`

**Step 1: Add How It Works page**

```python
# Add to src/pm_arb/dashboard/app.py

def render_how_it_works() -> None:
    """Render educational explainer panel."""
    st.header("How Arbitrage Works")

    st.markdown("""
    ### The Basic Idea

    Prediction markets price outcomes as probabilities. When the market price
    **lags behind reality**, we profit by trading before the market corrects.
    """)

    # Live example section
    st.subheader("Live Example")

    example_col1, example_col2 = st.columns(2)

    with example_col1:
        st.markdown("""
        **Polymarket**
        Market: "BTC above $97,000 at 4pm ET?"
        YES Price: **$0.52** (52% implied odds)
        """)

    with example_col2:
        st.markdown("""
        **Binance (Oracle)**
        BTC Price: **$97,842**
        (Already above threshold!)
        """)

    st.info("""
    **The Opportunity**
    BTC is ALREADY above $97k, but the market only prices YES at 52%.
    True probability: ~85%+

    **Edge = 85% - 52% = 33% mispricing**
    """)

    # The math
    st.subheader("The Math")

    st.markdown("""
    We buy YES at **$0.52**

    | Outcome | Payout | Profit/Loss |
    |---------|--------|-------------|
    | BTC stays above $97k | YES pays $1.00 | **+$0.48** per share (92% return) |
    | BTC drops below $97k | YES pays $0.00 | **-$0.52** per share |

    **Expected value** (at 85% true odds):
    `(0.85 x $0.48) + (0.15 x -$0.52)` = **+$0.33 per share**
    """)

    # Why it works
    st.subheader("Why This Works")

    st.code("""
Timeline:
─────────●────────────●────────────●──────────▶
      BTC moves    We trade    Market corrects
        (0ms)       (50ms)       (2-5 sec)
    """, language=None)

    st.markdown("""
    - **Binance** updates every millisecond
    - **Polymarket** updates every few seconds
    - In that gap, we see the future price before the prediction market catches up
    """)

    # Three types
    st.subheader("Three Types We Detect")

    type_col1, type_col2, type_col3 = st.columns(3)

    with type_col1:
        st.markdown("""
        **1. Oracle Lag**
        Real-world data moves before the market.

        *Example: BTC pumps on Binance, Polymarket BTC markets lag behind.*
        """)

    with type_col2:
        st.markdown("""
        **2. Mispricing**
        YES + NO don't sum to ~100%.

        *Example: YES = 45%, NO = 48%. Buy both, guaranteed profit.*
        """)

    with type_col3:
        st.markdown("""
        **3. Cross-Platform**
        Same event priced differently.

        *Example: Polymarket YES = 52%, Kalshi YES = 58%.*
        """)

    # Glossary
    with st.expander("Glossary"):
        st.markdown("""
        | Term | Definition |
        |------|------------|
        | **Edge** | The difference between market price and true probability |
        | **VWAP** | Volume-Weighted Average Price - what you'll actually pay accounting for order book depth |
        | **Slippage** | The difference between expected price and actual fill price |
        | **Oracle** | External data source (Binance, weather APIs, etc.) |
        | **Venue** | Prediction market platform (Polymarket, Kalshi) |
        """)
```

**Step 2: Run dashboard**

Run: `streamlit run src/pm_arb/dashboard/app.py`

Expected: "How It Works" tab appears with educational content

**Step 3: Commit**

```bash
git add src/pm_arb/dashboard/app.py
git commit -m "feat: add How It Works explainer tab to dashboard"
```

---

## Task 13: Integration Test - Full Flow

**Priority**: P1 | **Complexity**: Small | **Blocked By**: Task 7

**Files:**
- Create: `tests/integration/test_pilot_flow.py`

**Step 1: Write integration test**

```python
# tests/integration/test_pilot_flow.py
"""Integration test for full pilot flow."""

import asyncio

import pytest

from pm_arb.db import get_pool, init_db
from pm_arb.db.repository import PaperTradeRepository
from pm_arb.pilot import PilotOrchestrator


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_pilot_flow(redis_url):
    """Test that pilot runs and persists trades."""
    # Initialize database
    await init_db()
    pool = await get_pool()
    repo = PaperTradeRepository(pool)

    # Get initial trade count
    initial_summary = await repo.get_daily_summary(days=1)
    initial_trades = initial_summary["total_trades"]

    # Start orchestrator
    orchestrator = PilotOrchestrator(redis_url=redis_url, db_pool=pool)

    # Run for a short time
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(10)

    # Verify health
    health = orchestrator.get_health()
    assert health["running"]
    assert len(health["agents"]) >= 5

    # Stop gracefully
    await orchestrator.stop()
    await task

    # Verify no errors - summary should be retrievable
    final_summary = await repo.get_daily_summary(days=1)
    assert final_summary is not None

    await pool.close()
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_pilot_flow.py -v -m integration`

Expected: Test PASSES

**Step 3: Commit**

```bash
git add tests/integration/test_pilot_flow.py
git commit -m "test: add integration test for full pilot flow"
```

---

## Execution Summary

**Phase 1: Foundation** (Tasks 1-4) — Database layer
**Phase 2: Persistence** (Tasks 5-6) — Executor integration
**Phase 3: Orchestration** (Tasks 7, 13) — Pilot runner
**Phase 4: Interface** (Tasks 8-12) — CLI and dashboard

**Parallel opportunities:**
- Tasks 8 + 12 can run during Phase 2
- Tasks 9 + 11 can run in parallel after Task 4
- Tasks 10 + 13 can run in parallel after Task 7

**Usage after implementation:**

```bash
# Start infrastructure
docker-compose up -d

# Initialize database
python -c "import asyncio; from pm_arb.db import init_db; asyncio.run(init_db())"

# Start the pilot
pm-arb pilot

# In another terminal, start dashboard
streamlit run src/pm_arb/dashboard/app.py

# Generate reports
pm-arb report --days 1
pm-arb report --days 7 --json
```
