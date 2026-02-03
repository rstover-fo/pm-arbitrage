# 15-Second Poll Interval Too Slow for Arbitrage

---
status: pending
priority: p2
issue_id: 005
tags: [code-review, performance, trading-strategy]
dependencies: []
---

## Problem Statement

The CoinGecko oracle polls every 15 seconds, but the dashboard's "How It Works" page correctly states arbitrage windows close in 2-5 seconds. This means the system will miss 70-95% of opportunities.

**Why it matters:** The poll interval fundamentally limits the system's ability to capture arbitrage opportunities, making it ineffective for its stated purpose.

## Findings

**Source:** performance-oracle

**Location:** `src/pm_arb/pilot.py:111`, `src/pm_arb/dashboard/app.py:457-469`

**Evidence:**
```python
# pilot.py:111
OracleAgent(
    self._redis_url,
    oracle=coingecko_oracle,
    symbols=symbols,
    poll_interval=15.0,  # CoinGecko free tier: ~10-30 req/min
),

# dashboard/app.py:457-469 - The system's own documentation
st.code("""
Timeline:
---------*------------*------------*----------->
      BTC moves    We trade    Market corrects
        (0ms)       (50ms)       (2-5 sec)
""", language=None)
```

**Opportunity Loss Calculation:**
- Arbitrage window: ~2-5 seconds
- Poll interval: 15 seconds
- Probability of catching window: (5 / 15) = ~33% at best
- Most opportunities close before detection

## Proposed Solutions

### Option A: Add Real-Time Price Source (Recommended)
- **Description:** Add Binance WebSocket for sub-second BTC/ETH prices, keep CoinGecko as backup
- **Pros:** Free, real-time, solves the problem
- **Cons:** Adds complexity, Binance has geo-restrictions
- **Effort:** Medium
- **Risk:** Low

### Option B: Upgrade to CoinGecko Pro
- **Description:** Pay for CoinGecko Pro ($129/month) for 500 req/min
- **Pros:** Simple change (just poll faster)
- **Cons:** Monthly cost, still not real-time
- **Effort:** Small
- **Risk:** Low

### Option C: Accept Limitation for Paper Trading
- **Description:** Keep 15s interval, document as paper trading limitation
- **Pros:** No work required, free tier preserved
- **Cons:** System doesn't actually detect real arbitrage
- **Effort:** None
- **Risk:** None (but defeats purpose)

## Recommended Action

**DEFERRED - Option C (Accept for Paper Trading)**

Rationale: This is a paper trading pilot, not production. The 15s interval is acceptable for:
- Validating the system architecture
- Testing agent communication
- Demonstrating opportunity detection (even if not all are caught)

When moving to production, implement Option A (Binance WebSocket) for real-time data.

This is a feature enhancement, not a bug fix - appropriate for a future sprint.

## Technical Details

**Affected Files:**
- `src/pm_arb/pilot.py`
- `src/pm_arb/adapters/oracles/crypto.py` (existing Binance adapter)

**Components:**
- Oracle agent configuration
- Price data pipeline

**CoinGecko Rate Limits:**
- Free tier: ~10-30 calls/minute
- Pro tier ($129/mo): 500 calls/minute
- Demo tier (free with attribution): 30 calls/minute

## Acceptance Criteria

- [ ] Oracle data arrives within 1 second of price change (for real arbitrage)
- [ ] OR system clearly documented as "demo only" due to latency
- [ ] Rate limits not exceeded

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |
| 2026-02-03 | Deferred | Accepted as paper trading limitation; Option A for production |

## Resources

- PR: Paper trading pilot bug fixes
- CoinGecko pricing: https://www.coingecko.com/en/api/pricing
