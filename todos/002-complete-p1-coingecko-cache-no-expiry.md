# CoinGecko Price Cache Has No Expiration

---
status: pending
priority: p1
issue_id: 002
tags: [code-review, data-integrity, performance, trading-safety]
dependencies: []
---

## Problem Statement

The CoinGecko oracle caches prices indefinitely with no TTL or staleness check. If API calls fail, the system continues using arbitrarily old prices, potentially executing trades based on data that is hours old.

**Why it matters:** Stale prices in an arbitrage system mean the detected "opportunities" may not exist, leading to trades that lose money at execution.

## Findings

**Source:** data-integrity-guardian, performance-oracle

**Location:** `src/pm_arb/adapters/oracles/coingecko.py:37-38, 70-78, 104-108`

**Evidence:**
```python
self._cached_prices: dict[str, Decimal] = {}  # Line 37 - No TTL

# Line 70: Returns cached price with no staleness check
price = self._cached_prices.get(symbol_upper)
if price is None:
    return None

# Lines 104-108: Only updates cache on successful fetch
for coin_id, prices in data.items():
    symbol = ID_TO_SYMBOL.get(coin_id)
    if symbol and "usd" in prices:
        self._cached_prices[symbol] = Decimal(str(prices["usd"]))
```

**Corruption Scenario:**
- 10:00 AM: BTC = $100,000 (cached successfully)
- 10:01-12:00 PM: Network issues prevent updates (API calls fail silently)
- 12:00 PM: BTC = $85,000 (reality), cache still shows $100,000
- System sees 15% "opportunity" that doesn't exist
- Trade executes at $85,000, not the expected $100,000

## Proposed Solutions

### Option A: Add TTL with Timestamp Tracking (Recommended)
- **Description:** Track cache timestamp and reject data older than threshold (e.g., 30 seconds)
- **Pros:** Simple, effective, configurable
- **Cons:** Adds state complexity
- **Effort:** Small
- **Risk:** Low

```python
def __init__(self) -> None:
    self._cached_prices: dict[str, Decimal] = {}
    self._cache_timestamp: datetime | None = None
    self._cache_ttl = timedelta(seconds=30)

async def get_current(self, symbol: str) -> OracleData | None:
    now = datetime.now(UTC)
    if (self._cache_timestamp is None or
        now - self._cache_timestamp > self._cache_ttl):
        await self._fetch_batch()
        self._cache_timestamp = now
    # ... rest of method
```

### Option B: Return None on Stale Cache
- **Description:** If cache is older than TTL, return None instead of stale data
- **Pros:** Fail-safe, prevents stale trades
- **Cons:** May cause gaps in data during network issues
- **Effort:** Small
- **Risk:** Medium - reduced availability

### Option C: Include Timestamp in OracleData
- **Description:** Let consumers decide staleness by checking `OracleData.timestamp`
- **Pros:** Flexible, doesn't change adapter behavior
- **Cons:** Pushes responsibility to every consumer
- **Effort:** Medium
- **Risk:** Low

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/adapters/oracles/coingecko.py`
- `src/pm_arb/agents/oracle_agent.py` (downstream consumer)
- `src/pm_arb/agents/opportunity_scanner.py`

**Components:**
- CoinGecko oracle adapter
- Oracle agent
- Opportunity detection pipeline

## Acceptance Criteria

- [ ] Cache has configurable TTL (default 30 seconds)
- [ ] Stale cache triggers re-fetch or returns None
- [ ] Timestamps are tracked and logged
- [ ] Tests verify staleness handling

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- Similar: Binance oracle doesn't cache (different pattern)
