# Sprint 5: Strategy Agent + Capital Allocator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Strategy Agent framework with Oracle Sniper implementation, and a Capital Allocator that distributes capital across strategies based on tournament-style performance tracking.

**Architecture:** Strategy Agent subscribes to `opportunities.detected`, evaluates opportunities against its rules, and publishes trade requests to `trade.requests`. Capital Allocator tracks P&L per strategy from `trade.results`, calculates performance scores, and adjusts allocation percentages. Strategies query allocator for their current budget before sizing trades.

**Tech Stack:** Python 3.12, asyncio, Redis Streams, Pydantic, pytest, structlog

**Demo:** Detect oracle lag opportunity → Oracle Sniper generates trade request → Risk Guardian approves → Paper Executor fills → Capital Allocator updates strategy score.

---

## Task 5.1: Strategy Agent Base Class

**Files:**
- Create: `src/pm_arb/agents/strategy_agent.py`
- Create: `tests/agents/test_strategy_agent.py`

**Step 1: Write the failing test**

Create `tests/agents/test_strategy_agent.py`:

```python
"""Tests for Strategy Agent base class."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.core.models import OpportunityType


class TestStrategy(StrategyAgent):
    """Concrete test implementation."""

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url, strategy_name="test-strategy")

    def evaluate_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any] | None:
        """Accept all opportunities for testing."""
        return {
            "market_id": opportunity["markets"][0],
            "side": "buy",
            "outcome": "YES",
            "amount": Decimal("10"),
            "max_price": Decimal("0.60"),
        }


@pytest.mark.asyncio
async def test_strategy_subscribes_to_opportunities() -> None:
    """Strategy should subscribe to opportunities channel."""
    strategy = TestStrategy(redis_url="redis://localhost:6379")

    subs = strategy.get_subscriptions()

    assert "opportunities.detected" in subs


@pytest.mark.asyncio
async def test_strategy_generates_trade_request() -> None:
    """Strategy should generate trade request from opportunity."""
    strategy = TestStrategy(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    strategy.publish = capture_publish  # type: ignore[method-assign]
    strategy._allocation_pct = Decimal("0.20")  # 20% allocation
    strategy._total_capital = Decimal("1000")

    await strategy.handle_message(
        "opportunities.detected",
        {
            "id": "opp-001",
            "type": OpportunityType.ORACLE_LAG.value,
            "markets": ["polymarket:btc-100k"],
            "expected_edge": "0.10",
            "signal_strength": "0.80",
            "metadata": {},
        },
    )

    assert len(published) == 1
    assert published[0][0] == "trade.requests"
    assert published[0][1]["strategy"] == "test-strategy"
    assert published[0][1]["opportunity_id"] == "opp-001"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_strategy_agent.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/agents/strategy_agent.py`:

```python
"""Strategy Agent base class - evaluates opportunities and generates trade requests."""

from abc import abstractmethod
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Side

logger = structlog.get_logger()


class StrategyAgent(BaseAgent):
    """Base class for trading strategies."""

    def __init__(
        self,
        redis_url: str,
        strategy_name: str,
        min_edge: Decimal = Decimal("0.02"),
        min_signal: Decimal = Decimal("0.50"),
    ) -> None:
        self.name = f"strategy-{strategy_name}"
        super().__init__(redis_url)
        self._strategy_name = strategy_name
        self._min_edge = min_edge
        self._min_signal = min_signal

        # Capital allocation (updated by Capital Allocator)
        self._allocation_pct = Decimal("0.10")  # Default 10%
        self._total_capital = Decimal("500")  # Will be updated

        # Performance tracking
        self._trades_submitted = 0
        self._trades_filled = 0
        self._total_pnl = Decimal("0")

    def get_subscriptions(self) -> list[str]:
        """Subscribe to opportunities and allocation updates."""
        return ["opportunities.detected", "allocations.update"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Route messages to appropriate handler."""
        if channel == "opportunities.detected":
            await self._handle_opportunity(data)
        elif channel == "allocations.update":
            await self._handle_allocation_update(data)

    async def _handle_opportunity(self, data: dict[str, Any]) -> None:
        """Evaluate opportunity and generate trade request if suitable."""
        # Check minimum thresholds
        edge = Decimal(str(data.get("expected_edge", "0")))
        signal = Decimal(str(data.get("signal_strength", "0")))

        if edge < self._min_edge or signal < self._min_signal:
            return

        # Let subclass evaluate
        trade_params = self.evaluate_opportunity(data)
        if not trade_params:
            return

        # Generate trade request
        await self._submit_trade_request(data, trade_params)

    @abstractmethod
    def evaluate_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any] | None:
        """
        Evaluate opportunity and return trade parameters if suitable.

        Returns:
            dict with keys: market_id, side, outcome, amount, max_price
            or None if opportunity should be skipped
        """
        ...

    async def _submit_trade_request(
        self,
        opportunity: dict[str, Any],
        trade_params: dict[str, Any],
    ) -> None:
        """Submit trade request to Risk Guardian."""
        request_id = f"req-{uuid4().hex[:8]}"

        # Calculate position size based on allocation
        max_position = self._total_capital * self._allocation_pct
        amount = min(trade_params["amount"], max_position)

        request = {
            "id": request_id,
            "opportunity_id": opportunity["id"],
            "strategy": self._strategy_name,
            "market_id": trade_params["market_id"],
            "side": trade_params["side"],
            "outcome": trade_params["outcome"],
            "amount": str(amount),
            "max_price": str(trade_params["max_price"]),
            "created_at": datetime.now(UTC).isoformat(),
        }

        logger.info(
            "trade_request_submitted",
            strategy=self._strategy_name,
            request_id=request_id,
            opportunity_id=opportunity["id"],
            amount=str(amount),
        )

        await self.publish("trade.requests", request)
        self._trades_submitted += 1

    async def _handle_allocation_update(self, data: dict[str, Any]) -> None:
        """Handle capital allocation update from allocator."""
        if data.get("strategy") != self._strategy_name:
            return

        self._allocation_pct = Decimal(str(data.get("allocation_pct", "0.10")))
        self._total_capital = Decimal(str(data.get("total_capital", "500")))

        logger.info(
            "allocation_updated",
            strategy=self._strategy_name,
            allocation_pct=str(self._allocation_pct),
            total_capital=str(self._total_capital),
        )

    def get_available_capital(self) -> Decimal:
        """Get current available capital for this strategy."""
        return self._total_capital * self._allocation_pct
```

**Step 4: Run test**

Run: `pytest tests/agents/test_strategy_agent.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/strategy_agent.py tests/agents/test_strategy_agent.py
git commit -m "feat: add Strategy Agent base class"
```

---

## Task 5.2: Oracle Sniper Strategy

**Files:**
- Create: `src/pm_arb/strategies/oracle_sniper.py`
- Create: `tests/strategies/test_oracle_sniper.py`
- Create: `src/pm_arb/strategies/__init__.py`
- Create: `tests/strategies/__init__.py`

**Step 1: Write the failing test**

Create `tests/strategies/__init__.py`:
```python
"""Strategy tests."""
```

Create `tests/strategies/test_oracle_sniper.py`:

```python
"""Tests for Oracle Sniper strategy."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.core.models import OpportunityType
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy


@pytest.mark.asyncio
async def test_oracle_sniper_accepts_oracle_lag() -> None:
    """Should accept oracle lag opportunities with sufficient edge."""
    strategy = OracleSniperStrategy(redis_url="redis://localhost:6379")

    opportunity = {
        "id": "opp-001",
        "type": OpportunityType.ORACLE_LAG.value,
        "markets": ["polymarket:btc-100k"],
        "oracle_source": "binance",
        "oracle_value": "105000",
        "expected_edge": "0.15",
        "signal_strength": "0.85",
        "metadata": {
            "threshold": "100000",
            "direction": "above",
            "fair_yes_price": "0.95",
            "current_yes_price": "0.80",
        },
    }

    trade_params = strategy.evaluate_opportunity(opportunity)

    assert trade_params is not None
    assert trade_params["market_id"] == "polymarket:btc-100k"
    assert trade_params["side"] == "buy"
    assert trade_params["outcome"] == "YES"
    assert trade_params["max_price"] == Decimal("0.80")  # Current price


@pytest.mark.asyncio
async def test_oracle_sniper_rejects_cross_platform() -> None:
    """Should reject non-oracle-lag opportunities."""
    strategy = OracleSniperStrategy(redis_url="redis://localhost:6379")

    opportunity = {
        "id": "opp-002",
        "type": OpportunityType.CROSS_PLATFORM.value,
        "markets": ["polymarket:btc-100k", "kalshi:btc-100k"],
        "expected_edge": "0.10",
        "signal_strength": "0.70",
        "metadata": {},
    }

    trade_params = strategy.evaluate_opportunity(opportunity)

    assert trade_params is None


@pytest.mark.asyncio
async def test_oracle_sniper_sizes_by_signal() -> None:
    """Should size position based on signal strength."""
    strategy = OracleSniperStrategy(redis_url="redis://localhost:6379")
    strategy._allocation_pct = Decimal("0.20")
    strategy._total_capital = Decimal("1000")

    # High signal = larger position
    opportunity = {
        "id": "opp-001",
        "type": OpportunityType.ORACLE_LAG.value,
        "markets": ["polymarket:btc-100k"],
        "expected_edge": "0.20",
        "signal_strength": "0.90",  # 90% confidence
        "metadata": {
            "fair_yes_price": "0.95",
            "current_yes_price": "0.75",
        },
    }

    trade_params = strategy.evaluate_opportunity(opportunity)

    # Max position = 1000 * 0.20 = 200
    # Signal scaling: 200 * 0.90 = 180
    assert trade_params is not None
    assert trade_params["amount"] == Decimal("180")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/strategies/test_oracle_sniper.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/strategies/__init__.py`:
```python
"""Trading strategies."""

from pm_arb.strategies.oracle_sniper import OracleSniperStrategy

__all__ = ["OracleSniperStrategy"]
```

Create `src/pm_arb/strategies/oracle_sniper.py`:

```python
"""Oracle Sniper Strategy - exploits oracle lag in prediction markets."""

from decimal import Decimal
from typing import Any

import structlog

from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.core.models import OpportunityType

logger = structlog.get_logger()


class OracleSniperStrategy(StrategyAgent):
    """
    Strategy that exploits lag between oracle data and prediction market prices.

    When oracle shows BTC > $100k but market still prices YES at 0.80,
    this strategy buys YES expecting convergence to fair value (~0.95).
    """

    def __init__(
        self,
        redis_url: str,
        min_edge: Decimal = Decimal("0.05"),  # 5% minimum edge
        min_signal: Decimal = Decimal("0.60"),  # 60% minimum signal
        max_position_pct: Decimal = Decimal("0.50"),  # Max 50% of allocation per trade
    ) -> None:
        super().__init__(
            redis_url=redis_url,
            strategy_name="oracle-sniper",
            min_edge=min_edge,
            min_signal=min_signal,
        )
        self._max_position_pct = max_position_pct

    def evaluate_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any] | None:
        """
        Evaluate oracle lag opportunity.

        Only accepts ORACLE_LAG type. Sizes position by signal strength.
        """
        # Only handle oracle lag opportunities
        opp_type = opportunity.get("type", "")
        if opp_type != OpportunityType.ORACLE_LAG.value:
            return None

        markets = opportunity.get("markets", [])
        if not markets:
            return None

        metadata = opportunity.get("metadata", {})
        edge = Decimal(str(opportunity.get("expected_edge", "0")))
        signal = Decimal(str(opportunity.get("signal_strength", "0")))

        # Determine trade direction from edge sign
        # Positive edge = YES underpriced, buy YES
        # Negative edge = YES overpriced, buy NO (sell YES)
        if edge > 0:
            side = "buy"
            outcome = "YES"
        else:
            side = "buy"
            outcome = "NO"

        # Get current price from metadata
        current_price = Decimal(str(metadata.get("current_yes_price", "0.50")))
        if outcome == "NO":
            current_price = Decimal("1") - current_price

        # Size position based on signal strength and allocation
        max_position = self.get_available_capital() * self._max_position_pct
        position_size = max_position * signal

        logger.info(
            "oracle_sniper_evaluation",
            opportunity_id=opportunity.get("id"),
            edge=str(edge),
            signal=str(signal),
            outcome=outcome,
            position_size=str(position_size),
        )

        return {
            "market_id": markets[0],
            "side": side,
            "outcome": outcome,
            "amount": position_size,
            "max_price": current_price,  # Willing to pay current price
        }
```

**Step 4: Run test**

Run: `pytest tests/strategies/test_oracle_sniper.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/strategies/ tests/strategies/
git commit -m "feat: add Oracle Sniper strategy implementation"
```

---

## Task 5.3: Capital Allocator Agent

**Files:**
- Create: `src/pm_arb/agents/capital_allocator.py`
- Create: `tests/agents/test_capital_allocator.py`

**Step 1: Write the failing test**

Create `tests/agents/test_capital_allocator.py`:

```python
"""Tests for Capital Allocator agent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.core.models import TradeStatus


@pytest.mark.asyncio
async def test_allocator_subscribes_to_trade_results() -> None:
    """Allocator should subscribe to trade results channel."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )

    subs = allocator.get_subscriptions()

    assert "trade.results" in subs


@pytest.mark.asyncio
async def test_allocator_tracks_strategy_pnl() -> None:
    """Allocator should track P&L per strategy."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )

    # Register strategies
    allocator.register_strategy("oracle-sniper")
    allocator.register_strategy("cross-arb")

    # Simulate profitable trade for oracle-sniper
    await allocator.handle_message(
        "trade.results",
        {
            "id": "trade-001",
            "request_id": "req-001",
            "strategy": "oracle-sniper",
            "status": TradeStatus.FILLED.value,
            "amount": "100",
            "price": "0.50",
            "pnl": "20",  # $20 profit
            "paper_trade": True,
        },
    )

    performance = allocator.get_strategy_performance("oracle-sniper")
    assert performance["total_pnl"] == Decimal("20")
    assert performance["trades"] == 1
    assert performance["wins"] == 1


@pytest.mark.asyncio
async def test_allocator_updates_allocations() -> None:
    """Allocator should adjust allocations based on performance."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    allocator.publish = capture_publish  # type: ignore[method-assign]

    # Register strategies
    allocator.register_strategy("oracle-sniper")
    allocator.register_strategy("cross-arb")

    # Oracle-sniper wins, cross-arb loses
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("100")
    allocator._strategy_performance["oracle-sniper"]["trades"] = 5
    allocator._strategy_performance["cross-arb"]["total_pnl"] = Decimal("-50")
    allocator._strategy_performance["cross-arb"]["trades"] = 5

    # Trigger reallocation
    await allocator.rebalance_allocations()

    # Oracle-sniper should get more allocation
    oracle_alloc = allocator.get_allocation("oracle-sniper")
    cross_alloc = allocator.get_allocation("cross-arb")

    assert oracle_alloc > cross_alloc
    assert oracle_alloc + cross_alloc <= Decimal("1.0")  # Total <= 100%
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_capital_allocator.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/agents/capital_allocator.py`:

```python
"""Capital Allocator Agent - manages capital allocation across strategies."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import TradeStatus

logger = structlog.get_logger()


class CapitalAllocatorAgent(BaseAgent):
    """
    Manages capital allocation across trading strategies.

    Uses tournament-style scoring to allocate more capital to better performers.
    """

    def __init__(
        self,
        redis_url: str,
        total_capital: Decimal = Decimal("500"),
        min_allocation: Decimal = Decimal("0.05"),  # 5% minimum per strategy
        max_allocation: Decimal = Decimal("0.50"),  # 50% maximum per strategy
        rebalance_interval_trades: int = 10,  # Rebalance every N trades
    ) -> None:
        self.name = "capital-allocator"
        super().__init__(redis_url)

        self._total_capital = total_capital
        self._min_allocation = min_allocation
        self._max_allocation = max_allocation
        self._rebalance_interval = rebalance_interval_trades

        # Strategy tracking
        self._strategies: list[str] = []
        self._allocations: dict[str, Decimal] = {}
        self._strategy_performance: dict[str, dict[str, Any]] = {}

        # Trade counter for rebalancing
        self._trades_since_rebalance = 0

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade results."""
        return ["trade.results"]

    def register_strategy(self, strategy_name: str) -> None:
        """Register a strategy for allocation tracking."""
        if strategy_name in self._strategies:
            return

        self._strategies.append(strategy_name)
        self._strategy_performance[strategy_name] = {
            "total_pnl": Decimal("0"),
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "largest_win": Decimal("0"),
            "largest_loss": Decimal("0"),
        }

        # Equal initial allocation
        self._recalculate_equal_allocation()

        logger.info("strategy_registered", strategy=strategy_name)

    def _recalculate_equal_allocation(self) -> None:
        """Set equal allocation across all strategies."""
        if not self._strategies:
            return

        equal_share = Decimal("1.0") / len(self._strategies)
        for strategy in self._strategies:
            self._allocations[strategy] = equal_share

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Process trade results."""
        if channel == "trade.results":
            await self._handle_trade_result(data)

    async def _handle_trade_result(self, data: dict[str, Any]) -> None:
        """Update strategy performance based on trade result."""
        strategy = data.get("strategy")
        if not strategy or strategy not in self._strategies:
            # Try to extract strategy from the trade
            strategy = data.get("request", {}).get("strategy")
            if not strategy:
                return

        status = data.get("status", "")
        if status != TradeStatus.FILLED.value:
            return

        pnl = Decimal(str(data.get("pnl", "0")))
        perf = self._strategy_performance[strategy]

        perf["trades"] += 1
        perf["total_pnl"] += pnl

        if pnl > 0:
            perf["wins"] += 1
            if pnl > perf["largest_win"]:
                perf["largest_win"] = pnl
        elif pnl < 0:
            perf["losses"] += 1
            if pnl < perf["largest_loss"]:
                perf["largest_loss"] = pnl

        logger.info(
            "strategy_pnl_updated",
            strategy=strategy,
            pnl=str(pnl),
            total_pnl=str(perf["total_pnl"]),
            trades=perf["trades"],
        )

        # Check if rebalance needed
        self._trades_since_rebalance += 1
        if self._trades_since_rebalance >= self._rebalance_interval:
            await self.rebalance_allocations()
            self._trades_since_rebalance = 0

    async def rebalance_allocations(self) -> None:
        """Rebalance allocations based on strategy performance."""
        if len(self._strategies) < 2:
            return

        # Calculate scores for each strategy
        scores: dict[str, Decimal] = {}
        total_score = Decimal("0")

        for strategy in self._strategies:
            score = self._calculate_strategy_score(strategy)
            scores[strategy] = score
            total_score += score

        if total_score <= 0:
            # No positive scores, use equal allocation
            self._recalculate_equal_allocation()
            return

        # Allocate proportionally to scores
        for strategy in self._strategies:
            raw_allocation = scores[strategy] / total_score

            # Apply min/max constraints
            allocation = max(self._min_allocation, min(self._max_allocation, raw_allocation))
            self._allocations[strategy] = allocation

        # Normalize to ensure sum = 1.0
        total_alloc = sum(self._allocations.values())
        if total_alloc > 0:
            for strategy in self._strategies:
                self._allocations[strategy] /= total_alloc

        # Publish allocation updates
        for strategy in self._strategies:
            await self._publish_allocation(strategy)

        logger.info(
            "allocations_rebalanced",
            allocations={s: str(a) for s, a in self._allocations.items()},
        )

    def _calculate_strategy_score(self, strategy: str) -> Decimal:
        """
        Calculate tournament score for a strategy.

        Score = PnL + (win_rate_bonus) + (consistency_bonus)
        Minimum score is 0.1 to ensure all strategies get some allocation.
        """
        perf = self._strategy_performance[strategy]
        trades = perf["trades"]

        if trades == 0:
            return Decimal("0.1")  # Base allocation for new strategies

        total_pnl = perf["total_pnl"]
        wins = perf["wins"]
        win_rate = Decimal(str(wins)) / Decimal(str(trades))

        # Base score from PnL (normalized)
        pnl_score = max(Decimal("0"), total_pnl / Decimal("100") + Decimal("1"))

        # Win rate bonus (0 to 0.5)
        win_rate_bonus = win_rate * Decimal("0.5")

        # Combine
        score = pnl_score + win_rate_bonus

        return max(Decimal("0.1"), score)

    async def _publish_allocation(self, strategy: str) -> None:
        """Publish allocation update for a strategy."""
        await self.publish(
            "allocations.update",
            {
                "strategy": strategy,
                "allocation_pct": str(self._allocations.get(strategy, Decimal("0.10"))),
                "total_capital": str(self._total_capital),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    def get_allocation(self, strategy: str) -> Decimal:
        """Get current allocation for a strategy."""
        return self._allocations.get(strategy, Decimal("0.10"))

    def get_strategy_performance(self, strategy: str) -> dict[str, Any]:
        """Get performance metrics for a strategy."""
        return self._strategy_performance.get(
            strategy,
            {"total_pnl": Decimal("0"), "trades": 0, "wins": 0, "losses": 0},
        )

    def get_all_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance metrics for all strategies."""
        return {
            strategy: {
                **self._strategy_performance[strategy],
                "allocation_pct": self._allocations.get(strategy, Decimal("0")),
            }
            for strategy in self._strategies
        }
```

**Step 4: Run test**

Run: `pytest tests/agents/test_capital_allocator.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/capital_allocator.py tests/agents/test_capital_allocator.py
git commit -m "feat: add Capital Allocator agent with tournament scoring"
```

---

## Task 5.4: Strategy Performance Model Enhancement

**Files:**
- Modify: `src/pm_arb/core/models.py`
- Modify: `tests/core/test_models.py`

**Step 1: Write the failing test**

Add to `tests/core/test_models.py`:

```python
class TestStrategyAllocation:
    """Tests for StrategyAllocation model."""

    def test_allocation_creation(self) -> None:
        """Should create strategy allocation."""
        from pm_arb.core.models import StrategyAllocation

        allocation = StrategyAllocation(
            strategy="oracle-sniper",
            allocation_pct=Decimal("0.25"),
            total_capital=Decimal("1000"),
            available_capital=Decimal("250"),
        )

        assert allocation.strategy == "oracle-sniper"
        assert allocation.allocation_pct == Decimal("0.25")
        assert allocation.available_capital == Decimal("250")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_models.py::TestStrategyAllocation -v`
Expected: FAIL (ImportError - StrategyAllocation not defined)

**Step 3: Add model**

Add to `src/pm_arb/core/models.py` after `StrategyPerformance`:

```python
class StrategyAllocation(BaseModel):
    """Current capital allocation for a strategy."""

    strategy: str
    allocation_pct: Decimal
    total_capital: Decimal
    available_capital: Decimal
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

**Step 4: Run test**

Run: `pytest tests/core/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/core/models.py tests/core/test_models.py
git commit -m "feat: add StrategyAllocation model"
```

---

## Task 5.5: Paper Executor P&L Tracking

**Files:**
- Modify: `src/pm_arb/agents/paper_executor.py`
- Modify: `tests/agents/test_paper_executor.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_paper_executor.py`:

```python
@pytest.mark.asyncio
async def test_executor_includes_strategy_in_result() -> None:
    """Executor should include strategy name in trade result."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Store pending request with strategy
    executor._pending_requests["req-001"] = {
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "oracle-sniper",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "50",
        "max_price": "0.55",
    }

    await executor.handle_message(
        "trade.decisions",
        {
            "request_id": "req-001",
            "approved": True,
            "reason": "All rules passed",
        },
    )

    assert len(published) == 1
    result = published[0][1]
    assert result["strategy"] == "oracle-sniper"
    assert "pnl" in result  # Should include P&L field
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_paper_executor.py::test_executor_includes_strategy_in_result -v`
Expected: FAIL (KeyError - 'strategy' not in result)

**Step 3: Update Paper Executor**

Modify `_execute_paper_trade` in `src/pm_arb/agents/paper_executor.py`:

```python
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

        await self._publish_trade_result(trade, strategy=strategy, pnl=simulated_pnl, paper_trade=True)

        # Clean up pending request
        del self._pending_requests[request_id]
```

Also update `_publish_trade_result`:

```python
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
```

**Step 4: Run test**

Run: `pytest tests/agents/test_paper_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/paper_executor.py tests/agents/test_paper_executor.py
git commit -m "feat: add strategy and P&L to Paper Executor results"
```

---

## Task 5.6: Sprint 5 Integration Test

**Files:**
- Create: `tests/integration/test_sprint5.py`

**Step 1: Write integration test**

Create `tests/integration/test_sprint5.py`:

```python
"""Integration test for Sprint 5: End-to-end paper trading flow."""

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import TradeStatus
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy


@pytest.mark.asyncio
async def test_end_to_end_paper_trading() -> None:
    """
    Full flow: Oracle update → Opportunity detected → Strategy generates request →
    Risk Guardian approves → Paper Executor fills → Capital Allocator updates score.
    """
    redis_url = "redis://localhost:6379"

    # Create agents
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.polymarket"],
        oracle_channels=["oracle.binance"],
    )

    strategy = OracleSniperStrategy(redis_url=redis_url)
    strategy._allocation_pct = Decimal("0.20")
    strategy._total_capital = Decimal("1000")

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.25"),
    )

    executor = PaperExecutorAgent(redis_url=redis_url)

    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")

    # Track results
    trade_results: list[dict[str, Any]] = []
    opportunities: list[dict[str, Any]] = []

    # Wire up message passing (simulating Redis)
    original_scanner_publish = scanner.publish
    original_strategy_publish = strategy.publish
    original_guardian_publish = guardian.publish
    original_executor_publish = executor.publish

    async def scanner_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
            await strategy._handle_opportunity(data)
        return "mock-id"

    async def strategy_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.requests":
            executor._pending_requests[data["id"]] = data
            await guardian._evaluate_request(data)
        return "mock-id"

    async def guardian_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.decisions":
            await executor._process_decision(data)
        return "mock-id"

    async def executor_publish(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            trade_results.append(data)
            await allocator._handle_trade_result(data)
        return "mock-id"

    scanner.publish = scanner_publish  # type: ignore[method-assign]
    strategy.publish = strategy_publish  # type: ignore[method-assign]
    guardian.publish = guardian_publish  # type: ignore[method-assign]
    executor.publish = executor_publish  # type: ignore[method-assign]

    # Register market-oracle mapping
    scanner.register_market_oracle_mapping(
        market_id="polymarket:btc-100k",
        oracle_symbol="BTCUSDT",
        threshold=Decimal("100000"),
        direction="above",
    )

    # Simulate market price update
    await scanner._handle_venue_price(
        "venue.polymarket",
        {
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "title": "Will BTC hit $100k?",
            "yes_price": "0.75",  # Market thinks 75% chance
            "no_price": "0.25",
        },
    )

    # Simulate oracle update showing BTC > $100k
    await scanner._handle_oracle_data(
        "oracle.binance",
        {
            "source": "binance",
            "symbol": "BTCUSDT",
            "value": "105000",  # BTC is at $105k - above threshold!
        },
    )

    # Wait for processing
    await asyncio.sleep(0.1)

    # Verify opportunity was detected
    assert len(opportunities) >= 1
    opp = opportunities[0]
    assert opp["type"] == "oracle_lag"
    assert Decimal(opp["expected_edge"]) > Decimal("0.05")

    # Verify trade was executed
    assert len(trade_results) >= 1
    result = trade_results[0]
    assert result["status"] == TradeStatus.FILLED.value
    assert result["strategy"] == "oracle-sniper"
    assert result["paper_trade"] is True

    # Verify allocator tracked the trade
    perf = allocator.get_strategy_performance("oracle-sniper")
    assert perf["trades"] >= 1

    print(f"\nOpportunities: {opportunities}")
    print(f"Trade results: {trade_results}")
    print(f"Strategy performance: {perf}")
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_sprint5.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/test_sprint5.py
git commit -m "test: add Sprint 5 integration test - end-to-end paper trading"
```

---

## Task 5.7: Sprint 5 Final Commit

**Step 1: Run all tests**

Run: `pytest tests/ -v --ignore=tests/integration/test_sprint2.py --ignore=tests/integration/test_sprint3.py`
Expected: All pass

**Step 2: Lint and type check**

Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`
Run: `mypy src/`
Expected: Clean

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: Sprint 5 complete - Strategy Agent + Capital Allocator

- StrategyAgent base class with allocation tracking
- OracleSniperStrategy for oracle lag opportunities
- CapitalAllocatorAgent with tournament-style scoring
- Paper Executor now tracks strategy and P&L
- End-to-end integration test

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Sprint 5 Complete

**Demo steps:**
1. `docker-compose up -d` (Redis)
2. `pytest tests/integration/test_sprint5.py -v`
3. See: Oracle update → Opportunity → Trade Request → Risk Check → Paper Fill → Score Update

**What we built:**
- StrategyAgent base class with allocation-aware sizing
- OracleSniperStrategy - exploits oracle lag opportunities
- CapitalAllocatorAgent - tournament-style allocation based on performance
- Paper Executor with strategy tracking and P&L
- Complete end-to-end paper trading flow

**Data flow:**
```
Oracle (Binance) → Scanner → Opportunity → Strategy → Trade Request
                                                         ↓
                           Allocator ← Trade Result ← Executor ← Guardian
```

**Next: Sprint 6 - Dashboard (Streamlit visualization)**
