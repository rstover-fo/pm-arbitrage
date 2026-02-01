# Sprint 4: Risk Guardian + Paper Executor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Risk Guardian agent that evaluates trade requests against configurable rules, and a Paper Executor that logs approved trades without real execution.

**Architecture:** Risk Guardian subscribes to `trade.requests`, evaluates each against rules (position limits, drawdown, daily loss), publishes decisions to `trade.decisions`. Paper Executor subscribes to approved decisions and logs simulated trades to `trade.results`. Both agents maintain state in Redis for fast checks.

**Tech Stack:** Python 3.12, asyncio, Redis Streams, Pydantic, pytest, structlog

**Demo:** Send a trade request, see Risk Guardian evaluate it, Paper Executor log the simulated fill.

---

## Task 4.1: Risk Guardian Agent Skeleton

**Files:**
- Create: `src/pm_arb/agents/risk_guardian.py`
- Create: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Create `tests/agents/test_risk_guardian.py`:

```python
"""Tests for Risk Guardian agent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import Side, TradeRequest


@pytest.mark.asyncio
async def test_guardian_subscribes_to_trade_requests() -> None:
    """Guardian should subscribe to trade request channel."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
    )

    subs = guardian.get_subscriptions()

    assert "trade.requests" in subs
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/agents/risk_guardian.py`:

```python
"""Risk Guardian Agent - evaluates trade requests against risk rules."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import RiskDecision, Side, TradeRequest, TradeStatus

logger = structlog.get_logger()


class RiskGuardianAgent(BaseAgent):
    """Evaluates trade requests and enforces risk limits."""

    def __init__(
        self,
        redis_url: str,
        initial_bankroll: Decimal = Decimal("500"),
        position_limit_pct: Decimal = Decimal("0.10"),  # 10% per position
        platform_limit_pct: Decimal = Decimal("0.50"),  # 50% per platform
        daily_loss_limit_pct: Decimal = Decimal("0.10"),  # 10% daily loss
        drawdown_limit_pct: Decimal = Decimal("0.20"),  # 20% from peak
    ) -> None:
        self.name = "risk-guardian"
        super().__init__(redis_url)

        # Configuration
        self._initial_bankroll = initial_bankroll
        self._position_limit_pct = position_limit_pct
        self._platform_limit_pct = platform_limit_pct
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._drawdown_limit_pct = drawdown_limit_pct

        # State tracking
        self._high_water_mark = initial_bankroll
        self._current_value = initial_bankroll
        self._daily_pnl = Decimal("0")
        self._daily_reset_date = datetime.now(UTC).date()
        self._positions: dict[str, Decimal] = {}  # market_id -> exposure
        self._platform_exposure: dict[str, Decimal] = {}  # venue -> exposure
        self._halted = False

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade requests."""
        return ["trade.requests"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Evaluate trade request against risk rules."""
        if channel == "trade.requests":
            await self._evaluate_request(data)

    async def _evaluate_request(self, data: dict[str, Any]) -> None:
        """Evaluate a trade request against all rules."""
        request = self._parse_request(data)
        if not request:
            return

        # Check each rule
        decision = await self._check_rules(request)

        # Publish decision
        await self._publish_decision(decision)

        # Update state if approved
        if decision.approved:
            await self._update_exposure(request)

    def _parse_request(self, data: dict[str, Any]) -> TradeRequest | None:
        """Parse trade request from message data."""
        try:
            return TradeRequest(
                id=data.get("id", f"req-{uuid4().hex[:8]}"),
                opportunity_id=data.get("opportunity_id", ""),
                strategy=data.get("strategy", "unknown"),
                market_id=data.get("market_id", ""),
                side=Side(data.get("side", "buy")),
                outcome=data.get("outcome", "YES"),
                amount=Decimal(str(data.get("amount", "0"))),
                max_price=Decimal(str(data.get("max_price", "1"))),
            )
        except Exception as e:
            logger.error("invalid_trade_request", error=str(e), data=data)
            return None

    async def _check_rules(self, request: TradeRequest) -> RiskDecision:
        """Check request against all risk rules."""
        # Placeholder - rules implemented in subsequent tasks
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="All rules passed",
        )

    async def _publish_decision(self, decision: RiskDecision) -> None:
        """Publish risk decision."""
        logger.info(
            "risk_decision",
            request_id=decision.request_id,
            approved=decision.approved,
            reason=decision.reason,
            rule=decision.rule_triggered,
        )

        await self.publish(
            "trade.decisions",
            {
                "request_id": decision.request_id,
                "approved": decision.approved,
                "reason": decision.reason,
                "rule_triggered": decision.rule_triggered,
                "decided_at": decision.decided_at.isoformat(),
            },
        )

    async def _update_exposure(self, request: TradeRequest) -> None:
        """Update exposure tracking after approved trade."""
        # Update position exposure
        current = self._positions.get(request.market_id, Decimal("0"))
        self._positions[request.market_id] = current + request.amount

        # Update platform exposure
        venue = request.market_id.split(":")[0] if ":" in request.market_id else "unknown"
        platform_current = self._platform_exposure.get(venue, Decimal("0"))
        self._platform_exposure[venue] = platform_current + request.amount
```

**Step 4: Run test**

Run: `pytest tests/agents/test_risk_guardian.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add Risk Guardian agent skeleton"
```

---

## Task 4.2: Position Limit Rule

**Files:**
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_risk_guardian.py`:

```python
@pytest.mark.asyncio
async def test_rejects_trade_exceeding_position_limit() -> None:
    """Should reject trade that exceeds position limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.10"),  # 10% = $100 max per position
    )

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Request $150 trade - exceeds 10% limit
    await guardian._evaluate_request({
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "test-strategy",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "150",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][0] == "trade.decisions"
    assert decisions[0][1]["approved"] is False
    assert decisions[0][1]["rule_triggered"] == "position_limit"


@pytest.mark.asyncio
async def test_approves_trade_within_position_limit() -> None:
    """Should approve trade within position limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.10"),  # 10% = $100 max per position
    )

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Request $80 trade - within 10% limit
    await guardian._evaluate_request({
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "test-strategy",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "80",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_trade_exceeding_position_limit -v`
Expected: FAIL (test expects rejection but gets approval)

**Step 3: Update implementation**

Update `_check_rules` in `src/pm_arb/agents/risk_guardian.py`:

```python
    async def _check_rules(self, request: TradeRequest) -> RiskDecision:
        """Check request against all risk rules."""
        # Rule 1: System halted
        if self._halted:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason="System is halted",
                rule_triggered="system_halt",
            )

        # Rule 2: Position limit
        position_limit = self._initial_bankroll * self._position_limit_pct
        current_position = self._positions.get(request.market_id, Decimal("0"))
        new_position = current_position + request.amount

        if new_position > position_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Position would exceed limit: ${new_position} > ${position_limit}",
                rule_triggered="position_limit",
            )

        # All rules passed
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="All rules passed",
        )
```

**Step 4: Run test**

Run: `pytest tests/agents/test_risk_guardian.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add position limit rule to Risk Guardian"
```

---

## Task 4.3: Platform Limit Rule

**Files:**
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_risk_guardian.py`:

```python
@pytest.mark.asyncio
async def test_rejects_trade_exceeding_platform_limit() -> None:
    """Should reject trade that exceeds platform exposure limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.50"),  # High position limit
        platform_limit_pct=Decimal("0.30"),  # 30% = $300 max per platform
    )

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # First trade: $200 to polymarket (within limit)
    await guardian._evaluate_request({
        "id": "req-001",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "200",
        "max_price": "0.50",
    })

    # Second trade: $150 more to polymarket (would exceed $300 limit)
    await guardian._evaluate_request({
        "id": "req-002",
        "market_id": "polymarket:eth-5k",
        "side": "buy",
        "outcome": "YES",
        "amount": "150",
        "max_price": "0.50",
    })

    assert len(decisions) == 2
    assert decisions[0][1]["approved"] is True
    assert decisions[1][1]["approved"] is False
    assert decisions[1][1]["rule_triggered"] == "platform_limit"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_trade_exceeding_platform_limit -v`
Expected: FAIL

**Step 3: Update implementation**

Add platform limit check to `_check_rules`:

```python
    async def _check_rules(self, request: TradeRequest) -> RiskDecision:
        """Check request against all risk rules."""
        # Rule 1: System halted
        if self._halted:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason="System is halted",
                rule_triggered="system_halt",
            )

        # Rule 2: Position limit
        position_limit = self._initial_bankroll * self._position_limit_pct
        current_position = self._positions.get(request.market_id, Decimal("0"))
        new_position = current_position + request.amount

        if new_position > position_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Position would exceed limit: ${new_position} > ${position_limit}",
                rule_triggered="position_limit",
            )

        # Rule 3: Platform limit
        platform_limit = self._initial_bankroll * self._platform_limit_pct
        venue = request.market_id.split(":")[0] if ":" in request.market_id else "unknown"
        current_platform = self._platform_exposure.get(venue, Decimal("0"))
        new_platform = current_platform + request.amount

        if new_platform > platform_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Platform exposure would exceed limit: ${new_platform} > ${platform_limit}",
                rule_triggered="platform_limit",
            )

        # All rules passed
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="All rules passed",
        )
```

**Step 4: Run test**

Run: `pytest tests/agents/test_risk_guardian.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add platform limit rule to Risk Guardian"
```

---

## Task 4.4: Daily Loss Limit Rule

**Files:**
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_risk_guardian.py`:

```python
@pytest.mark.asyncio
async def test_rejects_trade_when_daily_loss_limit_exceeded() -> None:
    """Should reject trades when daily loss limit is hit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        daily_loss_limit_pct=Decimal("0.05"),  # 5% = $50 max daily loss
    )

    # Simulate $60 loss already today
    guardian._daily_pnl = Decimal("-60")

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Try to trade - should be rejected due to daily loss
    await guardian._evaluate_request({
        "id": "req-001",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is False
    assert decisions[0][1]["rule_triggered"] == "daily_loss_limit"


@pytest.mark.asyncio
async def test_resets_daily_loss_on_new_day() -> None:
    """Should reset daily loss tracking at start of new day."""
    from datetime import timedelta

    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        daily_loss_limit_pct=Decimal("0.05"),
    )

    # Simulate loss from yesterday
    guardian._daily_pnl = Decimal("-60")
    guardian._daily_reset_date = (datetime.now(UTC) - timedelta(days=1)).date()

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Trade should be approved - new day resets loss tracking
    await guardian._evaluate_request({
        "id": "req-001",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_trade_when_daily_loss_limit_exceeded -v`
Expected: FAIL

**Step 3: Update implementation**

Add daily loss check and reset logic:

```python
    async def _check_rules(self, request: TradeRequest) -> RiskDecision:
        """Check request against all risk rules."""
        # Reset daily tracking if new day
        self._maybe_reset_daily()

        # Rule 1: System halted
        if self._halted:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason="System is halted",
                rule_triggered="system_halt",
            )

        # Rule 2: Daily loss limit
        daily_loss_limit = self._initial_bankroll * self._daily_loss_limit_pct
        if self._daily_pnl < -daily_loss_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Daily loss limit exceeded: ${abs(self._daily_pnl)} > ${daily_loss_limit}",
                rule_triggered="daily_loss_limit",
            )

        # Rule 3: Position limit
        position_limit = self._initial_bankroll * self._position_limit_pct
        current_position = self._positions.get(request.market_id, Decimal("0"))
        new_position = current_position + request.amount

        if new_position > position_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Position would exceed limit: ${new_position} > ${position_limit}",
                rule_triggered="position_limit",
            )

        # Rule 4: Platform limit
        platform_limit = self._initial_bankroll * self._platform_limit_pct
        venue = request.market_id.split(":")[0] if ":" in request.market_id else "unknown"
        current_platform = self._platform_exposure.get(venue, Decimal("0"))
        new_platform = current_platform + request.amount

        if new_platform > platform_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Platform exposure would exceed limit: ${new_platform} > ${platform_limit}",
                rule_triggered="platform_limit",
            )

        # All rules passed
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="All rules passed",
        )

    def _maybe_reset_daily(self) -> None:
        """Reset daily tracking if it's a new day."""
        today = datetime.now(UTC).date()
        if today != self._daily_reset_date:
            logger.info(
                "daily_reset",
                previous_pnl=str(self._daily_pnl),
                previous_date=str(self._daily_reset_date),
            )
            self._daily_pnl = Decimal("0")
            self._daily_reset_date = today
```

**Step 4: Run test**

Run: `pytest tests/agents/test_risk_guardian.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add daily loss limit rule to Risk Guardian"
```

---

## Task 4.5: Drawdown Halt Rule

**Files:**
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_risk_guardian.py`:

```python
@pytest.mark.asyncio
async def test_halts_system_on_drawdown() -> None:
    """Should halt system when drawdown exceeds limit."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
        drawdown_limit_pct=Decimal("0.20"),  # 20% drawdown limit
    )

    # Simulate: portfolio grew to $1200, then dropped to $900 (25% drawdown)
    guardian._high_water_mark = Decimal("1200")
    guardian._current_value = Decimal("900")

    decisions: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        decisions.append((channel, data))
        return "mock-id"

    guardian.publish = capture_publish  # type: ignore[method-assign]

    # Any trade should be rejected and system should halt
    await guardian._evaluate_request({
        "id": "req-001",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10",
        "max_price": "0.50",
    })

    assert len(decisions) == 1
    assert decisions[0][1]["approved"] is False
    assert decisions[0][1]["rule_triggered"] == "drawdown_halt"
    assert guardian._halted is True


@pytest.mark.asyncio
async def test_updates_high_water_mark_on_profit() -> None:
    """High water mark should ratchet up with profits."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
    )

    assert guardian._high_water_mark == Decimal("1000")

    # Record profit
    guardian.record_pnl(Decimal("100"))

    assert guardian._current_value == Decimal("1100")
    assert guardian._high_water_mark == Decimal("1100")

    # Record loss
    guardian.record_pnl(Decimal("-50"))

    assert guardian._current_value == Decimal("1050")
    assert guardian._high_water_mark == Decimal("1100")  # Should NOT drop
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py::test_halts_system_on_drawdown -v`
Expected: FAIL

**Step 3: Update implementation**

Add drawdown check and `record_pnl` method:

```python
    async def _check_rules(self, request: TradeRequest) -> RiskDecision:
        """Check request against all risk rules."""
        # Reset daily tracking if new day
        self._maybe_reset_daily()

        # Rule 1: System halted
        if self._halted:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason="System is halted",
                rule_triggered="system_halt",
            )

        # Rule 2: Drawdown check (halt if exceeded)
        drawdown_floor = self._high_water_mark * (1 - self._drawdown_limit_pct)
        if self._current_value < drawdown_floor:
            self._halted = True
            logger.critical(
                "drawdown_halt_triggered",
                current_value=str(self._current_value),
                high_water_mark=str(self._high_water_mark),
                floor=str(drawdown_floor),
            )
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Drawdown limit exceeded: ${self._current_value} < ${drawdown_floor}",
                rule_triggered="drawdown_halt",
            )

        # Rule 3: Daily loss limit
        daily_loss_limit = self._initial_bankroll * self._daily_loss_limit_pct
        if self._daily_pnl < -daily_loss_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Daily loss limit exceeded: ${abs(self._daily_pnl)} > ${daily_loss_limit}",
                rule_triggered="daily_loss_limit",
            )

        # Rule 4: Position limit
        position_limit = self._initial_bankroll * self._position_limit_pct
        current_position = self._positions.get(request.market_id, Decimal("0"))
        new_position = current_position + request.amount

        if new_position > position_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Position would exceed limit: ${new_position} > ${position_limit}",
                rule_triggered="position_limit",
            )

        # Rule 5: Platform limit
        platform_limit = self._initial_bankroll * self._platform_limit_pct
        venue = request.market_id.split(":")[0] if ":" in request.market_id else "unknown"
        current_platform = self._platform_exposure.get(venue, Decimal("0"))
        new_platform = current_platform + request.amount

        if new_platform > platform_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Platform exposure would exceed limit: ${new_platform} > ${platform_limit}",
                rule_triggered="platform_limit",
            )

        # All rules passed
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="All rules passed",
        )

    def record_pnl(self, pnl: Decimal) -> None:
        """Record P&L and update tracking."""
        self._current_value += pnl
        self._daily_pnl += pnl

        # Update high water mark if new peak
        if self._current_value > self._high_water_mark:
            self._high_water_mark = self._current_value
            logger.info(
                "new_high_water_mark",
                value=str(self._high_water_mark),
            )
```

**Step 4: Run test**

Run: `pytest tests/agents/test_risk_guardian.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add drawdown halt rule and high water mark tracking"
```

---

## Task 4.6: Paper Executor Agent

**Files:**
- Create: `src/pm_arb/agents/paper_executor.py`
- Create: `tests/agents/test_paper_executor.py`

**Step 1: Write the failing test**

Create `tests/agents/test_paper_executor.py`:

```python
"""Tests for Paper Executor agent."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.core.models import TradeStatus


@pytest.mark.asyncio
async def test_executor_subscribes_to_decisions() -> None:
    """Executor should subscribe to trade decision channel."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    subs = executor.get_subscriptions()

    assert "trade.decisions" in subs


@pytest.mark.asyncio
async def test_executor_logs_approved_trade() -> None:
    """Executor should publish trade result for approved decisions."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Store the pending request
    executor._pending_requests["req-001"] = {
        "id": "req-001",
        "opportunity_id": "opp-001",
        "strategy": "test-strategy",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "50",
        "max_price": "0.55",
    }

    # Process approved decision
    await executor.handle_message(
        "trade.decisions",
        {
            "request_id": "req-001",
            "approved": True,
            "reason": "All rules passed",
        },
    )

    assert len(published) == 1
    assert published[0][0] == "trade.results"
    result = published[0][1]
    assert result["request_id"] == "req-001"
    assert result["status"] == TradeStatus.FILLED.value
    assert Decimal(result["amount"]) == Decimal("50")
    assert result["paper_trade"] is True


@pytest.mark.asyncio
async def test_executor_ignores_rejected_trade() -> None:
    """Executor should not execute rejected trades."""
    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")

    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Process rejected decision
    await executor.handle_message(
        "trade.decisions",
        {
            "request_id": "req-001",
            "approved": False,
            "reason": "Position limit exceeded",
            "rule_triggered": "position_limit",
        },
    )

    # Should publish rejection result, not a fill
    assert len(published) == 1
    assert published[0][1]["status"] == TradeStatus.REJECTED.value
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_paper_executor.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/agents/paper_executor.py`:

```python
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

        logger.info(
            "paper_trade_executed",
            trade_id=trade.id,
            market=trade.market_id,
            side=trade.side.value,
            outcome=trade.outcome,
            amount=str(trade.amount),
            price=str(trade.price),
        )

        await self._publish_trade_result(trade, paper_trade=True)

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

    async def _publish_trade_result(self, trade: Trade, paper_trade: bool = True) -> None:
        """Publish trade execution result."""
        await self.publish(
            "trade.results",
            {
                "id": trade.id,
                "request_id": trade.request_id,
                "market_id": trade.market_id,
                "venue": trade.venue,
                "side": trade.side.value,
                "outcome": trade.outcome,
                "amount": str(trade.amount),
                "price": str(trade.price),
                "fees": str(trade.fees),
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
git commit -m "feat: add Paper Executor agent for simulated trading"
```

---

## Task 4.7: Sprint 4 Integration Test

**Files:**
- Create: `tests/integration/test_sprint4.py`

**Step 1: Write integration test**

Create `tests/integration/test_sprint4.py`:

```python
"""Integration test for Sprint 4: Risk Guardian + Paper Executor."""

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import TradeStatus


@pytest.mark.asyncio
async def test_opportunity_to_paper_trade_flow() -> None:
    """Full flow: opportunity detected → trade request → risk check → paper execution."""
    redis_url = "redis://localhost:6379"

    # Create agents
    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
        position_limit_pct=Decimal("0.20"),
    )

    executor = PaperExecutorAgent(redis_url=redis_url)

    # Track results
    trade_results: list[dict[str, Any]] = []

    original_executor_publish = executor.publish

    async def capture_results(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            trade_results.append(data)
        return await original_executor_publish(channel, data)

    executor.publish = capture_results  # type: ignore[method-assign]

    # Start agents
    guardian_task = asyncio.create_task(guardian.run())
    executor_task = asyncio.create_task(executor.run())

    await asyncio.sleep(0.2)

    # Simulate trade request (normally from Strategy agent)
    trade_request = {
        "id": "req-test-001",
        "opportunity_id": "opp-001",
        "strategy": "oracle-sniper",
        "market_id": "polymarket:btc-100k-jan",
        "side": "buy",
        "outcome": "YES",
        "amount": "50",
        "max_price": "0.55",
    }

    # Store request in executor and send to guardian
    executor._pending_requests["req-test-001"] = trade_request
    await guardian._evaluate_request(trade_request)

    # Wait for processing
    await asyncio.sleep(0.5)

    # Stop agents
    await guardian.stop()
    await executor.stop()
    await asyncio.gather(guardian_task, executor_task, return_exceptions=True)

    # Verify paper trade was executed
    assert len(trade_results) >= 1

    # Find the filled trade
    filled = [r for r in trade_results if r.get("status") == TradeStatus.FILLED.value]
    assert len(filled) == 1
    assert filled[0]["request_id"] == "req-test-001"
    assert filled[0]["paper_trade"] is True
    assert Decimal(filled[0]["amount"]) == Decimal("50")

    print(f"\nTrade results: {trade_results}")
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_sprint4.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/test_sprint4.py
git commit -m "test: add Sprint 4 integration test - opportunity to paper trade flow"
```

---

## Task 4.8: Sprint 4 Final Commit

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
git commit -m "chore: Sprint 4 complete - Risk Guardian + Paper Executor"
```

---

## Sprint 4 Complete

**Demo steps:**
1. `docker-compose up -d` (Redis)
2. `pytest tests/integration/test_sprint4.py -v`
3. See trade request flow through risk checks to paper execution

**What we built:**
- RiskGuardianAgent with configurable rules:
  - Position limit per market
  - Platform exposure limit
  - Daily loss limit with auto-reset
  - Drawdown halt with high water mark tracking
- PaperExecutorAgent for simulated trading
- Integration test proving end-to-end flow

**Risk rules order:**
1. System halt check
2. Drawdown limit (triggers halt)
3. Daily loss limit
4. Position limit
5. Platform limit

**Next: Sprint 5 - Strategy Agent + Capital Allocator**
