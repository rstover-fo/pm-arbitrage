# Paper Trading Pilot API Integration Fixes

---
title: Paper Trading Pilot API Integration Fixes
category: integration-issues
tags: [oracle-adapters, venue-adapters, external-apis, async, streamlit, coingecko, polymarket]
symptoms:
  - HTTP 404 with malformed symbols like BTCUSDTUSDT
  - decimal.InvalidOperation on parsing API responses
  - HTTP 451 Unavailable For Legal Reasons from Binance
  - HTTP 429 Too Many Requests from CoinGecko
  - RuntimeError asyncio.run() cannot be called from running event loop
module: pm_arb.adapters, pm_arb.dashboard
date_documented: 2026-02-03
---

## Overview

During end-to-end testing of the paper trading pilot, we discovered and fixed 5 bugs that prevented the system from running correctly with live data. All issues relate to integrating with external APIs (CoinGecko, Polymarket) and handling async patterns in the Streamlit dashboard.

**Files Changed:**
- `src/pm_arb/pilot.py` - Switch to CoinGecko, fix symbol format
- `src/pm_arb/adapters/oracles/coingecko.py` - NEW: CoinGecko oracle adapter
- `src/pm_arb/adapters/oracles/crypto.py` - Update Binance.US endpoints
- `src/pm_arb/adapters/venues/polymarket.py` - Safe decimal parsing
- `src/pm_arb/dashboard/app.py` - Fix async event loop issues

---

## Bug 1: Binance Symbol Doubling

### Symptom
Oracle price fetching fails with HTTP 404 errors. Logs show malformed symbols like `BTCUSDTUSDT`.

### Root Cause
The pilot passed fully-qualified symbols `["BTCUSDT", "ETHUSDT"]` to the oracle adapter, which internally appends `"USDT"` to construct Binance trading pairs. This resulted in double-suffixed symbols.

### Solution

**File:** `src/pm_arb/pilot.py:93`

```python
# Before - WRONG
symbols = ["BTCUSDT", "ETHUSDT"]

# After - CORRECT
symbols = ["BTC", "ETH"]
```

The adapter handles symbol-to-pair conversion internally. Pass only asset symbols.

### Prevention
- Document symbol format conventions in adapter docstrings
- Add input validation to reject symbols that already contain quote currency
- Test: Verify constructed API URLs don't have duplicate suffixes

---

## Bug 2: Polymarket Decimal Parsing Crashes

### Symptom
`decimal.InvalidOperation` exception when parsing market data with None or empty string values.

### Root Cause
Direct `Decimal(str(value))` conversion fails on `None`, `""`, or malformed strings. Polymarket API sometimes returns incomplete data for illiquid markets.

### Solution

**File:** `src/pm_arb/adapters/venues/polymarket.py:7-14`

```python
from decimal import Decimal, InvalidOperation
from typing import Any

def _safe_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Safely convert value to Decimal, returning default if conversion fails."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
```

Used in `_parse_market()`:
```python
yes_price = _safe_decimal(prices[0], default_price) if prices else default_price
no_price = _safe_decimal(prices[1], default_price) if len(prices) > 1 else default_price
volume_24h = _safe_decimal(data.get("volume24hr", 0))
liquidity = _safe_decimal(data.get("liquidity", 0))
```

### Prevention
- Always use defensive parsing for external API data
- Test with: `None`, `""`, `"NaN"`, `"invalid"`, extremely large numbers
- Log parsing failures instead of silently defaulting (see code review finding #001)

---

## Bug 3: Binance Geo-blocking (HTTP 451)

### Symptom
`HTTP 451 Unavailable For Legal Reasons` from Binance API. Binance.US alternative has SSL/connectivity issues.

### Root Cause
Binance implements geographic IP-based blocking for regulatory compliance. The system had no fallback oracle.

### Solution

Created CoinGecko oracle adapter (no geo-restrictions, free tier available).

**File:** `src/pm_arb/adapters/oracles/coingecko.py` (NEW)

```python
"""CoinGecko crypto price oracle - no geo-restrictions."""

COINGECKO_API = "https://api.coingecko.com/api/v3"

SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}

class CoinGeckoOracle(OracleAdapter):
    name = "coingecko"

    async def get_current(self, symbol: str) -> OracleData | None:
        # Uses batch fetching from cache
        ...

    async def _fetch_batch(self) -> None:
        # Single API call for all symbols
        response = await self._client.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": ",".join(coin_ids), "vs_currencies": "usd"},
        )
```

Updated pilot to use CoinGecko:
```python
from pm_arb.adapters.oracles.coingecko import CoinGeckoOracle

coingecko_oracle = CoinGeckoOracle()
```

### Prevention
- Design for multi-provider fallback from the start
- Test with primary oracle disabled to verify failover
- Document geo-restrictions in adapter selection guide

---

## Bug 4: CoinGecko Rate Limits (HTTP 429)

### Symptom
`HTTP 429 Too Many Requests` when polling CoinGecko API too frequently.

### Root Cause
Initial implementation made individual API calls per symbol. With 2+ symbols, this exceeded CoinGecko free tier limits (~10-30 req/min).

### Solution

**Batch fetching:** Single API call for all symbols.

```python
async def _fetch_batch(self) -> None:
    """Fetch all configured symbols in one API call."""
    coin_ids = [SYMBOL_TO_ID[sym] for sym in self._symbols]

    response = await self._client.get(
        f"{COINGECKO_API}/simple/price",
        params={"ids": ",".join(coin_ids), "vs_currencies": "usd"},
    )
```

**Increased poll interval:**

```python
# pilot.py
OracleAgent(
    self._redis_url,
    oracle=coingecko_oracle,
    symbols=symbols,
    poll_interval=15.0,  # CoinGecko free tier: ~10-30 req/min
),
```

**Rate calculation:** 1 call every 15 seconds = 4 calls/min (well within limits)

### Prevention
- Document API rate limits in adapter classes
- Implement batch endpoints where available
- Add exponential backoff on 429 responses
- Consider paid tier for production ($129/mo for CoinGecko Pro)

---

## Bug 5: Dashboard Async Event Loop Error

### Symptom
`RuntimeError: asyncio.run() cannot be called from a running event loop` in Streamlit dashboard.

### Root Cause
Streamlit runs its own event loop. Calling `asyncio.run()` inside that loop violates Python's event loop nesting rules.

### Solution

**Part 1:** Add `nest_asyncio` to allow nested event loops.

**File:** `src/pm_arb/dashboard/app.py:6-9`

```python
import nest_asyncio

# Allow nested event loops (needed for asyncio.run() inside Streamlit)
nest_asyncio.apply()
```

**Part 2:** Create fresh DB pool per request instead of caching.

```python
async def _get_pilot_summary() -> dict:
    # Create a fresh pool for this request (avoids event loop issues)
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=2,
    )

    try:
        repo = PaperTradeRepository(pool)
        summary = await repo.get_daily_summary(days=7)
        return {...}
    finally:
        await pool.close()
```

### Prevention
- Use sync database access in Streamlit when possible
- Or use Streamlit's native async support (1.18+)
- Document async patterns for dashboard development
- See code review findings #003 and #012 for improvements

---

## Verification Commands

```bash
# Run existing tests
pytest tests/ -v

# Start pilot and verify no errors
pm-arb pilot

# Check dashboard works
streamlit run src/pm_arb/dashboard/app.py

# Generate report
pm-arb report --days 1
```

---

## Related Documentation

- Design doc: `docs/plans/2026-01-30-arbitrage-bot-design.md`
- Paper trading plan: `docs/plans/2026-02-03-paper-trading-pilot.md`
- CoinGecko API: https://www.coingecko.com/en/api/documentation
- Polymarket CLOB API: https://docs.polymarket.com/
- Streamlit async: https://docs.streamlit.io/develop/concepts/architecture/caching

---

## Code Review Findings

During review of these fixes, additional improvements were identified and documented in `todos/`:

| ID | Priority | Issue |
|----|----------|-------|
| 001 | P1 | Silent price fallback creates phantom signals |
| 002 | P1 | CoinGecko cache has no expiration |
| 003 | P1 | Dashboard creates fresh DB pool per request |
| 004 | P1 | Oracle channel name mismatch |
| 005 | P2 | 15s poll interval too slow for arbitrage |
| 006 | P2 | Import order violation in polymarket.py |
| 007 | P2 | Race condition in batch fetch trigger |
| 008 | P2 | Dashboard is GUI-only, no API |
| 009 | P2 | Hardcoded default DB credentials |

See `todos/` directory for full details and remediation options.
