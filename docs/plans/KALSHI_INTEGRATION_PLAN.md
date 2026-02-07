# Kalshi Integration Plan

**Date:** 2026-02-06
**Brainstorm:** [2026-02-06-kalshi-integration-brainstorm.md](../brainstorms/2026-02-06-kalshi-integration-brainstorm.md)
**Branch:** `feature/kalshi-integration`

## Overview

Replace Polymarket (US-restricted) with Kalshi (CFTC-regulated, US-legal) as the primary prediction market venue. Support all market categories (crypto, economics, weather, politics) with new oracle adapters for FRED and NOAA.

---

## Sprint 1: Interface Cleanup & Kalshi Adapter Foundation

**Goal:** Fix the broken `VenueAdapter` contract, add Kalshi credential management, and implement the core Kalshi adapter with read-only market data.

### Task 1.1: Fix VenueAdapter.place_order() Contract
**Files:** `src/pm_arb/adapters/venues/base.py`, `src/pm_arb/adapters/venues/polymarket.py`, `src/pm_arb/agents/live_executor.py`
**Description:**
- The base `VenueAdapter.place_order(request: TradeRequest) -> Trade` is correct
- `PolymarketAdapter.place_order()` uses a completely different signature with `# type: ignore[override]`
- Fix `PolymarketAdapter` to accept `TradeRequest` and translate internally to its token-based API:
  - Extract `token_id` from `request.market_id` via `get_token_id()`
  - Map `request.side` and `request.outcome` to token-side logic
  - Map `request.amount` and `request.max_price` to CLOB params
  - Return `Trade` (not `Order`) to match the base contract
- Update `LiveExecutorAgent._execute_trade()` to call `adapter.place_order(trade_request)` instead of the custom signature
- Generalize `LiveExecutorAgent._adapters` type from `dict[str, PolymarketAdapter]` to `dict[str, VenueAdapter]`
- Generalize `LiveExecutorAgent._get_adapter()` to instantiate the correct adapter class based on venue name

**Acceptance Criteria:**
- `PolymarketAdapter.place_order()` signature matches `VenueAdapter.place_order()`
- No `# type: ignore[override]` needed
- `LiveExecutorAgent` works with any `VenueAdapter` subclass
- Existing tests pass

**Validation:** `pytest tests/ -x`

### Task 1.2: Kalshi Credential Management
**Files:** `src/pm_arb/core/auth.py`, `src/pm_arb/core/config.py`, `.env.example`
**Description:**
- Add `KalshiCredentials` model to `auth.py`:
  - `api_key_id: str` - Kalshi API key ID
  - `private_key: str` - RSA private key (PEM format)
  - Validator for PEM format
  - `__str__` masks secrets
- Update `load_credentials()` to handle `venue="kalshi"`:
  - Load `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY` from env
  - Return `KalshiCredentials` (change return type to `PolymarketCredentials | KalshiCredentials`)
- Update `config.py` Settings:
  - Replace `kalshi_email`/`kalshi_password` with `kalshi_api_key_id`/`kalshi_private_key`
- Update `.env.example` with new Kalshi fields

**Acceptance Criteria:**
- `load_credentials("kalshi")` returns valid `KalshiCredentials`
- `load_credentials("polymarket")` still works unchanged
- Missing credentials raise `ValueError` with helpful message

**Validation:** `pytest tests/core/test_auth.py` (new tests for Kalshi creds)

### Task 1.3: Kalshi Adapter - Auth & Market Discovery
**Files:** `src/pm_arb/adapters/venues/kalshi.py` (new), `tests/adapters/venues/test_kalshi.py` (new)
**Description:**
Implement `KalshiAdapter(VenueAdapter)` with:
- **Auth (RSA-PSS signed requests):**
  - Sign each request with RSA-PSS using private key
  - Signature format: timestamp + method + path (no JWT rotation needed with RSA-PSS)
  - Headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-SIGNATURE`, `KALSHI-ACCESS-TIMESTAMP`
- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
- **`connect()`:** Initialize `httpx.AsyncClient`, verify connection with `GET /exchange/status`
- **`get_markets()`:** `GET /markets?status=open&limit=200`
  - Parse into `Market` model
  - Market ID format: `kalshi:{ticker}`
  - Map Kalshi prices (cents) to Decimal (divide by 100)
  - `yes_price` = yes_bid/100, `no_price` = (100 - yes_bid)/100
  - `yes_token_id` and `no_token_id` set to ticker (Kalshi uses tickers, not tokens)
- **`subscribe_prices()`:** No-op initially (polling mode)
- **`disconnect()`:** Close httpx client

**Kalshi API notes:**
- All monetary values in cents (balance) or centi-cents (positions)
- Markets are binary YES/NO
- Events contain multiple markets (e.g., "BTC price on Feb 6" has multiple strike prices)
- Tickers are structured: `BTCUSD-26FEB04-T104000`

**Acceptance Criteria:**
- `KalshiAdapter.get_markets()` returns `list[Market]` with correct prices
- Auth headers are correctly signed
- Connection/disconnection lifecycle works
- All tests use mock httpx responses (no real API calls)

**Validation:** `pytest tests/adapters/venues/test_kalshi.py -v`

### Task 1.4: Kalshi Adapter - Trading Operations
**Files:** `src/pm_arb/adapters/venues/kalshi.py`
**Description:**
Add trading methods to `KalshiAdapter`:
- **`place_order(request: TradeRequest) -> Trade`:**
  - `POST /orders` with body: `{ticker, action: "buy"/"sell", side: "yes"/"no", type: "market"/"limit", count, yes_price/no_price}`
  - Map `TradeRequest` fields to Kalshi order format
  - Convert prices to cents for Kalshi API
  - Return `Trade` with mapped status
- **`get_balance() -> Decimal`:**
  - `GET /balance` returns `{balance: <cents>}`
  - Convert cents to dollars: `Decimal(balance) / 100`
- **`get_order_book(market_id, outcome) -> OrderBook`:**
  - `GET /markets/{ticker}/orderbook`
  - Parse bids/asks into `OrderBook` model
  - Convert cent prices to Decimal

**Acceptance Criteria:**
- `place_order()` correctly maps TradeRequest to Kalshi API format
- Balance returns dollars (not cents)
- Order book has correct bid/ask structure
- Error handling: log errors, return rejected Trade on failure (per ADAPTER_CONVENTIONS.md)

**Validation:** `pytest tests/adapters/venues/test_kalshi.py -v`

---

## Sprint 2: Oracle Adapters (FRED + Weather)

**Goal:** Add oracle sources for economic and weather data to support non-crypto Kalshi markets.

### Task 2.1: FRED Oracle Adapter
**Files:** `src/pm_arb/adapters/oracles/fred.py` (new), `tests/adapters/oracles/test_fred.py` (new)
**Description:**
Implement `FredOracle(OracleAdapter)`:
- **API:** `https://api.stlouisfed.org/fred/series/observations`
- **Auth:** API key via query param `api_key` (from `FRED_API_KEY` env var)
- **`connect()`:** Initialize httpx client, validate API key with test request
- **`get_current(symbol) -> OracleData`:**
  - Map symbols to FRED series IDs:
    - `FED_RATE` -> `FEDFUNDS` (effective federal funds rate)
    - `CPI` -> `CPIAUCSL` (consumer price index)
    - `GDP` -> `GDP` (gross domestic product)
    - `UNEMPLOYMENT` -> `UNRATE` (unemployment rate)
    - `INITIAL_CLAIMS` -> `ICSA` (initial jobless claims)
  - Fetch latest observation: `sort_order=desc&limit=1&file_type=json`
  - Return `OracleData(source="fred", symbol=symbol, value=Decimal(observation_value))`
- **`subscribe(symbols)`:** Store symbols for polling
- **`supports_streaming`:** `False` (FRED is REST-only, data updates daily/monthly)

**Add to config.py:** `fred_api_key: str = ""`
**Add to .env.example:** `FRED_API_KEY=`

**Acceptance Criteria:**
- `FredOracle.get_current("FED_RATE")` returns valid `OracleData`
- All 5 economic indicators mapped
- Graceful handling of missing/stale data (FRED data is not real-time)
- Tests mock httpx responses

**Validation:** `pytest tests/adapters/oracles/test_fred.py -v`

### Task 2.2: Weather Oracle Adapter
**Files:** `src/pm_arb/adapters/oracles/weather.py` (new), `tests/adapters/oracles/test_weather.py` (new)
**Description:**
Implement `WeatherOracle(OracleAdapter)`:
- **API:** `https://api.weather.gov` (NWS API - no auth needed, just User-Agent header)
- **`connect()`:** Initialize httpx client with `User-Agent: pm-arbitrage/0.1.0`
- **`get_current(symbol) -> OracleData`:**
  - Symbol format: `TEMP_{STATION_ID}` (e.g., `TEMP_KNYC` for NYC)
  - Flow: `GET /stations/{station_id}/observations/latest`
  - Extract temperature from `properties.temperature.value` (Celsius)
  - Convert to Fahrenheit for US markets
  - Return `OracleData(source="weather", symbol=symbol, value=temperature_f)`
  - Also support: `WIND_{station}`, `PRECIP_{station}`
- **`subscribe(symbols)`:** Store symbols for polling
- **`supports_streaming`:** `False`
- **Station mapping for common Kalshi cities:**
  - NYC: `KNYC`, Miami: `KMIA`, Chicago: `KORD`, LA: `KLAX`

**Acceptance Criteria:**
- `WeatherOracle.get_current("TEMP_KNYC")` returns temperature in Fahrenheit
- Graceful handling of station not found, API errors
- Tests mock httpx responses

**Validation:** `pytest tests/adapters/oracles/test_weather.py -v`

### Task 2.3: Register New Oracle Adapters in Config
**Files:** `src/pm_arb/core/config.py`, `.env.example`
**Description:**
- Add `fred_api_key: str = ""` to Settings (if not done in 2.1)
- No config needed for Weather (no auth required)
- Add `active_venues: str = "kalshi"` setting to control which venues to activate
- Add `active_oracles: str = "binance,fred,weather"` setting

**Acceptance Criteria:**
- Config loads cleanly with new fields
- Backwards-compatible (existing .env files still work)

**Validation:** `pytest tests/core/test_config.py`

---

## Sprint 3: Market Matcher & Scanner Wiring

**Goal:** Wire Kalshi markets to the opportunity detection pipeline with expanded matching for economics and weather.

### Task 3.1: Extend MarketMatcher for Kalshi Tickers
**Files:** `src/pm_arb/core/market_matcher.py`, `tests/core/test_market_matcher.py` (new/update)
**Description:**
Kalshi tickers are structured and easier to parse than Polymarket titles:
- `BTCUSD-26FEB04-T104000` = BTC price at 10:40 UTC on Feb 4, 2026
- `KXFEDRATE-26MAR19-T4.50` = Fed rate >= 4.50% at March 19 FOMC meeting
- `KXHITEMP-NYC-26FEB06-T45` = NYC high temp >= 45°F on Feb 6

Add Kalshi-specific parsing:
- **New regex patterns** for Kalshi ticker format
- **`_parse_kalshi_ticker(market: Market) -> ParsedMarket | None`:**
  - Extract asset, threshold, direction from structured ticker
  - Map Kalshi-specific prefixes: `BTCUSD` -> crypto, `KXFEDRATE` -> FRED, `KXHITEMP` -> weather
- **Update `match_markets()`** to try Kalshi regex first (by venue), then existing Polymarket regex/LLM
- **New oracle mappings:**
  - Crypto: `BTC`, `ETH`, `SOL` -> Binance oracle (existing)
  - Fed rate: `FED_RATE` -> FRED oracle
  - CPI: `CPI` -> FRED oracle
  - Temperature: `TEMP_{city}` -> Weather oracle

**Acceptance Criteria:**
- Kalshi crypto tickers matched to Binance oracle
- Kalshi economics tickers matched to FRED oracle
- Kalshi weather tickers matched to Weather oracle
- Polymarket matching still works unchanged

**Validation:** `pytest tests/core/test_market_matcher.py -v`

### Task 3.2: Wire Kalshi into Pilot Orchestrator
**Files:** `src/pm_arb/pilot.py`
**Description:**
- Import `KalshiAdapter` and new oracle adapters
- Read `active_venues` config to determine which venues to start
- Create Kalshi adapter with credentials from `load_credentials("kalshi")`
- Create `VenueWatcherAgent` for Kalshi (name: `venue-watcher-kalshi`)
- Add `venue.kalshi.prices` to scanner's `venue_channels`
- Create FRED and Weather oracle agents:
  - `OracleAgent(oracle=FredOracle(), symbols=["FED_RATE", "CPI", "UNEMPLOYMENT", "GDP", "INITIAL_CLAIMS"], poll_interval=300)` (5-min polls, data is slow)
  - `OracleAgent(oracle=WeatherOracle(), symbols=["TEMP_KNYC", "TEMP_KMIA", "TEMP_KORD"], poll_interval=600)` (10-min polls)
- Add oracle channels to scanner: `oracle.fred.*`, `oracle.weather.*`
- Run `MarketMatcher.match_markets()` for Kalshi markets too
- Update `_validate_live_mode()` to validate Kalshi credentials when Kalshi is active venue

**Acceptance Criteria:**
- Kalshi watcher agent starts and polls markets
- FRED and Weather oracles start and poll data
- Scanner receives Kalshi price updates and oracle data
- Opportunities detected from Kalshi markets

**Validation:** `pytest tests/ -x` (all tests pass), manual integration test with `pm-arb pilot --paper`

### Task 3.3: Update Opportunity Scanner for Kalshi Fee Structure
**Files:** `src/pm_arb/agents/opportunity_scanner.py`
**Description:**
- Add Kalshi fee awareness:
  - Kalshi fees are series-specific (not the 15-min crypto fee model from Polymarket)
  - Add `_calculate_kalshi_fee()` method
  - For now, use a flat fee estimate (configurable in settings)
  - Later: fetch actual fees from `GET /exchange/series-fee-changes`
- Update `_calculate_net_edge()` to dispatch by venue:
  - `polymarket` -> existing fee logic
  - `kalshi` -> new Kalshi fee logic
- Kalshi-specific resolved market detection:
  - Check `market.end_date` and settlement status from market metadata

**Acceptance Criteria:**
- Fee calculation dispatches correctly by venue
- Edge calculations include Kalshi fees
- Tests cover both Polymarket and Kalshi fee paths

**Validation:** `pytest tests/agents/test_opportunity_scanner.py -v`

---

## Sprint 4: End-to-End Integration & Polish

**Goal:** Full integration test, CLI updates, dashboard visibility, and documentation.

### Task 4.1: Integration Test - Kalshi Full Flow
**Files:** `tests/integration/test_kalshi_flow.py` (new)
**Description:**
End-to-end test with mock Kalshi API:
1. VenueWatcherAgent polls mock Kalshi → publishes prices
2. OracleAgent (FRED) polls mock FRED → publishes economic data
3. Scanner detects oracle-lag opportunity on Kalshi economics market
4. Strategy generates trade request
5. Risk guardian approves
6. Paper executor simulates execution
- Use existing integration test patterns from `test_sprint4.py`

**Acceptance Criteria:**
- Full pipeline works end-to-end with Kalshi markets
- Oracle-lag detection works for economics markets
- Paper execution records trade correctly

**Validation:** `pytest tests/integration/test_kalshi_flow.py -v`

### Task 4.2: Update CLI for Multi-Venue Support
**Files:** `src/pm_arb/cli.py`
**Description:**
- Add `--venue` flag to relevant commands (`pilot`, `report`, `status`)
- `pm-arb pilot --venue kalshi` starts only Kalshi pipeline
- `pm-arb pilot --venue all` starts all active venues
- `pm-arb status` shows per-venue health
- `pm-arb report` shows per-venue trade history

**Acceptance Criteria:**
- CLI works with `--venue kalshi`, `--venue polymarket`, `--venue all`
- Default is `kalshi` (US-legal primary)

**Validation:** `pm-arb --help` shows new options, manual test

### Task 4.3: Update .env.example and README
**Files:** `.env.example`, `README.md`
**Description:**
- Update `.env.example` with all new fields (Kalshi API key, FRED API key, active venues/oracles)
- Update README with:
  - Kalshi setup instructions (get API key from Kalshi dashboard)
  - FRED API key setup
  - Configuration for venue selection
  - Updated architecture diagram showing multi-venue support

**Acceptance Criteria:**
- New user can set up Kalshi from README instructions
- `.env.example` documents all new fields with comments

**Validation:** Manual review

---

## Dependencies

```
Task 1.1 (fix interface) → Task 1.3, 1.4 (Kalshi adapter needs clean interface)
Task 1.2 (credentials)  → Task 1.3 (adapter needs auth)
Task 1.3 (market data)  → Task 3.1 (matcher needs markets)
Task 1.4 (trading)      → Task 4.1 (integration test)
Task 2.1 (FRED)         → Task 3.1 (matcher needs oracles)
Task 2.2 (Weather)      → Task 3.1 (matcher needs oracles)
Task 3.1 (matcher)      → Task 3.2 (pilot wiring)
Task 3.2 (pilot wiring) → Task 4.1 (integration test)
```

**Parallelizable:**
- Tasks 1.1 and 1.2 can run in parallel
- Tasks 2.1 and 2.2 can run in parallel
- Tasks 2.1/2.2 can run in parallel with Tasks 1.3/1.4
- Tasks 4.2 and 4.3 can run in parallel

## Risk Mitigation

1. **Kalshi API rate limits unknown** - Start with conservative polling (5s for markets, 30s for order books). Add backoff/retry logic in adapter.
2. **FRED data staleness** - Economic data updates daily/monthly. Set long poll intervals (5-10 min). Strategy must account for data freshness.
3. **Weather API reliability** - NWS API has no SLA. Add fallback to alternative weather source if needed.
4. **Kalshi fee structure** - Start with flat fee estimate, add dynamic fee fetching in a later sprint.
