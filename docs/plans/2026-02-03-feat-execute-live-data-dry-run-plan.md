---
title: Execute Live Data Dry Run
type: feat
date: 2026-02-03
---

# Execute Live Data Dry Run

## Overview

Validate the paper trading pilot with real Polymarket/Binance data before extended multi-day runs or live trading consideration.

## Prerequisites

- [x] Docker containers running (PostgreSQL + Redis)
- [x] P1 findings addressed (4/4 complete)
- [x] Most P2/P3 findings addressed (6/9 complete)
- [ ] Virtual environment activated
- [ ] No blocking firewall rules for external APIs

## Quick Start Commands

```bash
cd /Users/robstover/Development/personal/pm-arbitrage

# Activate environment
source .venv/bin/activate

# Verify infrastructure
docker-compose ps

# Initialize database (if not done)
python -c "import asyncio; from pm_arb.db import init_db; asyncio.run(init_db())"

# Verify environment config
cat .env | grep -E "REDIS_URL|DATABASE_URL|PAPER_TRADING"
```

## Execution Checklist

### Phase 1: Infrastructure Verification (2 min)

- [ ] `docker-compose ps` shows postgres and redis healthy
- [ ] Database responds: `psql postgresql://pm_arb:pm_arb@localhost:5432/pm_arb -c "SELECT 1;"`
- [ ] Redis responds: `redis-cli ping` returns PONG

### Phase 2: Start Pilot (Terminal 1)

```bash
pm-arb pilot
```

**Watch for (in order):**
- [ ] `pilot_starting` log message
- [ ] All 7 agents report `agent_started`:
  - venue-watcher-polymarket
  - oracle-binance
  - opportunity-scanner
  - risk-guardian
  - paper-executor
  - oracle-sniper (strategy)
  - capital-allocator
- [ ] `pilot_started` with `agent_count=7`
- [ ] No crash within first 30 seconds

### Phase 3: Verify External Data (Terminal 2)

```bash
# Test Binance API
curl -s "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT" | jq .

# Test Polymarket API
curl -s "https://gamma-api.polymarket.com/markets?closed=false&limit=5" | jq '.[0].question'
```

**Watch pilot logs for:**
- [ ] `oracle-binance`: `price_update` with BTC/ETH prices
- [ ] `venue-watcher-polymarket`: `markets_fetched` or `market_update`

### Phase 4: Monitor Message Bus (Optional)

```bash
redis-cli SUBSCRIBE oracle.prices venue.markets opportunity.detected trade.requests trade.decisions trade.results
```

- [ ] See messages flowing through channels

### Phase 5: Check Reports (Terminal 2)

```bash
# After pilot has run for 5+ minutes
pm-arb report --days 1
```

**Expected output structure:**
```
PM Arbitrage - Daily Summary
─────────────────────────────
TRADES
  Total trades: N
  Open positions: N
  Closed: N

P&L (Paper)
  Realized P&L: $X.XX
  Win rate: XX% (N/N)
```

- [ ] Report command executes without errors
- [ ] Trade count matches log observations

### Phase 6: Dashboard Verification (Terminal 3)

```bash
streamlit run src/pm_arb/dashboard/app.py
```

**Check each page:**

| Page | Verification |
|------|-------------|
| Overview | Shows portfolio summary |
| Pilot Monitor | Displays P&L, trades, win rate; "Live" indicator green |
| Strategies | Lists active strategies |
| Trades | Shows trade history table |
| Risk | Shows positions, exposure |
| System | Shows agent status (all running) |
| How It Works | Educational content renders |

- [ ] All pages load without errors
- [ ] Pilot Monitor "Refresh" updates data
- [ ] Trade count matches `pm-arb report` output

### Phase 7: Graceful Shutdown

In Terminal 1, press `Ctrl+C`.

**Watch for:**
- [ ] `pilot_stopping` log
- [ ] Each agent reports stopping
- [ ] `pilot_shutdown_complete` log
- [ ] No stack traces or orphaned processes

**Verify state persistence:**
```bash
# Note trade count before restart
pm-arb report --days 1

# Restart pilot briefly
pm-arb pilot
# Watch for `state_recovered` log with open trade count
# Ctrl+C to stop

# Verify count matches
pm-arb report --days 1
```

- [ ] Trade count preserved across restart

## Success Criteria

The dry run is **successful** if ALL of these are true:

- [ ] All 7 agents start without errors
- [ ] Binance prices appear in logs
- [ ] Polymarket markets are fetched
- [ ] Redis message bus shows activity
- [ ] Database queries work (report command)
- [ ] Dashboard displays correct data
- [ ] Graceful shutdown completes cleanly
- [ ] State recovery works on restart

## Expected Observations

**Normal behavior:**
- Opportunities may be rare in stable markets (this is expected)
- Scanner should show `price_received` or `market_received` even if no opportunities detected
- Win rate may be 0% if no trades resolved yet

**Warning signs:**
- `agent_crashed` errors → check specific error, may need code fix
- `Connection refused` → check Docker containers
- High memory usage over time → potential connection leak

## Post-Dry-Run Actions

Based on results:

| Outcome | Next Step |
|---------|-----------|
| All checks pass | Plan extended multi-day run |
| Minor bugs found | Create todos, fix before extended run |
| Major issues | Prioritize fixes, re-run dry run |
| Stable for 30+ min | Consider live trading readiness planning |

## Findings Log

Document any issues during the dry run:

| Time | Issue | Severity | Notes |
|------|-------|----------|-------|
| | | | |
| | | | |
| | | | |

## Terminal Setup Reference

```
┌─────────────────────┬─────────────────────┐
│ Terminal 1          │ Terminal 2          │
│ pm-arb pilot        │ Reports, API tests  │
│ (main process)      │ pm-arb report       │
├─────────────────────┼─────────────────────┤
│ Terminal 3          │ Terminal 4          │
│ streamlit run ...   │ redis-cli SUBSCRIBE │
│ (dashboard)         │ (optional)          │
└─────────────────────┴─────────────────────┘
```
