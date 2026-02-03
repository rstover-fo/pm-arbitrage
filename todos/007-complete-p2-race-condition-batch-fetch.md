# Race Condition in CoinGecko Batch Fetch Trigger

---
status: complete
priority: p2
issue_id: 007
tags: [code-review, concurrency, data-integrity]
dependencies: [002]
---

## Problem Statement

The CoinGecko adapter's batch fetch is triggered only when the first symbol (BTC) is requested. This creates race conditions when symbols are requested concurrently or out of order, potentially causing some symbols to return None or stale data.

**Why it matters:** Intermittent missing data causes unpredictable arbitrage detection behavior that is hard to debug.

## Findings

**Source:** data-integrity-guardian, architecture-strategist

**Location:** `src/pm_arb/adapters/oracles/coingecko.py:64-67`

**Evidence:**
```python
# If we have symbols configured, do a batch fetch for all of them
if self._symbols and symbol_upper == self._symbols[0]:
    # First symbol triggers batch fetch
    await self._fetch_batch()
```

**Race Condition Scenario:**
```
Coroutine A: get_current("BTC") -> triggers _fetch_batch()
Coroutine B: get_current("ETH") -> returns None (cache not yet populated)
Coroutine A: _fetch_batch() completes, populates cache
Coroutine B: already returned None for ETH

Result: ETH oracle data missing for this arbitrage cycle
```

**Additional Issues:**
- No locking on `_cached_prices` dict during concurrent access
- Dual fetch if two coroutines call `get_current("BTC")` simultaneously

## Proposed Solutions

### Option A: TTL-Based Fetch with Lock (Recommended)
- **Description:** Use timestamp-based staleness check with asyncio Lock
- **Pros:** Eliminates race conditions, predictable behavior
- **Cons:** Adds lock contention
- **Effort:** Medium
- **Risk:** Low

```python
def __init__(self) -> None:
    self._lock = asyncio.Lock()
    self._cache_timestamp: datetime | None = None

async def get_current(self, symbol: str) -> OracleData | None:
    async with self._lock:
        if self._cache_stale():
            await self._fetch_batch()
            self._cache_timestamp = datetime.now(UTC)
    return self._cached_prices.get(symbol.upper())
```

### Option B: Remove Caching (Simpler)
- **Description:** Fetch on every request, no caching
- **Pros:** No race conditions, simple
- **Cons:** More API calls, may hit rate limits
- **Effort:** Small
- **Risk:** Medium (rate limits)

### Option C: Pre-Fetch All on Startup
- **Description:** Fetch all prices in `connect()`, then on each `get_current()` only return cached
- **Pros:** Simple, no per-request fetching
- **Cons:** Prices become stale between polls
- **Effort:** Small
- **Risk:** Low

## Recommended Action

[To be filled during triage]

## Technical Details

**Affected Files:**
- `src/pm_arb/adapters/oracles/coingecko.py`

**Components:**
- CoinGecko oracle adapter
- Price caching

**Dependencies:**
- Should be fixed alongside #002 (cache expiration)

## Acceptance Criteria

- [ ] No race conditions in price fetching
- [ ] All symbols return consistent data
- [ ] Tests verify concurrent access patterns

## Work Log

| Date | Action | Notes |
|------|--------|-------|
| 2026-02-03 | Created | Identified during code review of pilot bug fixes |

## Resources

- PR: Paper trading pilot bug fixes
- Python asyncio Lock docs
