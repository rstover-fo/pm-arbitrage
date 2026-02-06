# Paper Trading Pilot - Live Data Dry Run Test Plan

> **For Claude:** This is a testing/validation plan, not an implementation plan. Use this to guide a systematic end-to-end validation session.

**Goal:** Validate the paper trading pilot works correctly with real Polymarket/Binance data, from agent startup through trade persistence to dashboard visualization.

**Approach:** Live data dry run - connect to real market feeds, execute paper trades only, observe and verify each stage of the pipeline.

---

## Prerequisites Checklist

Before starting the test session, verify:

- [ ] Docker is installed and running
- [ ] Python 3.12+ available (`python --version`)
- [ ] Project virtual environment exists (`.venv/`)
- [ ] No blocking firewall rules for Binance/Polymarket APIs

---

## Phase 1: Infrastructure Setup

### Task 1.1: Start Docker Services

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
docker-compose up -d
```

**Verify:**
```bash
docker-compose ps
```

**Expected:** Both `postgres` and `redis` containers running and healthy.

**If fails:**
- Check Docker Desktop is running
- Check port conflicts: `lsof -i :5432` and `lsof -i :6379`

---

### Task 1.2: Initialize Database

```bash
source .venv/bin/activate
python -c "import asyncio; from pm_arb.db import init_db; asyncio.run(init_db())"
```

**Verify:**
```bash
psql postgresql://pm_arb:pm_arb@localhost:5432/pm_arb -c "SELECT COUNT(*) FROM paper_trades;"
```

**Expected:** Returns `0` (or count of existing trades).

**If fails:**
- Check DATABASE_URL in `.env` matches docker-compose credentials
- Ensure postgres container is healthy: `docker-compose logs postgres`

---

### Task 1.3: Verify Environment Configuration

```bash
cat .env | grep -E "REDIS_URL|DATABASE_URL|PAPER_TRADING"
```

**Expected:**
```
REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://pm_arb:pm_arb@localhost:5432/pm_arb
PAPER_TRADING=true
```

**If missing:** Copy from template:
```bash
cp .env.example .env
```

---

## Phase 2: Agent Startup Validation

### Task 2.1: Start Pilot Orchestrator

**Terminal 1:**
```bash
pm-arb pilot
```

**Watch for (in order):**
1. `pilot_starting` log message
2. Each agent reports `agent_started`:
   - `venue-watcher-polymarket`
   - `oracle-binance`
   - `opportunity-scanner`
   - `risk-guardian`
   - `paper-executor`
   - `oracle-sniper` (strategy)
   - `capital-allocator`
3. `pilot_started` with `agent_count=7`

**Success indicators:**
- No crash within first 30 seconds
- All 7 agents started
- Periodic log messages showing activity

**Failure indicators:**
- `agent_crashed` errors
- Connection refused to Redis/Postgres
- Import errors (missing dependencies)

---

### Task 2.2: Verify External Data Connections

**Watch pilot logs for:**

| Agent | Expected Log Pattern |
|-------|---------------------|
| `oracle-binance` | `price_update` with BTC/ETH prices |
| `venue-watcher-polymarket` | `markets_fetched` or `market_update` |

**Test external connectivity (separate terminal):**
```bash
# Test Binance API
curl -s "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT" | jq .

# Test Polymarket API
curl -s "https://gamma-api.polymarket.com/markets?closed=false&limit=5" | jq '.[0].question'
```

**Expected:** Both return valid JSON with current prices/markets.

---

## Phase 3: Opportunity Detection

### Task 3.1: Monitor Opportunity Scanner

Watch pilot logs for `opportunity_detected` events.

**Note:** Real opportunities may be rare. The scanner looks for:
- Oracle lag (BTC/ETH price moves faster than market odds)
- Mispricing (YES + NO don't sum to ~100%)

**If no opportunities after 5 minutes:**
- This is NORMAL for stable markets
- Check scanner is receiving data: look for `price_received` or `market_received` logs

---

### Task 3.2: Verify Message Bus Flow

In a separate terminal, monitor Redis pub/sub:

```bash
redis-cli SUBSCRIBE oracle.prices venue.markets opportunity.detected trade.requests trade.decisions trade.results
```

**Expected:** See messages flowing through channels as agents communicate.

---

## Phase 4: Trade Execution Verification

### Task 4.1: Check Paper Trades in Database

**Terminal 2:**
```bash
pm-arb report --days 1
```

**Expected output:**
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

**If no trades appear:**
- Opportunities may not have been detected yet (normal in stable markets)
- Check `trade.requests` channel in Redis CLI
- Verify Risk Guardian isn't rejecting all trades: `pm-arb report --json | jq .risk_rejections`

---

### Task 4.2: Verify Database Persistence

```bash
psql postgresql://pm_arb:pm_arb@localhost:5432/pm_arb -c "SELECT id, created_at, opportunity_type, market_id, side, status FROM paper_trades ORDER BY created_at DESC LIMIT 5;"
```

**Expected:** Rows showing paper trades with proper fields populated.

---

## Phase 5: Dashboard Validation

### Task 5.1: Start Dashboard

**Terminal 3:**
```bash
streamlit run src/pm_arb/dashboard/app.py
```

**Opens:** http://localhost:8501

---

### Task 5.2: Verify Dashboard Pages

| Page | What to Check |
|------|---------------|
| **Overview** | Shows portfolio summary, capital allocation |
| **Pilot Monitor** | Displays cumulative P&L, trades today, win rate |
| **Strategies** | Lists active strategies with performance |
| **Trades** | Shows trade history table |
| **Risk** | Shows positions, exposure, drawdown |
| **System** | Shows agent status (should show running) |
| **How It Works** | Educational content renders properly |

**Key validation on Pilot Monitor:**
- "Live" indicator shows green
- Trade count matches `pm-arb report` output
- Click "Refresh" - data updates

---

### Task 5.3: Verify Live Updates

1. Keep dashboard open on Pilot Monitor
2. Wait for a trade to execute (or verify existing trades)
3. Click Refresh
4. Verify trade appears in "Recent Trades" table

---

## Phase 6: Graceful Shutdown

### Task 6.1: Stop Pilot

In Terminal 1, press `Ctrl+C`.

**Watch for:**
1. `pilot_stopping` log
2. Each agent reports stopping
3. `pilot_shutdown_complete` log

**Verify clean exit:**
- No stack traces
- No orphaned processes: `ps aux | grep pm_arb`

---

### Task 6.2: Verify State Recovery

1. Note the trade count from `pm-arb report`
2. Restart pilot: `pm-arb pilot`
3. Check logs for `state_recovered` with open trade count
4. Run `pm-arb report` again - count should match

---

## Phase 7: Extended Run (Optional)

For stability testing, leave the pilot running for an extended period:

### Task 7.1: Background Run

```bash
nohup pm-arb pilot > pilot.log 2>&1 &
echo $! > pilot.pid
```

### Task 7.2: Monitor Over Time

```bash
# Check if still running
ps -p $(cat pilot.pid)

# View recent logs
tail -100 pilot.log

# Check for crashes/restarts
grep -c "agent_crashed" pilot.log

# Daily summary
pm-arb report --days 1
```

### Task 7.3: Stop Background Pilot

```bash
kill $(cat pilot.pid)
```

---

## Success Criteria

The live data dry run is **successful** if:

- [ ] All 7 agents start without errors
- [ ] Binance prices appear in logs
- [ ] Polymarket markets are fetched
- [ ] Redis message bus shows activity
- [ ] Trades persist to PostgreSQL (if opportunities detected)
- [ ] Dashboard displays correct data
- [ ] Graceful shutdown completes cleanly
- [ ] State recovery works on restart

---

## Troubleshooting Reference

| Issue | Likely Cause | Fix |
|-------|--------------|-----|
| `Connection refused` to Redis | Redis not running | `docker-compose up -d redis` |
| `Connection refused` to Postgres | Postgres not running | `docker-compose up -d postgres` |
| No opportunities detected | Market is stable | Normal - wait or check scanner config |
| Agent keeps crashing | Check specific error | Look at full traceback in logs |
| Dashboard shows 0 trades | No opportunities OR DB not connected | Check `DATABASE_URL`, run `pm-arb report` |
| High memory usage | Connection leaks | Check pool cleanup, restart pilot |

---

## Post-Test Actions

After successful validation:

1. **Document findings** - Note any bugs, slow responses, or unexpected behavior
2. **Create issues** - File GitHub issues for any bugs found
3. **Consider next steps:**
   - If stable: Plan for longer multi-day run
   - If bugs found: Fix before extended testing
   - If working well: Consider live trading readiness

---

## Execution Notes

**Estimated time:** 30-60 minutes for full validation

**Best run during:** Active market hours (when Polymarket has activity)

**Terminal setup:**
- Terminal 1: Pilot (`pm-arb pilot`)
- Terminal 2: Reports/DB queries
- Terminal 3: Dashboard (`streamlit run ...`)
- Terminal 4: Redis monitoring (optional)
