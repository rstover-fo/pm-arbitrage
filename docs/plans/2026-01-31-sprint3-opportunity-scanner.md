# Sprint 3: Opportunity Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an Opportunity Scanner agent that detects arbitrage opportunities by comparing prediction market prices against oracle data (crypto prices) and identifying when markets lag behind real-world events.

**Architecture:** The OpportunityScannerAgent subscribes to both venue price updates (`venue.*.prices`) and oracle data (`oracle.*.*`). It maintains a cache of current prices and oracle values, then applies detection algorithms to identify when PM prices diverge significantly from what oracle data suggests they should be. Detected opportunities are published to `opportunities.detected` for downstream processing.

**Tech Stack:** Python 3.12, asyncio, Redis Streams, Pydantic, pytest, structlog

**Demo:** Run the scanner with live Binance + Polymarket data, see opportunities logged when BTC moves and crypto markets haven't updated yet.

---

## Task 3.1: Opportunity Scanner Agent Skeleton

**Files:**
- Create: `src/pm_arb/agents/opportunity_scanner.py`
- Create: `tests/agents/test_opportunity_scanner.py`

**Step 1: Write the failing test**

Create `tests/agents/test_opportunity_scanner.py`:

```python
"""Tests for Opportunity Scanner agent."""

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.core.models import Market, OpportunityType


@pytest.mark.asyncio
async def test_scanner_subscribes_to_channels() -> None:
    """Scanner should subscribe to venue and oracle channels."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
    )

    subs = agent.get_subscriptions()

    assert "venue.polymarket.prices" in subs
    assert "oracle.binance.BTC" in subs
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_opportunity_scanner.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/agents/opportunity_scanner.py`:

```python
"""Opportunity Scanner Agent - detects arbitrage opportunities."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Market, Opportunity, OpportunityType, OracleData

logger = structlog.get_logger()


class OpportunityScannerAgent(BaseAgent):
    """Scans for arbitrage opportunities across venues and oracles."""

    def __init__(
        self,
        redis_url: str,
        venue_channels: list[str],
        oracle_channels: list[str],
        min_edge_pct: Decimal = Decimal("0.02"),  # 2% minimum edge
        min_signal_strength: Decimal = Decimal("0.5"),
    ) -> None:
        self.name = "opportunity-scanner"
        super().__init__(redis_url)
        self._venue_channels = venue_channels
        self._oracle_channels = oracle_channels
        self._min_edge_pct = min_edge_pct
        self._min_signal_strength = min_signal_strength

        # Cache of current state
        self._markets: dict[str, Market] = {}
        self._oracle_values: dict[str, OracleData] = {}
        self._market_oracle_map: dict[str, str] = {}  # market_id -> oracle_symbol

    def get_subscriptions(self) -> list[str]:
        """Subscribe to venue prices and oracle data."""
        return self._venue_channels + self._oracle_channels

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Route messages to appropriate handler."""
        if channel.startswith("venue."):
            await self._handle_venue_price(channel, data)
        elif channel.startswith("oracle."):
            await self._handle_oracle_data(channel, data)

    async def _handle_venue_price(self, channel: str, data: dict[str, Any]) -> None:
        """Process venue price update."""
        market_id = data.get("market_id", "")
        if not market_id:
            return

        market = Market(
            id=market_id,
            venue=data.get("venue", ""),
            external_id=data.get("external_id", market_id),
            title=data.get("title", ""),
            yes_price=Decimal(str(data.get("yes_price", "0.5"))),
            no_price=Decimal(str(data.get("no_price", "0.5"))),
        )
        self._markets[market_id] = market

        # Check for opportunities
        await self._scan_for_opportunities(market)

    async def _handle_oracle_data(self, channel: str, data: dict[str, Any]) -> None:
        """Process oracle data update."""
        symbol = data.get("symbol", "")
        if not symbol:
            return

        oracle_data = OracleData(
            source=data.get("source", ""),
            symbol=symbol,
            value=Decimal(str(data.get("value", "0"))),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now(UTC).isoformat())),
            metadata=data.get("metadata", {}),
        )
        self._oracle_values[symbol] = oracle_data

        # Check all markets that depend on this oracle
        await self._scan_oracle_opportunities(symbol, oracle_data)

    async def _scan_for_opportunities(self, market: Market) -> None:
        """Scan for opportunities involving this market."""
        # Placeholder - will be implemented in Task 3.2
        pass

    async def _scan_oracle_opportunities(self, symbol: str, oracle_data: OracleData) -> None:
        """Scan for oracle-based opportunities."""
        # Placeholder - will be implemented in Task 3.2
        pass
```

**Step 4: Run test**

Run: `pytest tests/agents/test_opportunity_scanner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/opportunity_scanner.py tests/agents/test_opportunity_scanner.py
git commit -m "feat: add Opportunity Scanner agent skeleton"
```

---

## Task 3.2: Oracle-Based Opportunity Detection

**Files:**
- Modify: `src/pm_arb/agents/opportunity_scanner.py`
- Modify: `tests/agents/test_opportunity_scanner.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_opportunity_scanner.py`:

```python
@pytest.mark.asyncio
async def test_detects_oracle_lag_opportunity() -> None:
    """Should detect when PM price lags behind oracle price movement."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
        min_edge_pct=Decimal("0.01"),  # 1% edge threshold
    )

    # Register a crypto market that tracks BTC price
    agent.register_market_oracle_mapping(
        market_id="polymarket:btc-above-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),  # Market: "Will BTC be above $100k?"
        direction="above",
    )

    # Simulate: BTC jumps to $105k but market still prices YES at 50%
    # This is a buying opportunity - BTC is already above threshold
    published = []
    original_publish = agent.publish

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Feed oracle data showing BTC at $105k
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {
            "source": "binance",
            "symbol": "BTC",
            "value": "105000",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )

    # Feed market data showing YES still at 50%
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {
            "market_id": "polymarket:btc-above-100k",
            "venue": "polymarket",
            "title": "Will BTC be above $100k?",
            "yes_price": "0.50",
            "no_price": "0.50",
        },
    )

    # Should detect opportunity
    assert len(published) == 1
    assert published[0][0] == "opportunities.detected"
    opp = published[0][1]
    assert opp["type"] == OpportunityType.ORACLE_LAG.value
    assert Decimal(opp["expected_edge"]) > Decimal("0.40")  # ~45% edge (should be ~95% not 50%)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_detects_oracle_lag_opportunity -v`
Expected: FAIL (AttributeError: register_market_oracle_mapping)

**Step 3: Write implementation**

Update `src/pm_arb/agents/opportunity_scanner.py` - add after `__init__`:

```python
    def register_market_oracle_mapping(
        self,
        market_id: str,
        oracle_symbol: str,
        threshold: Decimal,
        direction: str,  # "above" or "below"
    ) -> None:
        """Register a market that tracks an oracle threshold."""
        self._market_oracle_map[market_id] = oracle_symbol
        self._market_thresholds[market_id] = {
            "threshold": threshold,
            "direction": direction,
            "oracle_symbol": oracle_symbol,
        }
```

Add `_market_thresholds` to `__init__`:

```python
        self._market_thresholds: dict[str, dict[str, Any]] = {}
```

Replace `_scan_for_opportunities` and `_scan_oracle_opportunities`:

```python
    async def _scan_for_opportunities(self, market: Market) -> None:
        """Scan for opportunities involving this market."""
        # Check if this market has an oracle mapping
        if market.id not in self._market_thresholds:
            return

        threshold_info = self._market_thresholds[market.id]
        oracle_symbol = threshold_info["oracle_symbol"]

        if oracle_symbol not in self._oracle_values:
            return

        oracle_data = self._oracle_values[oracle_symbol]
        await self._check_oracle_lag(market, oracle_data, threshold_info)

    async def _scan_oracle_opportunities(self, symbol: str, oracle_data: OracleData) -> None:
        """Scan for oracle-based opportunities when oracle updates."""
        # Find all markets that track this oracle
        for market_id, oracle_symbol in self._market_oracle_map.items():
            if oracle_symbol != symbol:
                continue
            if market_id not in self._markets:
                continue
            if market_id not in self._market_thresholds:
                continue

            market = self._markets[market_id]
            threshold_info = self._market_thresholds[market_id]
            await self._check_oracle_lag(market, oracle_data, threshold_info)

    async def _check_oracle_lag(
        self,
        market: Market,
        oracle_data: OracleData,
        threshold_info: dict[str, Any],
    ) -> None:
        """Check if market price lags behind oracle reality."""
        threshold = threshold_info["threshold"]
        direction = threshold_info["direction"]

        # Calculate what the fair price should be based on oracle
        if direction == "above":
            # If oracle > threshold, YES should be ~1.0
            oracle_suggests_yes = oracle_data.value > threshold
        else:
            # If oracle < threshold, YES should be ~1.0
            oracle_suggests_yes = oracle_data.value < threshold

        # Calculate implied probability from oracle
        # If condition is met, fair value is high (0.95)
        # If not met, fair value is low (0.05)
        # Add buffer zone around threshold
        distance_pct = abs(oracle_data.value - threshold) / threshold

        if oracle_suggests_yes:
            # Condition met - YES should be high
            if distance_pct > Decimal("0.05"):  # 5% buffer
                fair_yes_price = Decimal("0.95")
            else:
                fair_yes_price = Decimal("0.50") + (distance_pct * 10)  # Scale up
        else:
            # Condition not met - YES should be low
            if distance_pct > Decimal("0.05"):
                fair_yes_price = Decimal("0.05")
            else:
                fair_yes_price = Decimal("0.50") - (distance_pct * 10)

        # Calculate edge
        current_yes = market.yes_price
        edge = fair_yes_price - current_yes

        if abs(edge) < self._min_edge_pct:
            return  # Not enough edge

        # Calculate signal strength based on oracle distance from threshold
        signal_strength = min(Decimal("1.0"), distance_pct * 10)

        if signal_strength < self._min_signal_strength:
            return

        # Publish opportunity
        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.ORACLE_LAG,
            markets=[market.id],
            oracle_source=oracle_data.source,
            oracle_value=oracle_data.value,
            expected_edge=edge,
            signal_strength=signal_strength,
            metadata={
                "threshold": str(threshold),
                "direction": direction,
                "fair_yes_price": str(fair_yes_price),
                "current_yes_price": str(current_yes),
            },
        )

        await self._publish_opportunity(opportunity)

    async def _publish_opportunity(self, opportunity: Opportunity) -> None:
        """Publish detected opportunity."""
        logger.info(
            "opportunity_detected",
            opp_id=opportunity.id,
            type=opportunity.type.value,
            edge=str(opportunity.expected_edge),
            signal=str(opportunity.signal_strength),
        )

        await self.publish(
            "opportunities.detected",
            {
                "id": opportunity.id,
                "type": opportunity.type.value,
                "markets": opportunity.markets,
                "oracle_source": opportunity.oracle_source,
                "oracle_value": str(opportunity.oracle_value) if opportunity.oracle_value else None,
                "expected_edge": str(opportunity.expected_edge),
                "signal_strength": str(opportunity.signal_strength),
                "detected_at": opportunity.detected_at.isoformat(),
                "metadata": opportunity.metadata,
            },
        )
```

**Step 4: Run test**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_detects_oracle_lag_opportunity -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/opportunity_scanner.py tests/agents/test_opportunity_scanner.py
git commit -m "feat: add oracle-based opportunity detection"
```

---

## Task 3.3: Cross-Platform Opportunity Detection

**Files:**
- Modify: `src/pm_arb/agents/opportunity_scanner.py`
- Modify: `tests/agents/test_opportunity_scanner.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_opportunity_scanner.py`:

```python
@pytest.mark.asyncio
async def test_detects_cross_platform_opportunity() -> None:
    """Should detect price discrepancy between matched markets on different venues."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices", "venue.kalshi.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.03"),  # 3% edge threshold
    )

    # Register two markets as tracking the same event
    agent.register_matched_markets(
        market_ids=["polymarket:btc-100k-jan", "kalshi:btc-100k-jan"],
        event_id="btc-100k-jan-2026",
    )

    published = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Polymarket has YES at 60%
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {
            "market_id": "polymarket:btc-100k-jan",
            "venue": "polymarket",
            "title": "BTC above $100k in Jan?",
            "yes_price": "0.60",
            "no_price": "0.40",
        },
    )

    # Kalshi has YES at 52% - 8% discrepancy
    await agent._handle_venue_price(
        "venue.kalshi.prices",
        {
            "market_id": "kalshi:btc-100k-jan",
            "venue": "kalshi",
            "title": "BTC above $100k in Jan?",
            "yes_price": "0.52",
            "no_price": "0.48",
        },
    )

    # Should detect cross-platform opportunity
    assert len(published) == 1
    assert published[0][0] == "opportunities.detected"
    opp = published[0][1]
    assert opp["type"] == OpportunityType.CROSS_PLATFORM.value
    assert len(opp["markets"]) == 2
    assert Decimal(opp["expected_edge"]) >= Decimal("0.03")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_detects_cross_platform_opportunity -v`
Expected: FAIL (AttributeError: register_matched_markets)

**Step 3: Write implementation**

Add to `__init__` in `opportunity_scanner.py`:

```python
        # Cross-platform matching
        self._matched_markets: dict[str, list[str]] = {}  # event_id -> [market_ids]
        self._market_to_event: dict[str, str] = {}  # market_id -> event_id
```

Add method:

```python
    def register_matched_markets(
        self,
        market_ids: list[str],
        event_id: str,
    ) -> None:
        """Register markets that track the same underlying event."""
        self._matched_markets[event_id] = market_ids
        for market_id in market_ids:
            self._market_to_event[market_id] = event_id
```

Update `_scan_for_opportunities`:

```python
    async def _scan_for_opportunities(self, market: Market) -> None:
        """Scan for opportunities involving this market."""
        # Check oracle-based opportunities
        if market.id in self._market_thresholds:
            threshold_info = self._market_thresholds[market.id]
            oracle_symbol = threshold_info["oracle_symbol"]
            if oracle_symbol in self._oracle_values:
                oracle_data = self._oracle_values[oracle_symbol]
                await self._check_oracle_lag(market, oracle_data, threshold_info)

        # Check cross-platform opportunities
        if market.id in self._market_to_event:
            await self._check_cross_platform(market)

    async def _check_cross_platform(self, updated_market: Market) -> None:
        """Check for cross-platform arbitrage opportunities."""
        event_id = self._market_to_event.get(updated_market.id)
        if not event_id:
            return

        matched_ids = self._matched_markets.get(event_id, [])
        if len(matched_ids) < 2:
            return

        # Get all markets for this event
        markets = [
            self._markets[mid]
            for mid in matched_ids
            if mid in self._markets
        ]

        if len(markets) < 2:
            return

        # Find max and min YES prices
        prices = [(m, m.yes_price) for m in markets]
        prices.sort(key=lambda x: x[1])

        lowest_market, lowest_price = prices[0]
        highest_market, highest_price = prices[-1]

        # Calculate edge (buy YES on cheap venue, buy NO on expensive venue)
        edge = highest_price - lowest_price

        if edge < self._min_edge_pct:
            return

        # Signal strength based on price difference
        signal_strength = min(Decimal("1.0"), edge * 5)

        if signal_strength < self._min_signal_strength:
            return

        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.CROSS_PLATFORM,
            markets=[lowest_market.id, highest_market.id],
            expected_edge=edge,
            signal_strength=signal_strength,
            metadata={
                "event_id": event_id,
                "buy_yes_venue": lowest_market.venue,
                "buy_yes_price": str(lowest_price),
                "buy_no_venue": highest_market.venue,
                "buy_no_price": str(Decimal("1") - highest_price),
            },
        )

        await self._publish_opportunity(opportunity)
```

**Step 4: Run test**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_detects_cross_platform_opportunity -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/opportunity_scanner.py tests/agents/test_opportunity_scanner.py
git commit -m "feat: add cross-platform opportunity detection"
```

---

## Task 3.4: Signal Strength Calculation

**Files:**
- Modify: `src/pm_arb/agents/opportunity_scanner.py`
- Modify: `tests/agents/test_opportunity_scanner.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_opportunity_scanner.py`:

```python
@pytest.mark.asyncio
async def test_signal_strength_increases_with_edge() -> None:
    """Signal strength should increase with larger edge."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.1"),
    )

    agent.register_market_oracle_mapping(
        market_id="polymarket:btc-above-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),
        direction="above",
    )

    published = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Test 1: BTC at $110k (10% above threshold) - high signal
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {"source": "binance", "symbol": "BTC", "value": "110000", "timestamp": datetime.now(UTC).isoformat()},
    )
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {"market_id": "polymarket:btc-above-100k", "venue": "polymarket", "title": "BTC>100k", "yes_price": "0.50", "no_price": "0.50"},
    )

    high_edge_signal = Decimal(published[0][1]["signal_strength"])

    # Test 2: BTC at $102k (2% above threshold) - lower signal
    published.clear()
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {"source": "binance", "symbol": "BTC", "value": "102000", "timestamp": datetime.now(UTC).isoformat()},
    )
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {"market_id": "polymarket:btc-above-100k", "venue": "polymarket", "title": "BTC>100k", "yes_price": "0.50", "no_price": "0.50"},
    )

    low_edge_signal = Decimal(published[0][1]["signal_strength"])

    assert high_edge_signal > low_edge_signal


@pytest.mark.asyncio
async def test_filters_low_signal_opportunities() -> None:
    """Should not publish opportunities below signal threshold."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.8"),  # High threshold
    )

    agent.register_market_oracle_mapping(
        market_id="polymarket:btc-above-100k",
        oracle_symbol="BTC",
        threshold=Decimal("100000"),
        direction="above",
    )

    published = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # BTC barely above threshold - weak signal
    await agent._handle_oracle_data(
        "oracle.binance.BTC",
        {"source": "binance", "symbol": "BTC", "value": "100500", "timestamp": datetime.now(UTC).isoformat()},
    )
    await agent._handle_venue_price(
        "venue.polymarket.prices",
        {"market_id": "polymarket:btc-above-100k", "venue": "polymarket", "title": "BTC>100k", "yes_price": "0.50", "no_price": "0.50"},
    )

    # Should NOT publish due to low signal
    assert len(published) == 0
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/agents/test_opportunity_scanner.py::test_signal_strength_increases_with_edge -v`
Run: `pytest tests/agents/test_opportunity_scanner.py::test_filters_low_signal_opportunities -v`
Expected: PASS (implementation already handles this)

**Step 3: Commit tests**

```bash
git add tests/agents/test_opportunity_scanner.py
git commit -m "test: add signal strength tests for opportunity scanner"
```

---

## Task 3.5: Sprint 3 Integration Test

**Files:**
- Create: `tests/integration/test_sprint3.py`

**Step 1: Write integration test**

Create `tests/integration/test_sprint3.py`:

```python
"""Integration test for Sprint 3: Opportunity Scanner with live data."""

import asyncio
from decimal import Decimal

import pytest

from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent


@pytest.mark.asyncio
@pytest.mark.integration
async def test_scanner_detects_live_opportunities() -> None:
    """Scanner should process live data and detect opportunities when configured."""
    redis_url = "redis://localhost:6379"

    # Create adapters
    binance = BinanceOracle()
    polymarket = PolymarketAdapter()

    # Create data-producing agents
    oracle_agent = OracleAgent(redis_url, binance, symbols=["BTC", "ETH"], poll_interval=1.0)
    venue_agent = VenueWatcherAgent(redis_url, polymarket, poll_interval=2.0)

    # Create scanner
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC", "oracle.binance.ETH"],
        min_edge_pct=Decimal("0.01"),
        min_signal_strength=Decimal("0.1"),
    )

    # Register a test mapping (hypothetical - real markets would need actual IDs)
    # This tests that the scanner receives and processes data correctly
    scanner.register_market_oracle_mapping(
        market_id="polymarket:test-btc-market",
        oracle_symbol="BTC",
        threshold=Decimal("50000"),  # Low threshold so BTC is always above
        direction="above",
    )

    # Track received data
    venue_prices_received = []
    oracle_data_received = []
    opportunities_detected = []

    # Patch handlers to capture data
    original_venue_handler = scanner._handle_venue_price
    original_oracle_handler = scanner._handle_oracle_data
    original_publish = scanner._publish_opportunity

    async def capture_venue(channel, data):
        venue_prices_received.append(data)
        await original_venue_handler(channel, data)

    async def capture_oracle(channel, data):
        oracle_data_received.append(data)
        await original_oracle_handler(channel, data)

    async def capture_opportunity(opp):
        opportunities_detected.append(opp)
        # Don't actually publish in test

    scanner._handle_venue_price = capture_venue  # type: ignore[method-assign]
    scanner._handle_oracle_data = capture_oracle  # type: ignore[method-assign]
    scanner._publish_opportunity = capture_opportunity  # type: ignore[method-assign]

    # Start all agents
    oracle_task = asyncio.create_task(oracle_agent.run())
    venue_task = asyncio.create_task(venue_agent.run())
    scanner_task = asyncio.create_task(scanner.run())

    # Let them run
    await asyncio.sleep(5)

    # Stop agents
    await oracle_agent.stop()
    await venue_agent.stop()
    await scanner.stop()

    await asyncio.gather(oracle_task, venue_task, scanner_task, return_exceptions=True)

    # Verify data flow
    print(f"\nOracle data received: {len(oracle_data_received)}")
    print(f"Venue prices received: {len(venue_prices_received)}")
    print(f"Opportunities detected: {len(opportunities_detected)}")

    # Should have received oracle data (Binance is reliable)
    assert len(oracle_data_received) > 0, "Should receive BTC/ETH prices from Binance"

    # Venue data is optional (Polymarket may rate limit)
    # Opportunities depend on configured market IDs matching actual data
```

**Step 2: Run integration test (requires Redis + internet)**

Run: `pytest tests/integration/test_sprint3.py -v -m integration`
Expected: PASS with data counts printed

**Step 3: Commit**

```bash
git add tests/integration/test_sprint3.py
git commit -m "test: add Sprint 3 integration test - opportunity scanner"
```

---

## Task 3.6: Sprint 3 Final Commit

**Step 1: Run all tests**

Run: `pytest tests/ -v --ignore=tests/integration/test_sprint3.py`
Expected: All pass

**Step 2: Lint and type check**

Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`
Run: `mypy src/`
Expected: Clean

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: Sprint 3 complete - Opportunity Scanner agent"
```

---

## Sprint 3 Complete

**Demo steps:**
1. `docker-compose up -d` (Redis)
2. `pytest tests/integration/test_sprint3.py -v -m integration`
3. See BTC/ETH prices received, scanner processing data

**What we built:**
- OpportunityScannerAgent with configurable thresholds
- Oracle-based opportunity detection (PM price vs real-world data)
- Cross-platform opportunity detection (price discrepancies between venues)
- Signal strength calculation based on edge magnitude
- Integration test demonstrating data flow

**Next: Sprint 4 - Risk Guardian + Paper Executor**
