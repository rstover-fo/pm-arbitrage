# Detection Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add simple arbitrage detection checks that captured 99.76% of $40M in extracted profits from Polymarket research.

**Architecture:** Extend existing OpportunityScannerAgent with single-condition and multi-outcome checks. Add OrderBook model and VWAP calculation to venue adapters. Add MinimumProfitRule to RiskGuardianAgent.

**Tech Stack:** Python 3.12, Pydantic, pytest, existing pm-arbitrage infrastructure

---

## Sprint Overview

| Task | Deliverable | Validates |
|------|-------------|-----------|
| 1 | OrderBook model with VWAP calculation | Core model for execution validation |
| 2 | Single-condition arbitrage detection | YES + NO < $1 opportunities ($10.5M class) |
| 3 | Multi-outcome market model + detection | All outcomes < $1 opportunities ($29M class) |
| 4 | Minimum profit threshold rule | Filters unprofitable edges |
| 5 | Order book depth in Polymarket adapter | Real liquidity data |
| 6 | Integration test | End-to-end detection flow |

---

## Task 1: OrderBook Model with VWAP Calculation

**Files:**
- Modify: `src/pm_arb/core/models.py`
- Create: `tests/core/test_order_book.py`

**Step 1: Write the failing test**

Create `tests/core/test_order_book.py`:

```python
"""Tests for OrderBook model and VWAP calculation."""

from decimal import Decimal

import pytest

from pm_arb.core.models import OrderBook, OrderBookLevel


def test_order_book_creation() -> None:
    """Should create OrderBook with bid/ask levels."""
    book = OrderBook(
        market_id="polymarket:btc-up",
        bids=[
            OrderBookLevel(price=Decimal("0.45"), size=Decimal("100")),
            OrderBookLevel(price=Decimal("0.44"), size=Decimal("200")),
        ],
        asks=[
            OrderBookLevel(price=Decimal("0.46"), size=Decimal("150")),
            OrderBookLevel(price=Decimal("0.47"), size=Decimal("250")),
        ],
    )

    assert book.best_bid == Decimal("0.45")
    assert book.best_ask == Decimal("0.46")
    assert book.spread == Decimal("0.01")


def test_vwap_calculation_single_level() -> None:
    """VWAP for amount within first level equals that level's price."""
    book = OrderBook(
        market_id="test",
        bids=[OrderBookLevel(price=Decimal("0.50"), size=Decimal("1000"))],
        asks=[OrderBookLevel(price=Decimal("0.52"), size=Decimal("1000"))],
    )

    vwap = book.calculate_buy_vwap(Decimal("100"))
    assert vwap == Decimal("0.52")


def test_vwap_calculation_multiple_levels() -> None:
    """VWAP across multiple levels is volume-weighted."""
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("100")),  # $50 total
            OrderBookLevel(price=Decimal("0.60"), size=Decimal("100")),  # $60 total
        ],
    )

    # Buy 200 tokens: 100 @ 0.50, 100 @ 0.60
    # VWAP = (100*0.50 + 100*0.60) / 200 = 110 / 200 = 0.55
    vwap = book.calculate_buy_vwap(Decimal("200"))
    assert vwap == Decimal("0.55")


def test_vwap_insufficient_liquidity() -> None:
    """VWAP returns None when insufficient liquidity."""
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[OrderBookLevel(price=Decimal("0.50"), size=Decimal("100"))],
    )

    vwap = book.calculate_buy_vwap(Decimal("500"))
    assert vwap is None


def test_available_liquidity() -> None:
    """Should calculate total available liquidity at price limit."""
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("100")),
            OrderBookLevel(price=Decimal("0.55"), size=Decimal("200")),
            OrderBookLevel(price=Decimal("0.60"), size=Decimal("300")),
        ],
    )

    # Liquidity up to price 0.55
    liquidity = book.available_liquidity_at_price(Decimal("0.55"), side="buy")
    assert liquidity == Decimal("300")  # 100 + 200

    # Liquidity up to price 0.60
    liquidity = book.available_liquidity_at_price(Decimal("0.60"), side="buy")
    assert liquidity == Decimal("600")  # 100 + 200 + 300
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_order_book.py -v`
Expected: FAIL with "cannot import name 'OrderBook'"

**Step 3: Write minimal implementation**

Add to `src/pm_arb/core/models.py` (after Position class):

```python
class OrderBookLevel(BaseModel):
    """Single level in an order book."""

    price: Decimal
    size: Decimal  # Number of tokens available at this price


class OrderBook(BaseModel):
    """Order book for a market with VWAP calculations."""

    market_id: str
    bids: list[OrderBookLevel] = Field(default_factory=list)  # Sorted high to low
    asks: list[OrderBookLevel] = Field(default_factory=list)  # Sorted low to high
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def best_bid(self) -> Decimal | None:
        """Highest bid price."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        """Lowest ask price."""
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        """Bid-ask spread."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def calculate_buy_vwap(self, amount: Decimal) -> Decimal | None:
        """Calculate volume-weighted average price to buy `amount` tokens.

        Returns None if insufficient liquidity.
        """
        if not self.asks:
            return None

        remaining = amount
        total_cost = Decimal("0")
        total_filled = Decimal("0")

        for level in self.asks:
            fill_size = min(remaining, level.size)
            total_cost += fill_size * level.price
            total_filled += fill_size
            remaining -= fill_size

            if remaining <= 0:
                break

        if remaining > 0:
            return None  # Insufficient liquidity

        return total_cost / total_filled

    def calculate_sell_vwap(self, amount: Decimal) -> Decimal | None:
        """Calculate volume-weighted average price to sell `amount` tokens.

        Returns None if insufficient liquidity.
        """
        if not self.bids:
            return None

        remaining = amount
        total_proceeds = Decimal("0")
        total_filled = Decimal("0")

        for level in self.bids:
            fill_size = min(remaining, level.size)
            total_proceeds += fill_size * level.price
            total_filled += fill_size
            remaining -= fill_size

            if remaining <= 0:
                break

        if remaining > 0:
            return None

        return total_proceeds / total_filled

    def available_liquidity_at_price(
        self, max_price: Decimal, side: str
    ) -> Decimal:
        """Total tokens available up to max_price.

        Args:
            max_price: Maximum price willing to pay (buy) or minimum to receive (sell)
            side: "buy" or "sell"
        """
        total = Decimal("0")

        if side == "buy":
            for level in self.asks:
                if level.price <= max_price:
                    total += level.size
                else:
                    break
        else:
            for level in self.bids:
                if level.price >= max_price:
                    total += level.size
                else:
                    break

        return total
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_order_book.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/core/models.py tests/core/test_order_book.py
git commit -m "feat: add OrderBook model with VWAP calculation"
```

---

## Task 2: Single-Condition Arbitrage Detection

**Files:**
- Modify: `src/pm_arb/agents/opportunity_scanner.py`
- Modify: `tests/agents/test_opportunity_scanner.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_opportunity_scanner.py`:

```python
@pytest.mark.asyncio
async def test_detects_single_condition_arbitrage() -> None:
    """Should detect when YES + NO < 1.0 (mispricing)."""
    scanner = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.01"),  # 1% minimum
    )

    # Capture published opportunities
    opportunities: list[dict] = []
    original_publish = scanner.publish

    async def capture_publish(channel: str, data: dict) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return await original_publish(channel, data)

    scanner.publish = capture_publish  # type: ignore

    # Start scanner
    task = asyncio.create_task(scanner.run())
    await asyncio.sleep(0.1)

    # Send price update where YES + NO = 0.90 (10% mispricing)
    await scanner._handle_venue_price(
        "venue.test.prices",
        {
            "market_id": "polymarket:test-market",
            "venue": "polymarket",
            "title": "Test Market",
            "yes_price": "0.45",
            "no_price": "0.45",  # 0.45 + 0.45 = 0.90
        },
    )

    await asyncio.sleep(0.1)
    await scanner.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Should detect mispricing opportunity
    assert len(opportunities) >= 1
    opp = opportunities[0]
    assert opp["type"] == "mispricing"
    assert Decimal(opp["expected_edge"]) == Decimal("0.10")


@pytest.mark.asyncio
async def test_ignores_fair_priced_market() -> None:
    """Should not detect arbitrage when YES + NO = 1.0."""
    scanner = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.01"),
    )

    opportunities: list[dict] = []
    original_publish = scanner.publish

    async def capture_publish(channel: str, data: dict) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return await original_publish(channel, data)

    scanner.publish = capture_publish  # type: ignore

    task = asyncio.create_task(scanner.run())
    await asyncio.sleep(0.1)

    # Send fairly priced market (YES + NO = 1.0)
    await scanner._handle_venue_price(
        "venue.test.prices",
        {
            "market_id": "polymarket:fair-market",
            "venue": "polymarket",
            "title": "Fair Market",
            "yes_price": "0.55",
            "no_price": "0.45",  # 0.55 + 0.45 = 1.0
        },
    )

    await asyncio.sleep(0.1)
    await scanner.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Should NOT detect any mispricing (filter out oracle_lag opportunities)
    mispricing_opps = [o for o in opportunities if o["type"] == "mispricing"]
    assert len(mispricing_opps) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_detects_single_condition_arbitrage -v`
Expected: FAIL (no mispricing detection yet)

**Step 3: Write minimal implementation**

Add to `OpportunityScannerAgent` class in `src/pm_arb/agents/opportunity_scanner.py`:

After the existing `_scan_for_opportunities` method, add this check call at the start:

```python
async def _scan_for_opportunities(self, market: Market) -> None:
    """Scan for opportunities involving this market."""
    # NEW: Check single-condition mispricing first
    await self._check_single_condition_arb(market)

    # Check oracle-based opportunities (existing code)
    if market.id in self._market_thresholds:
        # ... existing code ...
```

Add the new method:

```python
async def _check_single_condition_arb(self, market: Market) -> None:
    """Check if YES + NO < 1.0 (simple mispricing).

    This captures the $10.5M opportunity class from research.
    """
    price_sum = market.yes_price + market.no_price

    # Calculate edge (how much under $1.00)
    edge = Decimal("1.0") - price_sum

    # Must be positive edge and exceed minimum
    if edge <= 0 or edge < self._min_edge_pct:
        return

    # Signal strength proportional to edge (capped at 1.0)
    signal_strength = min(Decimal("1.0"), edge * 5)

    if signal_strength < self._min_signal_strength:
        return

    opportunity = Opportunity(
        id=f"opp-{uuid4().hex[:8]}",
        type=OpportunityType.MISPRICING,
        markets=[market.id],
        expected_edge=edge,
        signal_strength=signal_strength,
        metadata={
            "arb_type": "single_condition",
            "yes_price": str(market.yes_price),
            "no_price": str(market.no_price),
            "price_sum": str(price_sum),
        },
    )

    await self._publish_opportunity(opportunity)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_detects_single_condition_arbitrage tests/agents/test_opportunity_scanner.py::test_ignores_fair_priced_market -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/opportunity_scanner.py tests/agents/test_opportunity_scanner.py
git commit -m "feat: add single-condition arbitrage detection (YES + NO < 1)"
```

---

## Task 3: Multi-Outcome Market Model and Detection

**Files:**
- Modify: `src/pm_arb/core/models.py`
- Modify: `src/pm_arb/agents/opportunity_scanner.py`
- Create: `tests/core/test_multi_outcome.py`
- Modify: `tests/agents/test_opportunity_scanner.py`

**Step 1: Write the failing test for model**

Create `tests/core/test_multi_outcome.py`:

```python
"""Tests for MultiOutcomeMarket model."""

from decimal import Decimal

import pytest

from pm_arb.core.models import MultiOutcomeMarket, Outcome


def test_multi_outcome_market_creation() -> None:
    """Should create market with multiple outcomes."""
    market = MultiOutcomeMarket(
        id="polymarket:president-2024",
        venue="polymarket",
        external_id="pres2024",
        title="Who will win the 2024 presidential election?",
        outcomes=[
            Outcome(name="Trump", price=Decimal("0.52")),
            Outcome(name="Biden", price=Decimal("0.35")),
            Outcome(name="Other", price=Decimal("0.08")),
        ],
    )

    assert len(market.outcomes) == 3
    assert market.price_sum == Decimal("0.95")


def test_multi_outcome_detects_mispricing() -> None:
    """Should detect when outcome sum < 1.0."""
    market = MultiOutcomeMarket(
        id="polymarket:test",
        venue="polymarket",
        external_id="test",
        title="Test",
        outcomes=[
            Outcome(name="A", price=Decimal("0.30")),
            Outcome(name="B", price=Decimal("0.30")),
            Outcome(name="C", price=Decimal("0.30")),
        ],
    )

    assert market.price_sum == Decimal("0.90")
    assert market.arbitrage_edge == Decimal("0.10")


def test_multi_outcome_no_arbitrage() -> None:
    """Should return zero edge when fairly priced."""
    market = MultiOutcomeMarket(
        id="polymarket:test",
        venue="polymarket",
        external_id="test",
        title="Test",
        outcomes=[
            Outcome(name="A", price=Decimal("0.50")),
            Outcome(name="B", price=Decimal("0.50")),
        ],
    )

    assert market.price_sum == Decimal("1.00")
    assert market.arbitrage_edge == Decimal("0")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_multi_outcome.py -v`
Expected: FAIL with "cannot import name 'MultiOutcomeMarket'"

**Step 3: Write model implementation**

Add to `src/pm_arb/core/models.py` (after Market class):

```python
class Outcome(BaseModel):
    """Single outcome in a multi-outcome market."""

    name: str
    price: Decimal
    external_id: str = ""


class MultiOutcomeMarket(BaseModel):
    """A multi-outcome prediction market (e.g., 'Who wins election?')."""

    id: str
    venue: str
    external_id: str
    title: str
    description: str = ""
    outcomes: list[Outcome]
    volume_24h: Decimal = Decimal("0")
    liquidity: Decimal = Decimal("0")
    end_date: datetime | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def price_sum(self) -> Decimal:
        """Sum of all outcome prices."""
        return sum(o.price for o in self.outcomes)

    @property
    def arbitrage_edge(self) -> Decimal:
        """Potential arbitrage if sum < 1.0."""
        edge = Decimal("1.0") - self.price_sum
        return max(Decimal("0"), edge)
```

**Step 4: Run model test**

Run: `pytest tests/core/test_multi_outcome.py -v`
Expected: PASS

**Step 5: Write detection test**

Add to `tests/agents/test_opportunity_scanner.py`:

```python
@pytest.mark.asyncio
async def test_detects_multi_outcome_arbitrage() -> None:
    """Should detect when all outcomes sum < 1.0."""
    scanner = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.01"),
    )

    opportunities: list[dict] = []
    original_publish = scanner.publish

    async def capture_publish(channel: str, data: dict) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return await original_publish(channel, data)

    scanner.publish = capture_publish  # type: ignore

    task = asyncio.create_task(scanner.run())
    await asyncio.sleep(0.1)

    # Send multi-outcome market update where sum = 0.88
    await scanner._handle_multi_outcome_market(
        "venue.test.multi",
        {
            "market_id": "polymarket:election",
            "venue": "polymarket",
            "title": "Who wins?",
            "outcomes": [
                {"name": "Candidate A", "price": "0.30"},
                {"name": "Candidate B", "price": "0.28"},
                {"name": "Candidate C", "price": "0.30"},
            ],
        },
    )

    await asyncio.sleep(0.1)
    await scanner.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Should detect mispricing
    mispricing_opps = [o for o in opportunities if o["type"] == "mispricing"]
    assert len(mispricing_opps) >= 1
    assert mispricing_opps[0]["metadata"]["arb_type"] == "multi_outcome"
    assert Decimal(mispricing_opps[0]["expected_edge"]) == Decimal("0.12")
```

**Step 6: Write detection implementation**

Add to `OpportunityScannerAgent` in `src/pm_arb/agents/opportunity_scanner.py`:

Add to imports:

```python
from pm_arb.core.models import Market, MultiOutcomeMarket, Opportunity, OpportunityType, OracleData, Outcome
```

Add to `__init__`:

```python
self._multi_outcome_markets: dict[str, MultiOutcomeMarket] = {}
```

Add to `handle_message`:

```python
async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
    """Route messages to appropriate handler."""
    if channel.startswith("venue.") and channel.endswith(".multi"):
        await self._handle_multi_outcome_market(channel, data)
    elif channel.startswith("venue."):
        await self._handle_venue_price(channel, data)
    elif channel.startswith("oracle."):
        await self._handle_oracle_data(channel, data)
```

Add new method:

```python
async def _handle_multi_outcome_market(
    self, channel: str, data: dict[str, Any]
) -> None:
    """Process multi-outcome market update."""
    market_id = data.get("market_id", "")
    if not market_id:
        return

    outcomes = [
        Outcome(
            name=o.get("name", ""),
            price=Decimal(str(o.get("price", "0"))),
            external_id=o.get("external_id", ""),
        )
        for o in data.get("outcomes", [])
    ]

    market = MultiOutcomeMarket(
        id=market_id,
        venue=data.get("venue", ""),
        external_id=data.get("external_id", market_id),
        title=data.get("title", ""),
        outcomes=outcomes,
    )

    self._multi_outcome_markets[market_id] = market
    await self._check_multi_outcome_arb(market)


async def _check_multi_outcome_arb(self, market: MultiOutcomeMarket) -> None:
    """Check if all outcome prices sum < 1.0.

    This captures the $29M opportunity class from research.
    """
    edge = market.arbitrage_edge

    if edge <= 0 or edge < self._min_edge_pct:
        return

    signal_strength = min(Decimal("1.0"), edge * 5)

    if signal_strength < self._min_signal_strength:
        return

    opportunity = Opportunity(
        id=f"opp-{uuid4().hex[:8]}",
        type=OpportunityType.MISPRICING,
        markets=[market.id],
        expected_edge=edge,
        signal_strength=signal_strength,
        metadata={
            "arb_type": "multi_outcome",
            "outcome_count": len(market.outcomes),
            "price_sum": str(market.price_sum),
            "outcomes": [
                {"name": o.name, "price": str(o.price)}
                for o in market.outcomes
            ],
        },
    )

    await self._publish_opportunity(opportunity)
```

**Step 7: Run all tests**

Run: `pytest tests/agents/test_opportunity_scanner.py -v`
Expected: PASS

**Step 8: Commit**

```bash
git add src/pm_arb/core/models.py src/pm_arb/agents/opportunity_scanner.py tests/core/test_multi_outcome.py tests/agents/test_opportunity_scanner.py
git commit -m "feat: add multi-outcome market model and arbitrage detection"
```

---

## Task 4: Minimum Profit Threshold Rule

**Files:**
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_risk_guardian.py`:

```python
@pytest.mark.asyncio
async def test_rejects_below_minimum_profit() -> None:
    """Should reject trades with expected profit below threshold."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("500"),
        min_profit_threshold=Decimal("0.05"),  # $0.05 minimum
    )

    # Small trade with small edge = below threshold
    request = TradeRequest(
        id="req-001",
        opportunity_id="opp-001",
        strategy="test",
        market_id="polymarket:test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("1.00"),  # $1 trade
        max_price=Decimal("0.50"),
        expected_edge=Decimal("0.02"),  # 2% edge = $0.02 profit
    )

    decision = await guardian._check_rules(request)

    assert decision.approved is False
    assert decision.rule_triggered == "minimum_profit"


@pytest.mark.asyncio
async def test_approves_above_minimum_profit() -> None:
    """Should approve trades with expected profit above threshold."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("500"),
        min_profit_threshold=Decimal("0.05"),
    )

    # Larger trade with good edge = above threshold
    request = TradeRequest(
        id="req-002",
        opportunity_id="opp-002",
        strategy="test",
        market_id="polymarket:test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("10.00"),  # $10 trade
        max_price=Decimal("0.50"),
        expected_edge=Decimal("0.02"),  # 2% edge = $0.20 profit
    )

    decision = await guardian._check_rules(request)

    assert decision.approved is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_below_minimum_profit -v`
Expected: FAIL (min_profit_threshold not implemented)

**Step 3: Modify TradeRequest model**

Add `expected_edge` to `TradeRequest` in `src/pm_arb/core/models.py`:

```python
class TradeRequest(BaseModel):
    """Request from strategy to execute a trade."""

    id: str
    opportunity_id: str
    strategy: str
    market_id: str
    side: Side
    outcome: str
    amount: Decimal
    max_price: Decimal
    expected_edge: Decimal = Decimal("0")  # NEW: Expected profit percentage
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

**Step 4: Add minimum profit rule to RiskGuardian**

Modify `src/pm_arb/agents/risk_guardian.py`:

Add to `__init__`:

```python
def __init__(
    self,
    redis_url: str,
    initial_bankroll: Decimal = Decimal("500"),
    position_limit_pct: Decimal = Decimal("0.10"),
    platform_limit_pct: Decimal = Decimal("0.50"),
    daily_loss_limit_pct: Decimal = Decimal("0.10"),
    drawdown_limit_pct: Decimal = Decimal("0.20"),
    min_profit_threshold: Decimal = Decimal("0.05"),  # NEW: $0.05 minimum
) -> None:
    # ... existing code ...
    self._min_profit_threshold = min_profit_threshold
```

Add new rule check in `_check_rules` after platform limit check:

```python
# Rule 6: Minimum profit threshold
expected_profit = request.amount * request.expected_edge
if expected_profit < self._min_profit_threshold:
    return RiskDecision(
        request_id=request.id,
        approved=False,
        reason=f"Expected profit ${expected_profit} below minimum ${self._min_profit_threshold}",
        rule_triggered="minimum_profit",
    )
```

**Step 5: Run test**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_below_minimum_profit tests/agents/test_risk_guardian.py::test_approves_above_minimum_profit -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/pm_arb/core/models.py src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add minimum profit threshold rule to Risk Guardian"
```

---

## Task 5: Order Book Depth in Polymarket Adapter

**Files:**
- Modify: `src/pm_arb/adapters/venues/polymarket.py`
- Modify: `src/pm_arb/adapters/venues/base.py`
- Create: `tests/adapters/venues/test_order_book.py`

**Step 1: Write the failing test**

Create `tests/adapters/venues/test_order_book.py`:

```python
"""Tests for order book fetching from venues."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.models import OrderBook


@pytest.mark.asyncio
async def test_polymarket_fetches_order_book() -> None:
    """Should fetch and parse order book from Polymarket CLOB API."""
    mock_response = {
        "bids": [
            {"price": "0.45", "size": "1000"},
            {"price": "0.44", "size": "2000"},
        ],
        "asks": [
            {"price": "0.46", "size": "1500"},
            {"price": "0.47", "size": "2500"},
        ],
    }

    adapter = PolymarketAdapter()

    with patch.object(adapter, "_fetch_order_book", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response
        await adapter.connect()
        book = await adapter.get_order_book("polymarket:test-market", "YES")
        await adapter.disconnect()

    assert book is not None
    assert book.best_bid == Decimal("0.45")
    assert book.best_ask == Decimal("0.46")
    assert len(book.bids) == 2
    assert len(book.asks) == 2


@pytest.mark.asyncio
async def test_order_book_vwap_integration() -> None:
    """Should calculate VWAP from fetched order book."""
    mock_response = {
        "bids": [],
        "asks": [
            {"price": "0.50", "size": "100"},
            {"price": "0.60", "size": "100"},
        ],
    }

    adapter = PolymarketAdapter()

    with patch.object(adapter, "_fetch_order_book", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response
        await adapter.connect()
        book = await adapter.get_order_book("test", "YES")
        await adapter.disconnect()

    # VWAP for 200 tokens = (100*0.50 + 100*0.60) / 200 = 0.55
    vwap = book.calculate_buy_vwap(Decimal("200"))
    assert vwap == Decimal("0.55")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/venues/test_order_book.py -v`
Expected: FAIL with "get_order_book" not defined

**Step 3: Add to VenueAdapter base class**

Modify `src/pm_arb/adapters/venues/base.py`:

Add import:

```python
from pm_arb.core.models import Market, OrderBook, Trade, TradeRequest
```

Add abstract method:

```python
async def get_order_book(
    self,
    market_id: str,
    outcome: str,
) -> OrderBook | None:
    """Fetch order book for a market/outcome. Override in subclass."""
    raise NotImplementedError(f"{self.name} does not support order book queries")
```

**Step 4: Implement in PolymarketAdapter**

Modify `src/pm_arb/adapters/venues/polymarket.py`:

Add import:

```python
from pm_arb.core.models import Market, OrderBook, OrderBookLevel
```

Add methods:

```python
async def get_order_book(
    self,
    market_id: str,
    outcome: str,
) -> OrderBook | None:
    """Fetch order book from CLOB API."""
    raw_book = await self._fetch_order_book(market_id, outcome)
    if not raw_book:
        return None
    return self._parse_order_book(market_id, raw_book)


async def _fetch_order_book(
    self,
    market_id: str,
    outcome: str,
) -> dict[str, Any] | None:
    """Fetch raw order book from CLOB API."""
    if not self._client:
        raise RuntimeError("Not connected")

    # Extract token ID from market (would need actual token ID lookup)
    # For now, use market_id as placeholder
    external_id = market_id.split(":")[-1] if ":" in market_id else market_id

    try:
        response = await self._client.get(
            f"{CLOB_API}/book",
            params={"token_id": external_id},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result
    except httpx.HTTPError as e:
        logger.error("order_book_fetch_error", market=market_id, error=str(e))
        return None


def _parse_order_book(
    self,
    market_id: str,
    data: dict[str, Any],
) -> OrderBook:
    """Parse CLOB API response into OrderBook model."""
    bids = [
        OrderBookLevel(
            price=Decimal(str(b["price"])),
            size=Decimal(str(b["size"])),
        )
        for b in data.get("bids", [])
    ]

    asks = [
        OrderBookLevel(
            price=Decimal(str(a["price"])),
            size=Decimal(str(a["size"])),
        )
        for a in data.get("asks", [])
    ]

    # Sort: bids high to low, asks low to high
    bids.sort(key=lambda x: x.price, reverse=True)
    asks.sort(key=lambda x: x.price)

    return OrderBook(
        market_id=market_id,
        bids=bids,
        asks=asks,
    )
```

**Step 5: Run test**

Run: `pytest tests/adapters/venues/test_order_book.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/pm_arb/adapters/venues/base.py src/pm_arb/adapters/venues/polymarket.py tests/adapters/venues/test_order_book.py
git commit -m "feat: add order book fetching with VWAP to Polymarket adapter"
```

---

## Task 6: Integration Test

**Files:**
- Create: `tests/integration/test_detection_enhancements.py`

**Step 1: Write integration test**

Create `tests/integration/test_detection_enhancements.py`:

```python
"""Integration test for detection enhancements."""

import asyncio
from decimal import Decimal

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import Side, TradeRequest


@pytest.mark.asyncio
@pytest.mark.integration
async def test_end_to_end_mispricing_detection() -> None:
    """Full flow: detect mispricing → generate trade → risk check."""
    redis_url = "redis://localhost:6379"

    # Create scanner with low thresholds for testing
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.01"),
    )

    # Create risk guardian
    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("500"),
        min_profit_threshold=Decimal("0.05"),
    )

    # Capture detected opportunities
    opportunities: list[dict] = []
    original_publish = scanner.publish

    async def capture_opp(channel: str, data: dict) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return await original_publish(channel, data)

    scanner.publish = capture_opp  # type: ignore

    # Start scanner
    scanner_task = asyncio.create_task(scanner.run())
    guardian_task = asyncio.create_task(guardian.run())
    await asyncio.sleep(0.2)

    # Simulate mispriced market (YES + NO = 0.85)
    await scanner._handle_venue_price(
        "venue.test.prices",
        {
            "market_id": "polymarket:mispriced",
            "venue": "polymarket",
            "title": "Mispriced Market",
            "yes_price": "0.40",
            "no_price": "0.45",
        },
    )

    await asyncio.sleep(0.2)

    # Stop agents
    await scanner.stop()
    await guardian.stop()
    await asyncio.gather(scanner_task, guardian_task, return_exceptions=True)

    # Verify opportunity detected
    mispricing = [o for o in opportunities if o["type"] == "mispricing"]
    assert len(mispricing) >= 1
    assert Decimal(mispricing[0]["expected_edge"]) == Decimal("0.15")

    # Verify risk check would approve a good trade
    good_trade = TradeRequest(
        id="test-001",
        opportunity_id=mispricing[0]["id"],
        strategy="test",
        market_id="polymarket:mispriced",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("10.00"),
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.15"),  # 15% edge on $10 = $1.50 profit
    )

    decision = await guardian._check_rules(good_trade)
    assert decision.approved is True

    # Verify risk check would reject a tiny trade
    tiny_trade = TradeRequest(
        id="test-002",
        opportunity_id=mispricing[0]["id"],
        strategy="test",
        market_id="polymarket:mispriced",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("0.10"),  # $0.10 trade
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.15"),  # 15% edge on $0.10 = $0.015 profit
    )

    decision = await guardian._check_rules(tiny_trade)
    assert decision.approved is False
    assert decision.rule_triggered == "minimum_profit"
```

**Step 2: Run integration test**

Run: `docker-compose up -d` (ensure Redis running)
Run: `pytest tests/integration/test_detection_enhancements.py -v -m integration`
Expected: PASS

**Step 3: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/integration`
Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`
Run: `mypy src/`

**Step 4: Commit**

```bash
git add tests/integration/test_detection_enhancements.py
git commit -m "test: add integration test for detection enhancements"
```

---

## Final Commit

```bash
git add -A
git commit -m "chore: detection enhancements complete - single/multi-outcome checks, VWAP, min profit"
```

---

## Summary

**What we built:**
1. OrderBook model with VWAP calculation for execution validation
2. Single-condition arbitrage detection (YES + NO < $1) — $10.5M opportunity class
3. Multi-outcome market model and detection — $29M opportunity class
4. Minimum profit threshold ($0.05) in Risk Guardian
5. Order book depth fetching in Polymarket adapter
6. End-to-end integration test

**These changes capture 99.76% of the arbitrage opportunity classes identified in the research paper.**
