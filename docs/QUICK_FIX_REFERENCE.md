# Quick Fix Reference - 5 Paper Trading Bugs

**TL;DR for each bug + minimal code to fix it.**

---

## 1. Binance Symbol Doubling

**Error:** `BTCUSDTUSDT` (double suffix)
**Line:** `crypto.py:68`

### Quick Fix
```python
# BEFORE (wrong)
symbols = ["BTCUSDT", "ETHUSDT"]  # Pre-suffixed
# Adapter adds USDT again → BTCUSDTUSDT

# AFTER (correct)
symbols = ["BTC", "ETH"]  # Bare format
# Adapter correctly transforms to BTCUSDT
```

### 1-Minute Implementation
```python
# Add to pilot.py
symbols = ["BTC", "ETH"]  # ALWAYS bare format

# Add validation
from pm_arb.core.validators import SymbolValidator
symbols = SymbolValidator.validate_bare_symbols(symbols)

# Update crypto.py to reject pre-suffixed:
if symbol.endswith("USDT"):
    raise ValueError(f"Expected bare symbol, got {symbol}")
```

### Test It
```python
pytest tests/adapters/oracles/test_crypto.py::test_binance_oracle_rejects_presuffixed_symbols
```

---

## 2. Polymarket Decimal Parsing

**Error:** `InvalidOperation` from `Decimal("")`
**Line:** `polymarket.py` (multiple places)

### Quick Fix
```python
# BEFORE (crashes on empty/NaN)
price = Decimal(str(value))

# AFTER (handles edge cases)
from pm_arb.core.parsing import SafeParser
price = SafeParser.decimal(value, default=Decimal("0"))
```

### 1-Minute Implementation
```python
# Create pm_arb/core/parsing.py with SafeParser class
from decimal import Decimal, InvalidOperation

def safe_decimal(value, default=Decimal("0")):
    if value is None or value == "":
        return default
    try:
        str_val = str(value).strip()
        if str_val.lower() in ("nan", "inf", "-inf"):
            return default
        return Decimal(str_val)
    except:
        return default

# Update all Decimal conversions in polymarket.py
price = safe_decimal(level[0], Decimal("0"))
```

### Test It
```python
pytest tests/core/test_parsing.py::TestSafeDecimalParsing
```

---

## 3. Binance Geo-blocking

**Error:** HTTP 451 (geo-blocked) or SSL errors
**Problem:** Single provider, no fallback

### Quick Fix
```python
# BEFORE (single provider, no fallback)
oracle = BinanceOracle()

# AFTER (multi-provider with fallback)
from pm_arb.adapters.oracles.multi_provider import MultiProviderOracle, OracleProvider

providers = [
    OracleProvider("binance", BinanceOracle(), priority=100),
    OracleProvider("coingecko", CoinGeckoOracle(), priority=50),
]
oracle = MultiProviderOracle(providers)
```

### 1-Minute Implementation
```python
# Create pm_arb/adapters/oracles/multi_provider.py
class MultiProviderOracle:
    def __init__(self, providers):
        self.providers = sorted(providers, key=lambda p: p.priority, reverse=True)

    async def get_current(self, symbol):
        for provider in self.providers:
            try:
                data = await provider.oracle.get_current(symbol)
                if data:
                    return data
            except:
                continue
        return None

# Update pilot.py
oracle = MultiProviderOracle([
    OracleProvider("binance", BinanceOracle(), priority=100),
    OracleProvider("coingecko", CoinGeckoOracle(), priority=50),
])
```

### Test It
```python
pytest tests/adapters/oracles/test_multi_provider.py::test_multi_provider_falls_back_on_failure
```

---

## 4. CoinGecko Rate Limits

**Error:** HTTP 429 (Too Many Requests)
**Cause:** Per-symbol API calls hit rate limits immediately

### Quick Fix
```python
# BEFORE (separate call per symbol → rate limit)
for symbol in ["BTC", "ETH", "SOL"]:
    await oracle.get_current(symbol)  # 3 API calls

# AFTER (batch all symbols in one call)
oracle.set_symbols(["BTC", "ETH", "SOL"])
# get_current() now triggers batch fetch for all
```

### 1-Minute Implementation
```python
# Add to coingecko.py (already exists in codebase)
class CoinGeckoOracle:
    def __init__(self):
        self._symbols = []
        self._cached_prices = {}
        self._cache_time = {}
        self._batcher = RateLimitBatcher(max_requests_per_minute=20)

    def set_symbols(self, symbols):
        self._symbols = symbols  # Configure once

    async def get_current(self, symbol):
        # First call triggers batch fetch for ALL symbols
        if symbol == self._symbols[0]:
            await self._fetch_batch()  # Single API call for all
        return self._cached_prices.get(symbol)

    async def _fetch_batch(self):
        await self._batcher.wait_for_slot()  # Respect rate limit
        # Fetch all symbols in one call
        response = await self._client.get(
            f"{API}/simple/price",
            params={"ids": ",".join(coin_ids), "vs_currencies": "usd"}
        )
```

### Test It
```python
pytest tests/adapters/oracles/test_coingecko_batching.py
```

---

## 5. Dashboard Async Event Loop

**Error:** `RuntimeError: There is already a running event loop`
**Cause:** `asyncio.run()` in Streamlit (already has event loop)

### Quick Fix
```python
# BEFORE (crashes in Streamlit)
import asyncio
async def get_summary():
    ...
result = asyncio.run(get_summary())  # ← WRONG in Streamlit

# AFTER (use sync database instead)
def get_summary():  # ← Synchronous
    db = get_db_service()
    return db.get_daily_summary()
```

### 1-Minute Implementation
```python
# Create pm_arb/dashboard/db_service.py
import psycopg  # Sync driver, not asyncpg

class DashboardDatabaseService:
    def __init__(self, database_url):
        self.database_url = database_url
        self._connection = None

    def _get_connection(self):
        if self._connection is None:
            self._connection = psycopg.connect(self.database_url)
        return self._connection

    def get_daily_summary(self, days=1):
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM paper_trades
                WHERE created_at >= NOW() - INTERVAL '{}' days
            """.format(days))
            return {"total_trades": cur.fetchone()[0]}

# Update app.py
@st.cache_resource
def get_db_service():
    return DashboardDatabaseService(settings.database_url)

def render_pilot_monitor():
    db = get_db_service()  # No asyncio!
    summary = db.get_daily_summary(days=1)  # Sync call
```

### Test It
```python
pytest tests/dashboard/test_db_service.py -v
```

---

## Prevention Checklist

Copy to your PR template:

```
### External API Integration Checklist
- [ ] Symbol format documented and validated at boundaries
- [ ] All Decimal conversions use SafeParser or defensive parsing
- [ ] Multi-provider architecture or explicit fallback documented
- [ ] Rate limits identified and batching/caching implemented
- [ ] No asyncio in main thread of web framework (Streamlit/Django)
- [ ] Integration tests include provider failure scenarios
- [ ] Assumptions documented in code comments
```

---

## Test All Fixes

```bash
# Run all prevention tests
pytest tests/ -v -k "symbol or parsing or multi_provider or batch or db_service"

# Or run integration test
pytest tests/integration/test_bug_prevention.py -v
```

---

## Files to Create (Minimal)

```
pm_arb/core/
  ├── validators.py          # SymbolValidator
  ├── parsing.py             # SafeParser
  ├── api_batcher.py         # RateLimitBatcher
  └── backoff.py             # exponential_backoff

pm_arb/adapters/oracles/
  ├── multi_provider.py      # MultiProviderOracle

pm_arb/dashboard/
  └── db_service.py          # DashboardDatabaseService

tests/
  ├── core/test_validators.py
  ├── core/test_parsing.py
  ├── core/test_api_batcher.py
  ├── adapters/oracles/test_multi_provider.py
  └── dashboard/test_db_service.py
```

---

## Deploy Order

1. **Parsing (Safe Decimals)** — 5 min, lowest risk
2. **Symbol Validation** — 10 min, update pilot.py
3. **Multi-Provider Oracle** — 20 min, add coingecko provider
4. **Rate Limit Batcher** — 15 min, update coingecko polling
5. **Dashboard DB Service** — 15 min, separate from asyncio
6. **Tests** — 30 min, add all test cases

**Total:** ~95 minutes for full implementation with tests

---

## Full Documentation

For complete implementation with all test cases and architecture details:
- **Comprehensive Guide:** `/docs/BUG_FIXES_AND_PREVENTION.md` (2811 lines)
- **Summary:** `/docs/BUG_FIXES_SUMMARY.md` (260 lines)
- **This Reference:** `/docs/QUICK_FIX_REFERENCE.md` (this file)

