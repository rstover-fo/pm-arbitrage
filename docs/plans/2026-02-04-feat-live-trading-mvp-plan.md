---
title: "feat: Live Trading MVP"
type: feat
date: 2026-02-04
brainstorm: docs/brainstorms/2026-02-03-live-trading-mvp-brainstorm.md
---

# Live Trading MVP

## Overview

Replace paper trading executor with a live executor that places real Polymarket orders. The system architecture remains unchanged—same opportunity scanner, risk guardian, and message bus. The only difference is trades execute for real money.

**Capital**: $100-500 micro stakes
**Venue**: Polymarket only
**Target**: Validate oracle lag arbitrage thesis with real money

## Problem Statement

Paper trading has validated the architecture end-to-end. Now we need to prove the oracle lag arbitrage strategy works with real capital. The system is currently blocked from live trading by:

1. **Channel mismatch bug**: LiveExecutor subscribes to wrong Redis channel
2. **Missing token_id resolution**: Polymarket API requires token_id, not market_id
3. **No fee-aware edge calculation**: 15-min crypto markets charge up to 1.56% taker fee
4. **No alerting**: Operator has no visibility into live system health

## Proposed Solution

Fix the critical bugs and implement minimal live trading infrastructure:

1. Align message channels between RiskGuardian and LiveExecutor
2. Add token_id resolution from market_id + outcome
3. Implement fee-aware net edge calculation in OpportunityScanner
4. Create AlertService for critical notifications via Pushover
5. Add paper/live mode switch in PilotOrchestrator
6. Add live trade persistence

## Technical Considerations

### Architecture

```
OpportunityScanner
  └─[net edge ≥ 2%]→ opportunities.detected

OracleSniperStrategy
  └─→ trade.requests

RiskGuardianAgent
  └─→ trade.decisions (approved: true/false)

LiveExecutorAgent  ← FIX: subscribe to trade.decisions
  ├─ Resolve token_id from market_id + outcome
  ├─ Place order via PolymarketAdapter
  ├─ Persist to live_trades table
  └─→ trade.results

AlertService
  ├─ Trade confirmations (Normal priority)
  ├─ Trade failures (High priority)
  └─ System halt (Critical priority)
```

### Security

- Private keys loaded from environment variables only
- Credentials validated on startup (fail fast)
- Position limits enforced by RiskGuardian (unchanged)
- Manual kill switch via `pm-arb stop`

### Performance

- Fee calculation adds minimal overhead (<1ms per opportunity)
- Token_id caching avoids repeated API calls
- Same polling intervals as paper trading

## Acceptance Criteria

### Phase 1: Fix Critical Bugs

- [x] ~~Tests passing (from Sprint 9)~~ (177/177 passing)
- [x] Fix LiveExecutor channel subscription (`trade.decisions`, `trade.requests`)
- [x] Add token_id to trade request data flow
- [x] Verify end-to-end message flow with integration test

### Phase 2: Fee-Aware Edge Calculation

- [x] Create fee calculation logic with 15-min crypto market formula (inline in scanner)
- [x] Add `_is_fee_market(market)` detection
- [x] Modify OpportunityScanner to calculate net edge (`_calculate_net_edge`)
- [x] Only emit opportunities with net edge ≥ min threshold
- [x] Add tests for fee calculation (10 new tests)

### Phase 3: AlertService

- [x] Create `AlertService` wrapping Pushover API
- [x] Implement alert types: trade_executed, trade_failed, agent_crash, agent_dead, drawdown_halt
- [x] Integrate with LiveExecutor for trade events
- [x] Integrate with PilotOrchestrator for agent crash events
- [x] Test alert delivery (alerts disabled without credentials)

### Phase 4: Live Trade Infrastructure

- [x] Create `live_trades` database table (extend paper_trades schema)
- [x] Add token_id resolution in PolymarketAdapter (`get_token_id` method)
- [x] Add balance pre-check before order placement in LiveExecutor
- [x] Add paper/live mode switch to PilotOrchestrator config
- [x] Wire LiveExecutor persistence (reuses PaperTradeRepository)

### Phase 5: Manual Validation

- [ ] Generate/verify Polymarket API credentials
- [ ] Place $1 manual test trade via CLI
- [ ] Run 10-minute live dry-run with $10 max position
- [ ] Verify positions match Polymarket UI
- [ ] Verify alerts received on phone

## Success Metrics

1. First live trade executes successfully on Polymarket
2. Position tracking matches actual Polymarket holdings
3. Net P&L reflects real gains/losses after fees
4. Alerts arrive within 30 seconds of events
5. System runs 30+ minutes without operator intervention

## Dependencies & Risks

### Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| Polymarket API credentials | Pending | Need to generate via py-clob-client |
| Pushover account | Configured | Keys in settings |
| USDC.e balance on Polygon | Pending | Need to fund wallet |
| Redis + PostgreSQL | Running | Same as paper trading |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Credential misconfiguration | Medium | High | Validate on startup, fail fast |
| Fee calculation error | Medium | Medium | Conservative threshold (2% net) |
| Rate limiting | Low | Medium | Existing limits are adequate |
| Unexpected API behavior | Medium | High | Start with $10 trades, manual monitoring |

## Implementation Tasks

### Task 1: Fix LiveExecutor Channel Mismatch

**File**: `src/pm_arb/agents/live_executor.py:29-31`

```python
# BEFORE
def get_subscriptions(self) -> list[str]:
    return ["trade.approved"]

# AFTER
def get_subscriptions(self) -> list[str]:
    return ["trade.decisions", "trade.requests"]
```

Also update `handle_message()` to match PaperExecutor pattern.

---

### Task 2: Add token_id Resolution

**File**: `src/pm_arb/adapters/venues/polymarket.py`

Add method to resolve market_id + outcome → token_id:

```python
async def get_token_id(self, market_id: str, outcome: str) -> str:
    """Resolve token_id from market condition ID and outcome (YES/NO)."""
    # market_id format: "polymarket:{condition_id}"
    condition_id = market_id.split(":")[1]

    # Fetch from Gamma API or cache
    # clobTokenIds format: "YES_token_id,NO_token_id"
    ...
```

**File**: `src/pm_arb/agents/live_executor.py`

Add token_id resolution before order placement:

```python
async def _execute_trade(self, request: dict, decision: dict) -> None:
    market_id = request["market_id"]
    outcome = request["outcome"]

    # Resolve token_id if not provided
    token_id = request.get("token_id")
    if not token_id:
        adapter = self._get_adapter(market_id)
        token_id = await adapter.get_token_id(market_id, outcome)
    ...
```

---

### Task 3: Implement Fee Calculator

**File**: `src/pm_arb/core/fees.py` (new)

```python
from decimal import Decimal

class FeeCalculator:
    """Calculate trading fees for Polymarket markets."""

    # 15-minute crypto markets have probability-based taker fees
    CRYPTO_15MIN_KEYWORDS = ["15 minute", "15-minute", "15min"]
    CRYPTO_SYMBOLS = ["BTC", "ETH", "SOL", "XRP"]

    @classmethod
    def is_15min_crypto_market(cls, title: str) -> bool:
        """Check if market is a 15-minute crypto market with taker fees."""
        title_lower = title.lower()
        has_15min = any(kw in title_lower for kw in cls.CRYPTO_15MIN_KEYWORDS)
        has_crypto = any(sym.lower() in title_lower for sym in cls.CRYPTO_SYMBOLS)
        return has_15min and has_crypto

    @classmethod
    def calculate_taker_fee(cls, price: Decimal, is_15min_crypto: bool) -> Decimal:
        """Calculate taker fee rate.

        15-min crypto: fee_rate = 0.0312 * (0.5 - abs(price - 0.5))
        Other markets: 0%
        """
        if not is_15min_crypto:
            return Decimal("0")

        distance = abs(price - Decimal("0.5"))
        fee_rate = Decimal("0.0312") * (Decimal("0.5") - distance)
        return max(fee_rate, Decimal("0"))

    @classmethod
    def calculate_net_edge(
        cls,
        gross_edge: Decimal,
        price: Decimal,
        is_15min_crypto: bool
    ) -> Decimal:
        """Calculate net edge after fees."""
        fee_rate = cls.calculate_taker_fee(price, is_15min_crypto)
        return gross_edge - fee_rate
```

---

### Task 4: Update OpportunityScanner for Net Edge

**File**: `src/pm_arb/agents/opportunity_scanner.py`

Import and use FeeCalculator:

```python
from pm_arb.core.fees import FeeCalculator

# In _check_oracle_lag() around line 198:
gross_edge = fair_yes_price - current_yes

# Calculate net edge accounting for fees
is_15min = FeeCalculator.is_15min_crypto_market(market.title)
net_edge = FeeCalculator.calculate_net_edge(abs(gross_edge), current_yes, is_15min)

if net_edge < self._min_edge_pct:
    return  # Not enough edge after fees
```

---

### Task 5: Create AlertService

**File**: `src/pm_arb/core/alerts.py` (new)

```python
import httpx
import structlog
from enum import IntEnum
from pm_arb.core.config import settings

logger = structlog.get_logger()

class AlertPriority(IntEnum):
    LOWEST = -2
    LOW = -1
    NORMAL = 0
    HIGH = 1
    CRITICAL = 2  # Bypass quiet hours

class AlertService:
    """Send alerts via Pushover."""

    PUSHOVER_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self) -> None:
        self._user_key = settings.pushover_user_key
        self._api_token = settings.pushover_api_token
        self._enabled = bool(self._user_key and self._api_token)

        if not self._enabled:
            logger.warning("alert_service_disabled", reason="missing credentials")

    async def send(
        self,
        title: str,
        message: str,
        priority: AlertPriority = AlertPriority.NORMAL
    ) -> bool:
        """Send alert. Returns True if delivered."""
        if not self._enabled:
            logger.info("alert_skipped", title=title)
            return False

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.PUSHOVER_URL,
                data={
                    "token": self._api_token,
                    "user": self._user_key,
                    "title": title,
                    "message": message,
                    "priority": priority.value,
                },
            )

        success = response.status_code == 200
        logger.info("alert_sent", title=title, priority=priority.name, success=success)
        return success

    # Convenience methods
    async def trade_confirmed(self, trade_id: str, market: str, amount: str, pnl: str) -> bool:
        return await self.send(
            "Trade Executed",
            f"{trade_id}: {amount} on {market}\nP&L: {pnl}",
            AlertPriority.NORMAL,
        )

    async def trade_failed(self, trade_id: str, error: str) -> bool:
        return await self.send(
            "Trade Failed",
            f"{trade_id}: {error}",
            AlertPriority.HIGH,
        )

    async def system_halt(self, reason: str) -> bool:
        return await self.send(
            "SYSTEM HALTED",
            f"Trading stopped: {reason}",
            AlertPriority.CRITICAL,
        )
```

---

### Task 6: Create Live Trades Table

**File**: `src/pm_arb/db/schema.sql`

```sql
-- Live trades table (extends paper_trades with order details)
CREATE TABLE IF NOT EXISTS live_trades (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(64) UNIQUE NOT NULL,
    request_id VARCHAR(64) NOT NULL,
    opportunity_id VARCHAR(64) NOT NULL,
    opportunity_type VARCHAR(32),

    -- Order details
    market_id VARCHAR(128) NOT NULL,
    token_id VARCHAR(128) NOT NULL,
    side VARCHAR(10) NOT NULL,
    outcome VARCHAR(10) NOT NULL,

    -- Requested
    requested_amount DECIMAL(18,8) NOT NULL,
    max_price DECIMAL(18,8) NOT NULL,
    expected_edge DECIMAL(18,8),
    expected_fee DECIMAL(18,8),

    -- Actual
    filled_amount DECIMAL(18,8),
    fill_price DECIMAL(18,8),
    order_id VARCHAR(128),

    -- Status
    status VARCHAR(20) NOT NULL,  -- pending, filled, partial, failed, cancelled
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ,

    -- Strategy
    strategy VARCHAR(64)
);

CREATE INDEX idx_live_trades_market ON live_trades(market_id);
CREATE INDEX idx_live_trades_status ON live_trades(status);
CREATE INDEX idx_live_trades_created ON live_trades(created_at);
```

---

### Task 7: Add Paper/Live Mode Switch

**File**: `src/pm_arb/core/config.py`

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Trading mode
    paper_trading: bool = True  # Default to paper for safety
```

**File**: `src/pm_arb/pilot.py`

```python
from pm_arb.core.config import settings

async def _create_agents(self) -> list[BaseAgent]:
    agents = [
        VenueWatcherAgent(...),
        OracleAgent(...),
        scanner,
        RiskGuardianAgent(self._redis_url),
    ]

    # Choose executor based on mode
    if settings.paper_trading:
        agents.append(PaperExecutorAgent(self._redis_url, db_pool=self._db_pool))
        logger.info("executor_mode", mode="paper")
    else:
        credentials = load_credentials("polymarket")
        agents.append(LiveExecutorAgent(self._redis_url, credentials={"polymarket": credentials}))
        logger.info("executor_mode", mode="live")

    agents.extend([
        OracleSniperStrategy(self._redis_url),
        CapitalAllocatorAgent(self._redis_url),
    ])

    return agents
```

---

### Task 8: Add Balance Pre-Check

**File**: `src/pm_arb/agents/live_executor.py`

```python
async def _execute_trade(self, request: dict, decision: dict) -> None:
    adapter = self._get_adapter(request["market_id"])

    # Pre-check balance
    balance = await adapter.get_balance()
    amount = Decimal(request["amount"])

    if balance < amount:
        logger.error(
            "insufficient_balance",
            required=str(amount),
            available=str(balance),
        )
        await self._alert_service.trade_failed(
            request["id"],
            f"Insufficient balance: {balance} < {amount}",
        )
        return

    # Proceed with order placement
    ...
```

---

## Testing Requirements

### Unit Tests

```python
# tests/test_fees.py
def test_15min_crypto_detection():
    assert FeeCalculator.is_15min_crypto_market("Will BTC be above $100k in 15 minutes?")
    assert not FeeCalculator.is_15min_crypto_market("Will BTC hit $100k by end of week?")

def test_fee_calculation():
    # Max fee at 50%
    assert FeeCalculator.calculate_taker_fee(Decimal("0.50"), True) == Decimal("0.0156")
    # Lower fee at extremes
    assert FeeCalculator.calculate_taker_fee(Decimal("0.80"), True) < Decimal("0.01")
    # Zero fee for non-15min
    assert FeeCalculator.calculate_taker_fee(Decimal("0.50"), False) == Decimal("0")

def test_net_edge_calculation():
    # 5% gross edge, 1.56% fee = 3.44% net
    net = FeeCalculator.calculate_net_edge(Decimal("0.05"), Decimal("0.50"), True)
    assert net == Decimal("0.0344")
```

### Integration Tests

```python
# tests/integration/test_live_executor.py
@pytest.mark.integration
async def test_live_executor_receives_decisions():
    """Verify LiveExecutor subscribes to correct channel."""
    executor = LiveExecutorAgent(redis_url, credentials={})
    assert "trade.decisions" in executor.get_subscriptions()
    assert "trade.requests" in executor.get_subscriptions()

@pytest.mark.integration
async def test_token_id_resolution():
    """Verify token_id can be resolved from market_id."""
    adapter = PolymarketAdapter()
    await adapter.connect()

    # Use a known active market
    token_id = await adapter.get_token_id("polymarket:0x123...", "YES")
    assert token_id is not None
    assert len(token_id) > 0
```

---

## References & Research

### Internal References

- Brainstorm: [docs/brainstorms/2026-02-03-live-trading-mvp-brainstorm.md](../brainstorms/2026-02-03-live-trading-mvp-brainstorm.md)
- PaperExecutorAgent: [src/pm_arb/agents/paper_executor.py:18-186](../../src/pm_arb/agents/paper_executor.py)
- LiveExecutorAgent: [src/pm_arb/agents/live_executor.py:16-95](../../src/pm_arb/agents/live_executor.py)
- PolymarketAdapter: [src/pm_arb/adapters/venues/polymarket.py:297-383](../../src/pm_arb/adapters/venues/polymarket.py)
- RiskGuardianAgent: [src/pm_arb/agents/risk_guardian.py:190-209](../../src/pm_arb/agents/risk_guardian.py)
- OpportunityScanner: [src/pm_arb/agents/opportunity_scanner.py:161-228](../../src/pm_arb/agents/opportunity_scanner.py)

### External References

- [Polymarket CLOB Authentication](https://docs.polymarket.com/developers/CLOB/authentication)
- [Polymarket Order Placement](https://docs.polymarket.com/developers/CLOB/orders/create-order)
- [Polymarket Rate Limits](https://docs.polymarket.com/quickstart/introduction/rate-limits)
- [py-clob-client GitHub](https://github.com/Polymarket/py-clob-client)
- [Pushover API](https://pushover.net/api)

### Institutional Learnings

- **Defensive Decimal Parsing**: Always use `_safe_decimal()` for API responses ([paper-trading-pilot-api-integration-fixes.md](../solutions/integration-issues/paper-trading-pilot-api-integration-fixes.md))
- **Symbol Format Validation**: Validate format before API calls
- **Rate Limiting**: Implement exponential backoff on 429 responses
- **Auth Re-derive**: On 401, call `create_or_derive_api_creds()` and retry
