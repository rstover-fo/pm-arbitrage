---
title: "feat: Live Trading MVP"
type: feat
date: 2026-02-03
status: ready
estimated_effort: 2-3 days
---

# Live Trading MVP

Replace paper trading executor with real Polymarket order placement while maintaining the existing system architecture.

## Overview

This plan implements a **Minimal Viable Live Executor** that swaps the paper trading simulation with real Polymarket API calls. The system architecture remains unchanged—same opportunity scanner, risk guardian, and message bus. The only difference is trades execute for real.

### Scope

| In Scope | Out of Scope |
|----------|--------------|
| LiveExecutorAgent integration | Kalshi support |
| Fee-aware edge calculation | Advanced order lifecycle |
| AlertService (Pushover) | Position reconciliation system |
| Credential workflow | Shadow/testnet mode |
| CLI kill switch | Auto-retry on failure |
| Startup validation | Kelly position sizing |

### Key Constraints

- **Capital:** $100-500 total, $10-20 per trade
- **Venue:** Polymarket only
- **Auth:** Wallet signing required (py-clob-client handles this)
- **Rollback:** Manual only
- **Deployment:** Local initially

## Technical Approach

### Architecture

The system uses a message-bus architecture with Redis Streams. Currently:

```
VenueWatcher → OpportunityScanner → Strategy → RiskGuardian → PaperExecutor
     ↓              ↓                                              ↓
   prices      opportunities                                  trade.results
```

After this change:

```
VenueWatcher → OpportunityScanner → Strategy → RiskGuardian → LiveExecutor
     ↓              ↓                   ↓              ↓            ↓
   prices      opportunities      requests      decisions    trade.results
     |                                                             ↓
     +-------------- fee-aware edge calc -----------------------> AlertService
```

### Key Integration Points

| Component | File | Changes Needed |
|-----------|------|----------------|
| Config | [config.py](src/pm_arb/core/config.py) | Add credential env vars |
| Pilot | [pilot.py](src/pm_arb/pilot.py) | Switch executor based on config |
| LiveExecutor | [live_executor.py](src/pm_arb/agents/live_executor.py) | Fix channel subscription, add persistence |
| Scanner | [opportunity_scanner.py](src/pm_arb/agents/opportunity_scanner.py) | Fee-aware edge calculation |
| Polymarket | [polymarket.py](src/pm_arb/adapters/venues/polymarket.py) | Fetch token IDs with markets |
| CLI | [cli.py](src/pm_arb/cli.py) | Add `stop` command |
| AlertService | NEW: `src/pm_arb/core/alerts.py` | Pushover integration |

## Implementation Phases

### Phase 1: Critical Fixes (Blockers)

These issues prevent any live trading from working.

#### Task 1.1: Fix Message Channel Subscription

**File:** [src/pm_arb/agents/live_executor.py](src/pm_arb/agents/live_executor.py)

**Problem:** LiveExecutorAgent subscribes to `trade.approved` but RiskGuardian publishes to `trade.decisions`.

**Solution:**
```python
def get_subscriptions(self) -> list[str]:
    return ["trade.decisions", "trade.requests"]  # Match paper executor

async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
    if channel == "trade.requests":
        request_id = data.get("id", "")
        if request_id:
            self._pending_requests[request_id] = data
    elif channel == "trade.decisions":
        if data.get("approved", False):
            await self._execute_trade(data)
```

**Acceptance Criteria:**
- [ ] LiveExecutor subscribes to same channels as PaperExecutor
- [ ] Only executes trades when `approved=True`
- [ ] Test: Mock message with `approved=False` does not trigger execution

---

#### Task 1.2: Add Token ID to Market Data Flow

**Files:**
- [src/pm_arb/adapters/venues/polymarket.py](src/pm_arb/adapters/venues/polymarket.py)
- [src/pm_arb/core/models.py](src/pm_arb/core/models.py)

**Problem:** Orders require `token_id` but current Market model only has `external_id`.

**Solution:**

1. Extend Market model:
```python
class Market(BaseModel):
    # ... existing fields ...
    yes_token_id: str = ""  # CLOB token for YES outcome
    no_token_id: str = ""   # CLOB token for NO outcome
```

2. Fetch token IDs in adapter:
```python
async def _fetch_markets(self) -> list[dict[str, Any]]:
    # Existing gamma-api call for market metadata
    response = await self._client.get(f"{GAMMA_API}/markets", ...)

    # CLOB API provides token IDs via /markets endpoint
    # clobTokenIds field contains [yes_token, no_token]
    ...
```

3. Include in trade request:
```python
# In strategy/opportunity flow
trade_request = {
    "market_id": market.id,
    "token_id": market.yes_token_id if side == "buy_yes" else market.no_token_id,
    ...
}
```

**Acceptance Criteria:**
- [ ] Market model includes `yes_token_id` and `no_token_id`
- [ ] PolymarketAdapter populates token IDs when fetching markets
- [ ] Trade requests include correct `token_id` for outcome being traded
- [ ] Test: Market with known token IDs returns correct values

---

#### Task 1.3: Wire LiveExecutor into Pilot

**File:** [src/pm_arb/pilot.py](src/pm_arb/pilot.py)

**Problem:** Pilot always creates PaperExecutorAgent regardless of config.

**Solution:**
```python
from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.core.auth import load_credentials

async def _create_agents(self) -> list[BaseAgent]:
    # ... existing code ...

    # Choose executor based on config
    if settings.paper_trading:
        executor = PaperExecutorAgent(self._redis_url, db_pool=self._db_pool)
    else:
        # Load and validate credentials for live trading
        credentials = {"polymarket": load_credentials("polymarket")}
        executor = LiveExecutorAgent(
            self._redis_url,
            credentials=credentials,
            db_pool=self._db_pool,
        )

    return [
        # ... other agents ...
        executor,
        # ...
    ]
```

**Acceptance Criteria:**
- [ ] `paper_trading=True` creates PaperExecutorAgent
- [ ] `paper_trading=False` creates LiveExecutorAgent with credentials
- [ ] Missing credentials in live mode raises clear error at startup
- [ ] Test: Config toggle switches executor type

---

#### Task 1.4: Add Startup Validation for Live Mode

**File:** [src/pm_arb/pilot.py](src/pm_arb/pilot.py)

**Problem:** No validation that credentials exist and work before attempting trades.

**Solution:**
```python
async def _validate_live_mode(self) -> None:
    """Validate system is ready for live trading."""
    if settings.paper_trading:
        return  # Skip validation for paper mode

    # 1. Check credentials exist
    try:
        creds = load_credentials("polymarket")
    except ValueError as e:
        raise RuntimeError(f"Live mode requires credentials: {e}")

    # 2. Test API connection
    adapter = PolymarketAdapter(credentials=creds)
    await adapter.connect()

    if not adapter.is_authenticated:
        raise RuntimeError("Failed to authenticate with Polymarket")

    # 3. Check wallet balance
    balance = await adapter.get_balance()
    min_balance = Decimal(str(settings.initial_bankroll))

    if balance < min_balance:
        raise RuntimeError(
            f"Insufficient balance: ${balance} < ${min_balance} required"
        )

    logger.info(
        "live_mode_validated",
        balance=str(balance),
        bankroll=str(min_balance),
    )

    await adapter.disconnect()
```

**Acceptance Criteria:**
- [ ] Missing credentials fails fast with clear error
- [ ] Invalid credentials (auth failure) fails fast
- [ ] Insufficient balance fails fast with amounts shown
- [ ] Successful validation logs balance and bankroll
- [ ] Test: Each failure mode produces expected error

---

### Phase 2: Fee-Aware Edge Calculation

#### Task 2.1: Detect 15-Minute Crypto Markets

**File:** [src/pm_arb/agents/opportunity_scanner.py](src/pm_arb/agents/opportunity_scanner.py)

**Problem:** No way to identify markets subject to taker fees.

**Solution:**
```python
CRYPTO_KEYWORDS = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "xrp"]
DURATION_PATTERNS = [r"15\s*min", r"15-min", r"fifteen\s*min"]

def _is_fee_market(self, market: Market) -> bool:
    """Check if market has taker fees (15-min crypto markets)."""
    title_lower = market.title.lower()

    # Must be crypto-related
    is_crypto = any(kw in title_lower for kw in CRYPTO_KEYWORDS)
    if not is_crypto:
        return False

    # Must be 15-minute duration
    import re
    is_15min = any(re.search(p, title_lower) for p in DURATION_PATTERNS)

    return is_15min
```

**Acceptance Criteria:**
- [ ] "BTC 15 min up" detected as fee market
- [ ] "BTC above $100k by Jan 1" NOT detected as fee market
- [ ] "Will Trump win?" NOT detected as fee market
- [ ] Test: Various market titles correctly classified

---

#### Task 2.2: Calculate Net Edge After Fees

**File:** [src/pm_arb/agents/opportunity_scanner.py](src/pm_arb/agents/opportunity_scanner.py)

**Problem:** Edge calculation ignores taker fees, leading to unprofitable trades.

**Fee Formula (from Polymarket docs):**
```
fee_rate = 0.0312 * (0.5 - abs(price - 0.5))
# Max 1.56% at 50¢, 0% at 0¢ or $1
```

**Solution:**
```python
def _calculate_taker_fee(self, price: Decimal) -> Decimal:
    """Calculate expected taker fee rate for 15-min crypto markets."""
    # Fee is highest at 50% probability, zero at 0% or 100%
    distance_from_edge = Decimal("0.5") - abs(price - Decimal("0.5"))
    fee_rate = Decimal("0.0312") * distance_from_edge
    return fee_rate

def _calculate_net_edge(
    self,
    gross_edge: Decimal,
    market: Market,
    entry_price: Decimal,
) -> Decimal:
    """Calculate edge after accounting for fees."""
    if self._is_fee_market(market):
        fee_rate = self._calculate_taker_fee(entry_price)
        return gross_edge - fee_rate
    return gross_edge  # No fees on non-15-min markets

# Update _check_oracle_lag to use net edge:
async def _check_oracle_lag(self, market, oracle_data, threshold_info):
    # ... existing edge calculation ...
    gross_edge = fair_yes_price - current_yes
    net_edge = self._calculate_net_edge(gross_edge, market, current_yes)

    if abs(net_edge) < self._min_edge_pct:
        return  # Not enough edge after fees

    # Use net_edge in opportunity
    opportunity = Opportunity(
        expected_edge=net_edge,
        metadata={
            "gross_edge": str(gross_edge),
            "fee_rate": str(self._calculate_taker_fee(current_yes)) if self._is_fee_market(market) else "0",
            ...
        }
    )
```

**Acceptance Criteria:**
- [ ] 50¢ price → 1.56% fee rate
- [ ] 90¢ price → ~0.31% fee rate
- [ ] Non-fee markets → 0% fee rate
- [ ] Opportunities include both gross and net edge in metadata
- [ ] Test: Fee calculation matches expected values

---

### Phase 3: AlertService

#### Task 3.1: Create Pushover AlertService

**File:** NEW: `src/pm_arb/core/alerts.py`

**Implementation:**
```python
"""Alert service for trade notifications via Pushover."""

from enum import Enum
from typing import Any

import httpx
import structlog

from pm_arb.core.config import settings

logger = structlog.get_logger()

PUSHOVER_API = "https://api.pushover.net/1/messages.json"


class AlertPriority(Enum):
    LOW = -1      # Quiet hours respected
    NORMAL = 0    # Standard notification
    HIGH = 1      # Bypasses quiet hours
    CRITICAL = 2  # Requires acknowledgment


class AlertService:
    """Send alerts via Pushover."""

    def __init__(
        self,
        user_key: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self._user_key = user_key or settings.pushover_user_key
        self._api_token = api_token or settings.pushover_api_token
        self._enabled = bool(self._user_key and self._api_token)

        if not self._enabled:
            logger.warning("alerts_disabled", reason="Missing Pushover credentials")

    async def send(
        self,
        title: str,
        message: str,
        priority: AlertPriority = AlertPriority.NORMAL,
        url: str | None = None,
    ) -> bool:
        """Send an alert notification."""
        if not self._enabled:
            logger.debug("alert_skipped", title=title)
            return False

        payload = {
            "token": self._api_token,
            "user": self._user_key,
            "title": title,
            "message": message,
            "priority": priority.value,
        }

        if url:
            payload["url"] = url

        # Critical alerts require retry/expire params
        if priority == AlertPriority.CRITICAL:
            payload["retry"] = 60  # Retry every 60s
            payload["expire"] = 3600  # For 1 hour

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(PUSHOVER_API, data=payload)
                response.raise_for_status()
                logger.info("alert_sent", title=title, priority=priority.name)
                return True
        except Exception as e:
            logger.error("alert_failed", title=title, error=str(e))
            return False

    # Convenience methods
    async def trade_executed(
        self,
        market: str,
        side: str,
        amount: str,
        price: str,
        pnl: str | None = None,
    ) -> bool:
        """Alert for successful trade execution."""
        msg = f"{side.upper()} ${amount} @ {price}"
        if pnl:
            msg += f"\nP&L: {pnl}"
        return await self.send(
            title=f"Trade: {market[:30]}",
            message=msg,
            priority=AlertPriority.NORMAL,
        )

    async def trade_failed(self, market: str, error: str) -> bool:
        """Alert for failed trade."""
        return await self.send(
            title="Trade FAILED",
            message=f"{market[:30]}\n{error}",
            priority=AlertPriority.HIGH,
        )

    async def agent_crash(self, agent_name: str, error: str) -> bool:
        """Alert for agent crash."""
        return await self.send(
            title=f"CRASH: {agent_name}",
            message=error[:200],
            priority=AlertPriority.CRITICAL,
        )

    async def drawdown_halt(self, current_value: str, limit: str) -> bool:
        """Alert for drawdown halt."""
        return await self.send(
            title="TRADING HALTED",
            message=f"Drawdown limit exceeded\nValue: {current_value}\nLimit: {limit}",
            priority=AlertPriority.CRITICAL,
        )

    async def daily_summary(
        self,
        trades: int,
        pnl: str,
        positions: int,
    ) -> bool:
        """Daily summary alert."""
        return await self.send(
            title="Daily Summary",
            message=f"Trades: {trades}\nP&L: {pnl}\nOpen positions: {positions}",
            priority=AlertPriority.LOW,
        )
```

**Acceptance Criteria:**
- [ ] AlertService sends to Pushover when credentials configured
- [ ] Missing credentials disables alerts (no crash)
- [ ] Priority levels map to Pushover correctly
- [ ] Critical alerts include retry/expire
- [ ] Test: Mock Pushover API receives correct payload

---

#### Task 3.2: Integrate Alerts into LiveExecutor

**File:** [src/pm_arb/agents/live_executor.py](src/pm_arb/agents/live_executor.py)

**Solution:**
```python
from pm_arb.core.alerts import AlertService

class LiveExecutorAgent(BaseAgent):
    def __init__(self, ...):
        # ... existing init ...
        self._alerts = AlertService()

    async def _execute_trade(self, data: dict[str, Any]) -> None:
        # ... existing execution ...

        if order.status in (OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED):
            await self._alerts.trade_executed(
                market=market_id,
                side=side.value,
                amount=str(amount),
                price=str(order.average_price or "market"),
            )
        elif order.status == OrderStatus.REJECTED:
            await self._alerts.trade_failed(
                market=market_id,
                error=order.error_message or "Unknown error",
            )
```

**Acceptance Criteria:**
- [ ] Successful trades trigger normal-priority alert
- [ ] Failed trades trigger high-priority alert
- [ ] Alerts include market, side, amount, price

---

#### Task 3.3: Integrate Alerts into Pilot (Crashes)

**File:** [src/pm_arb/pilot.py](src/pm_arb/pilot.py)

**Solution:**
```python
from pm_arb.core.alerts import AlertService

class PilotOrchestrator:
    def __init__(self, ...):
        # ... existing init ...
        self._alerts = AlertService()

    async def _start_agent(self, agent: BaseAgent) -> None:
        async def run_with_restart() -> None:
            # ... existing restart logic ...
            except Exception as e:
                failures += 1
                logger.error("agent_crashed", ...)

                # Alert on crash
                await self._alerts.agent_crash(
                    agent_name=agent.name,
                    error=str(e),
                )

                if failures >= max_failures:
                    await self._alerts.send(
                        title=f"AGENT DEAD: {agent.name}",
                        message=f"Max restarts ({max_failures}) exceeded",
                        priority=AlertPriority.CRITICAL,
                    )
```

**Acceptance Criteria:**
- [ ] Agent crash triggers critical alert
- [ ] Max failures triggers separate critical alert
- [ ] Error message included in alert body

---

### Phase 4: CLI Kill Switch

#### Task 4.1: Implement `pm-arb stop` Command

**File:** [src/pm_arb/cli.py](src/pm_arb/cli.py)

**Implementation:**
```python
import os
import signal

@cli.command()
def stop() -> None:
    """Stop the running pilot gracefully."""
    pid_file = Path.home() / ".pm-arb" / "pilot.pid"

    if not pid_file.exists():
        click.echo("No running pilot found (pid file missing)")
        return

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to pilot (PID {pid})")

        # Wait for process to exit
        import time
        for _ in range(30):  # 30 second timeout
            try:
                os.kill(pid, 0)  # Check if process exists
                time.sleep(1)
            except ProcessLookupError:
                click.echo("Pilot stopped successfully")
                pid_file.unlink(missing_ok=True)
                return

        click.echo("Warning: Pilot did not stop within 30 seconds")
    except ProcessLookupError:
        click.echo("Pilot process not found (may have already stopped)")
        pid_file.unlink(missing_ok=True)
    except Exception as e:
        click.echo(f"Error stopping pilot: {e}")
```

**Also update pilot to write PID file:**
```python
# In pilot.py main()
async def main() -> None:
    # Write PID file
    pid_file = Path.home() / ".pm-arb" / "pilot.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))

    try:
        # ... existing run logic ...
    finally:
        pid_file.unlink(missing_ok=True)
```

**Acceptance Criteria:**
- [ ] `pm-arb stop` sends SIGTERM to running pilot
- [ ] Command reports success/failure
- [ ] Works when no pilot running (graceful error)
- [ ] PID file cleaned up on stop

---

### Phase 5: Database Persistence for Live Trades

#### Task 5.1: Add Trade Persistence to LiveExecutor

**File:** [src/pm_arb/agents/live_executor.py](src/pm_arb/agents/live_executor.py)

**Problem:** LiveExecutor doesn't persist trades like PaperExecutor does.

**Solution:** Add repository and persistence logic mirroring PaperExecutor:

```python
class LiveExecutorAgent(BaseAgent):
    def __init__(
        self,
        redis_url: str,
        credentials: dict[str, PolymarketCredentials],
        db_pool: asyncpg.Pool | None = None,
    ) -> None:
        # ... existing init ...
        self._db_pool = db_pool
        self._repo: PaperTradeRepository | None = None  # Reuse same repo

    async def run(self) -> None:
        if self._db_pool is not None:
            self._repo = PaperTradeRepository(self._db_pool)
        await super().run()

    async def _execute_trade(self, data: dict[str, Any]) -> None:
        # ... existing execution ...

        # Persist to database
        if self._repo and order.status == OrderStatus.FILLED:
            await self._repo.insert_trade(
                opportunity_id=data.get("opportunity_id", "unknown"),
                opportunity_type=data.get("opportunity_type", "unknown"),
                market_id=market_id,
                venue=venue,
                side=side.value,
                outcome=data.get("outcome", "YES"),
                quantity=amount,
                price=order.average_price or Decimal("0"),
                fees=Decimal("0"),  # TODO: Calculate actual fees
                expected_edge=Decimal(str(data.get("expected_edge", "0"))),
                strategy_id=data.get("strategy"),
                risk_approved=True,
                paper_trade=False,  # Mark as live trade
            )
```

**Acceptance Criteria:**
- [ ] Live trades persisted to same table as paper trades
- [ ] `paper_trade=False` for live trades
- [ ] All fields populated correctly
- [ ] Test: Live trade appears in database

---

### Phase 6: Configuration Updates

#### Task 6.1: Add Credential Environment Variables to Config

**File:** [src/pm_arb/core/config.py](src/pm_arb/core/config.py)

**Add:**
```python
class Settings(BaseSettings):
    # ... existing fields ...

    # Polymarket credentials (required for live mode)
    polymarket_secret: str = ""
    polymarket_passphrase: str = ""

    # Trade sizing
    max_trade_size: float = 20.0  # $20 max per trade for MVP
```

**Acceptance Criteria:**
- [ ] New env vars loadable from .env
- [ ] Defaults allow paper mode without credentials
- [ ] max_trade_size configurable

---

## Acceptance Criteria

### Functional Requirements

- [ ] Live executor places real orders on Polymarket when `paper_trading=False`
- [ ] Orders include correct `token_id` for outcome being traded
- [ ] Fee-aware edge calculation filters unprofitable 15-min crypto opportunities
- [ ] Pushover alerts sent for trade executions, failures, and crashes
- [ ] `pm-arb stop` command gracefully shuts down running pilot
- [ ] Startup validation prevents live mode without valid credentials/balance
- [ ] Live trades persisted to database

### Non-Functional Requirements

- [ ] No breaking changes to paper trading mode
- [ ] Credentials never logged in plaintext
- [ ] Graceful degradation if Pushover unavailable
- [ ] Clear error messages for configuration issues

### Quality Gates

- [ ] All existing tests pass
- [ ] New tests for live executor message handling
- [ ] New tests for fee calculation
- [ ] New tests for alert service (mocked)
- [ ] Manual test: Place $10 order on Polymarket testnet (N/A - no testnet)
- [ ] Manual test: Verify alerts received on Pushover

## Success Metrics

1. **First Live Trade:** Successfully place and confirm a real order
2. **Fee Filtering:** Observe opportunities rejected due to insufficient net edge
3. **Alert Visibility:** Receive Pushover notification within 30s of trade
4. **Kill Switch:** `pm-arb stop` halts trading within 5 seconds

## Dependencies & Prerequisites

| Dependency | Status | Notes |
|------------|--------|-------|
| Polymarket credentials | Required | Must generate before live trading |
| Wallet with USDC | Required | Min $100 for initial testing |
| Pushover account | Optional | For alerts (free tier sufficient) |
| py-clob-client | Installed | Already in requirements |

## Risk Analysis & Mitigation

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Wrong token_id → order fails | Medium | Medium | Validation in adapter, test with known markets |
| Fee calculation wrong → unprofitable trades | Medium | Low | Unit tests against known fee values |
| Credentials exposed in logs | High | Low | Mask in `__str__`, review all log statements |
| Race condition on shutdown | Low | Low | Cancel open orders before completing stop |
| Alert storm | Low | Medium | Rate limit alerts in AlertService |

## Rollback Plan

If issues discovered during live trading:

1. **Immediate:** `pm-arb stop` or Ctrl+C
2. **Config:** Set `PAPER_TRADING=true` in .env
3. **Manual:** Cancel open orders in Polymarket UI
4. **Investigate:** Check logs, review trade history
5. **Fix:** Address issue, re-test in paper mode
6. **Resume:** Set `PAPER_TRADING=false`, restart pilot

## References & Research

### Internal References

- Brainstorm: [docs/brainstorms/2026-02-03-live-trading-mvp-brainstorm.md](docs/brainstorms/2026-02-03-live-trading-mvp-brainstorm.md)
- Paper executor pattern: [src/pm_arb/agents/paper_executor.py](src/pm_arb/agents/paper_executor.py)
- Auth module: [src/pm_arb/core/auth.py](src/pm_arb/core/auth.py)
- Existing live executor scaffold: [src/pm_arb/agents/live_executor.py](src/pm_arb/agents/live_executor.py)

### External References

- Polymarket Auth: https://docs.polymarket.com/developers/CLOB/authentication
- Polymarket Rate Limits: https://docs.polymarket.com/quickstart/introduction/rate-limits
- py-clob-client: https://github.com/Polymarket/py-clob-client
- Polymarket Maker Rebates (fee structure): https://docs.polymarket.com/polymarket-learn/trading/maker-rebates-program

### Institutional Learnings Applied

1. **Defensive parsing:** All external data uses `safe_decimal()` pattern
2. **Error handling:** Return status objects, never raise in adapters
3. **Multi-provider fallback:** Oracle already has CoinGecko fallback
4. **Fee awareness:** Critical insight that 15-min crypto markets have taker fees

---

## Task Checklist

### Phase 1: Critical Fixes
- [x] 1.1 Fix message channel subscription
- [x] 1.2 Add token_id to market data flow
- [x] 1.3 Wire LiveExecutor into pilot
- [x] 1.4 Add startup validation

### Phase 2: Fee-Aware Edge
- [x] 2.1 Detect 15-minute crypto markets
- [x] 2.2 Calculate net edge after fees

### Phase 3: AlertService
- [x] 3.1 Create Pushover AlertService
- [x] 3.2 Integrate alerts into LiveExecutor
- [x] 3.3 Integrate alerts into Pilot

### Phase 4: CLI Kill Switch
- [x] 4.1 Implement `pm-arb stop` command

### Phase 5: Persistence
- [x] 5.1 Add trade persistence to LiveExecutor

### Phase 6: Config
- [x] 6.1 Add credential env vars to config
