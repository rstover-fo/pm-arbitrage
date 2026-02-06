# Review Prompt: Paper Trading Pilot Bug Fixes

> **For Claude:** Run `/workflows:review` on this session's changes.

## Context

During end-to-end testing of the paper trading pilot, we discovered and fixed 5 bugs that prevented the system from running correctly with live data.

## Files Changed

```
src/pm_arb/pilot.py                        # Switch to CoinGecko, fix symbols
src/pm_arb/adapters/oracles/coingecko.py   # NEW: CoinGecko oracle adapter
src/pm_arb/adapters/oracles/crypto.py      # Update Binance.US endpoints
src/pm_arb/adapters/venues/polymarket.py   # Safe decimal parsing
src/pm_arb/dashboard/app.py                # Fix async event loop issues
```

## Bugs Fixed

### 1. Binance Symbol Doubling
**File:** `pilot.py:106`
**Issue:** Passed `["BTCUSDT", "ETHUSDT"]` but crypto.py appends "USDT", resulting in `BTCUSDTUSDT`
**Fix:** Changed to `["BTC", "ETH"]`

### 2. Polymarket Decimal Parsing
**File:** `polymarket.py`
**Issue:** `Decimal(str(value))` fails on empty strings or non-numeric API responses
**Fix:** Added `_safe_decimal()` helper with fallback to default value

### 3. Binance Geo-blocking (HTTP 451)
**File:** `coingecko.py` (new), `pilot.py`
**Issue:** Binance.com API blocked in US; Binance.US has SSL issues
**Fix:** Created CoinGecko oracle adapter as alternative (no geo-restrictions)

### 4. CoinGecko Rate Limits (HTTP 429)
**File:** `coingecko.py`, `pilot.py`
**Issue:** Separate API calls per symbol hit CoinGecko's rate limits
**Fix:** Batch fetching (single call for all symbols) + 15s poll interval

### 5. Dashboard Async Event Loop
**File:** `app.py`
**Issue:** `asyncio.run()` fails inside Streamlit (already has event loop)
**Fix:** Create fresh DB pool per request instead of caching across async contexts; added `nest_asyncio`

## Review Focus Areas

1. **CoinGecko adapter** - New file, needs full review for:
   - Error handling
   - Rate limit resilience
   - Cache invalidation
   - Symbol mapping correctness

2. **Polymarket safe_decimal** - Verify:
   - All Decimal conversions covered
   - Default values are sensible
   - No silent data corruption

3. **Dashboard async fix** - Check:
   - Pool cleanup (no connection leaks)
   - Performance impact of per-request pools
   - Whether nest_asyncio is necessary

4. **Pilot orchestrator** - Verify:
   - Oracle channel names match (`oracle.coingecko.prices`)
   - Poll intervals are appropriate
   - No regressions to existing functionality

## Test Commands

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

## Expected Review Output

- Security concerns (if any)
- Code quality issues
- Missing error handling
- Performance considerations
- Suggestions for improvement
