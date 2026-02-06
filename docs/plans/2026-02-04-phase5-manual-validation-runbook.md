---
title: "Phase 5: Live Trading Manual Validation Runbook"
type: checklist
date: 2026-02-04
parent: docs/plans/2026-02-04-feat-live-trading-mvp-plan.md
---

# Phase 5: Live Trading Manual Validation Runbook

## Overview

Manual validation steps to verify the live trading system works end-to-end with real money. This is an operational runbook, not a coding task.

**Prerequisites:**
- Phases 1-4 complete (all 192 tests passing)
- Redis and PostgreSQL running
- Funded Polygon wallet with USDC.e

**Risk Controls:**
- Maximum position: $10
- Maximum single trade: $1
- Duration: 10 minutes
- Kill switch: `pm-arb stop`

---

## Task 1: Generate Polymarket API Credentials

**Duration:** ~10 minutes

### 1.1 Generate Wallet Signature

The py-clob-client requires signing an EIP-712 message to generate API credentials.

```bash
# Activate virtual environment
source .venv/bin/activate

# Launch Python REPL
python
```

```python
from py_clob_client.client import ClobClient

# Your funded Polygon wallet private key (0x + 64 hex chars)
private_key = "0x<your-64-char-hex-private-key>"

# Initialize client WITHOUT creds to generate them
client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,  # Polygon mainnet
    key=private_key,
)

# Generate API credentials via EIP-712 signature
creds = client.create_or_derive_api_creds()
print(f"API Key: {creds['apiKey']}")
print(f"Secret: {creds['secret']}")
print(f"Passphrase: {creds['passphrase']}")
```

### 1.2 Update Environment Variables

```bash
# Edit .env file
nano .env
```

Add/update these values:
```env
POLYMARKET_API_KEY=<apiKey from above>
POLYMARKET_SECRET=<secret from above>
POLYMARKET_PASSPHRASE=<passphrase from above>
POLYMARKET_PRIVATE_KEY=0x<your-64-char-hex-private-key>
```

### 1.3 Verify Credentials Load

```bash
python -c "
from pm_arb.core.auth import load_credentials
creds = load_credentials('polymarket')
print(f'Loaded: {creds}')
print('Credentials valid!')
"
```

**Expected:** `PolymarketCredentials(api_key=abc12345...)` (masked)

### 1.4 Verify API Connection

```bash
python -c "
import asyncio
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import load_credentials

async def test():
    creds = load_credentials('polymarket')
    adapter = PolymarketAdapter(credentials=creds)
    await adapter.connect()
    print(f'Authenticated: {adapter.is_authenticated}')
    balance = await adapter.get_balance()
    print(f'USDC Balance: \${balance}')
    await adapter.disconnect()

asyncio.run(test())
"
```

**Expected:**
- `Authenticated: True`
- `USDC Balance: $<your-balance>` (must be ≥ $10 for validation)

**Checkpoint:** [ ] Credentials generated and verified

---

## Task 2: Configure and Test Alerts

**Duration:** ~5 minutes

### 2.1 Set Up Pushover

1. Create account at https://pushover.net/
2. Note your **User Key** from dashboard
3. Create new application → get **API Token**

### 2.2 Update Environment

```bash
nano .env
```

Add:
```env
PUSHOVER_USER_KEY=<your-user-key>
PUSHOVER_API_TOKEN=<your-api-token>
```

### 2.3 Test Alert Delivery

```bash
python -c "
import asyncio
from pm_arb.core.alerts import AlertService, AlertPriority

async def test():
    alerts = AlertService()
    print(f'Alerts enabled: {alerts.is_enabled}')

    success = await alerts.send(
        title='PM-Arbitrage Test',
        message='Phase 5 validation - alert system working!',
        priority=AlertPriority.NORMAL,
    )
    print(f'Alert sent: {success}')

asyncio.run(test())
"
```

**Expected:** Push notification received on phone within 30 seconds

**Checkpoint:** [ ] Alert received on phone

---

## Task 3: Place $1 Manual Test Trade

**Duration:** ~5 minutes

### 3.1 Find an Active Market

```bash
python -c "
import asyncio
from pm_arb.adapters.venues.polymarket import PolymarketAdapter

async def find_market():
    adapter = PolymarketAdapter()
    await adapter.connect()

    markets = await adapter.get_crypto_markets()
    for m in markets[:5]:
        print(f'{m.external_id}: {m.title}')
        print(f'  YES: {m.yes_price}, NO: {m.no_price}')
        print(f'  Token IDs: YES={m.yes_token_id}, NO={m.no_token_id}')
        print()

    await adapter.disconnect()

asyncio.run(find_market())
"
```

Pick a market with good liquidity (spread < 5%).

### 3.2 Place Manual Trade via CLOB Client

```bash
python
```

```python
import asyncio
from decimal import Decimal
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import load_credentials
from pm_arb.core.models import Side, OrderType

async def place_trade():
    creds = load_credentials('polymarket')
    adapter = PolymarketAdapter(credentials=creds)
    await adapter.connect()

    # Use token_id from market lookup above
    token_id = "<YES_TOKEN_ID>"  # Replace with actual

    # Place $1 market order
    order = await adapter.place_order(
        token_id=token_id,
        side=Side.BUY,
        amount=Decimal("1.0"),  # $1 worth
        order_type=OrderType.MARKET,
    )

    print(f"Order ID: {order.id}")
    print(f"External ID: {order.external_id}")
    print(f"Status: {order.status}")
    print(f"Filled: {order.filled_amount}")

    await adapter.disconnect()

asyncio.run(place_trade())
```

### 3.3 Verify on Polymarket UI

1. Go to https://polymarket.com/portfolio
2. Confirm position appears
3. Note the position size matches $1

**Checkpoint:** [ ] $1 trade placed and visible on Polymarket

---

## Task 4: Run 10-Minute Live Dry-Run

**Duration:** 12-15 minutes

### 4.1 Configure Conservative Limits

```bash
nano .env
```

Set conservative risk limits:
```env
PAPER_TRADING=false
INITIAL_BANKROLL=10.0
POSITION_LIMIT_PCT=100.0    # Allow full $10 in single position
DAILY_LOSS_LIMIT_PCT=50.0   # Stop at $5 loss
DRAWDOWN_LIMIT_PCT=50.0     # Stop at $5 drawdown
```

### 4.2 Start Pilot in Live Mode

```bash
# Terminal 1: Run pilot
pm-arb pilot
```

**Watch for:**
```
executor_mode mode=live
polymarket_authenticated
live_validation_passed balance=$XX.XX
Starting agents...
agent_started: venue-watcher
agent_started: oracle-watcher
agent_started: opportunity-scanner
agent_started: risk-guardian
agent_started: live-executor
agent_started: strategy
agent_started: allocator
```

### 4.3 Monitor for 10 Minutes

```bash
# Terminal 2: Watch logs
tail -f ~/.pm-arb/pilot.log | grep -E "(opportunity|trade|error|alert)"
```

**Expected events:**
- `opportunity_detected` with net_edge values
- `trade_request` when scanner finds edge
- `risk_approved` or `risk_rejected` from guardian
- `trade_executed` if order fills
- Alert notifications on phone

### 4.4 Check Real-Time Status

```bash
# Terminal 3: Periodic checks
pm-arb status
pm-arb report --days 1
```

### 4.5 Graceful Shutdown

After 10 minutes:
```bash
pm-arb stop
```

**Verify clean shutdown:**
```
Stopping pilot (PID: XXXXX)...
agent_stopped: live-executor
agent_stopped: risk-guardian
...
Pilot stopped gracefully
```

**Checkpoint:** [ ] 10-minute run completed without crashes

---

## Task 5: Verify Positions Match Polymarket UI

**Duration:** ~5 minutes

### 5.1 Get System's View

```bash
pm-arb report --days 1
```

Note:
- Total trades executed
- Current open positions
- P&L (if any positions closed)

### 5.2 Compare with Polymarket UI

1. Go to https://polymarket.com/portfolio
2. Compare:
   - [ ] Number of positions matches
   - [ ] Position sizes match
   - [ ] Entry prices are close (within spread)

### 5.3 Check Database State

```bash
psql $DATABASE_URL -c "
SELECT
    market_id,
    outcome,
    entry_price,
    quantity,
    status,
    created_at
FROM paper_trades
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 10;
"
```

**Checkpoint:** [ ] Positions verified against Polymarket UI

---

## Task 6: Verify Alert Delivery

**Duration:** ~2 minutes

### 6.1 Check Phone for Notifications

During the 10-minute run, you should have received:
- [ ] `startup` alert when pilot started
- [ ] `trade_executed` for any filled trades
- [ ] `trade_failed` for any rejections (if applicable)

### 6.2 Test Critical Alert (Optional)

```bash
# Force a critical alert
python -c "
import asyncio
from pm_arb.core.alerts import AlertService, AlertPriority

async def test():
    alerts = AlertService()
    await alerts.agent_crash('test-agent', 'Manual test of critical alert')

asyncio.run(test())
"
```

This should:
- Bypass quiet hours
- Make sound even if phone is on silent
- Require acknowledgment

**Checkpoint:** [ ] All expected alerts received

---

## Validation Summary

| Task | Status | Notes |
|------|--------|-------|
| 1. Generate credentials | [ ] | API key, secret, passphrase, private_key |
| 2. Configure alerts | [ ] | Pushover test received |
| 3. Manual $1 trade | [ ] | Visible on Polymarket |
| 4. 10-min live run | [ ] | No crashes, clean shutdown |
| 5. Position matching | [ ] | System matches Polymarket UI |
| 6. Alert verification | [ ] | Notifications received |

## Success Criteria

**Phase 5 is COMPLETE when:**
1. ✅ At least one live trade executed successfully
2. ✅ Positions in database match Polymarket UI
3. ✅ Alerts arrive within 30 seconds
4. ✅ System runs 10+ minutes without intervention
5. ✅ Graceful shutdown works cleanly

## Troubleshooting

### Credentials Won't Load
```bash
# Check env vars are set
env | grep POLYMARKET

# Verify format
python -c "import os; print(len(os.getenv('POLYMARKET_PRIVATE_KEY', '')))"
# Should be 66 (0x + 64 hex chars)
```

### API Connection Fails
- Check CLOB endpoint: https://clob.polymarket.com/health
- Verify Polygon network is up
- Ensure wallet has MATIC for gas

### No Opportunities Detected
- Check oracle data is flowing (Binance/CoinGecko)
- Verify market matcher has valid pairs
- Net edge threshold may be too high (default 2%)

### Alerts Not Received
- Verify Pushover app installed on phone
- Check Pushover subscription is active
- Test with curl: `curl -s --form-string "token=<TOKEN>" --form-string "user=<USER>" --form-string "message=test" https://api.pushover.net/1/messages.json`

---

## Post-Validation

After successful validation:

1. **Document learnings** at `docs/solutions/integration-issues/polymarket-live-trading-validation.md`
2. **Increase limits** gradually: $10 → $50 → $100
3. **Enable extended monitoring**: 30-min → 1-hour → overnight runs
4. **Consider**: Automated deployment, monitoring dashboards, position reconciliation cron
