# Kalshi Integration Brainstorm

**Date:** 2026-02-06
**Status:** Decided
**Author:** Rob Stover

## Context

Polymarket is restricted for US-based users. Kalshi is a CFTC-regulated US prediction market exchange with a REST/WebSocket API. The pm-arbitrage system needs Kalshi as its US-legal primary venue.

## What We're Building

A `KalshiAdapter` that plugs into the existing agent-based architecture as a drop-in venue replacement, plus new oracle adapters (FRED, weather) to support Kalshi's broader market categories beyond crypto.

## Why This Approach (Approach A: Clean Adapter Swap)

- **Minimal disruption:** Same agent pipeline (watcher -> scanner -> strategy -> risk -> executor), just a new adapter
- **Fixes tech debt:** The `VenueAdapter.place_order()` interface is currently broken (Polymarket overrides with incompatible signature). Fix this first, then Kalshi implements the clean contract
- **Polymarket stays intact:** Keep it for potential future cross-platform arb or non-US deployment
- **YAGNI:** No need for a full abstraction overhaul with only two venues

### Rejected Approaches

- **B: Venue Abstraction Overhaul** - Over-engineering for two venues. Delays getting Kalshi working.
- **C: Parallel Pipeline** - Code duplication, harder to do cross-platform arb later.

## Key Decisions

### 1. Kalshi as US-legal replacement (not cross-platform complement)
Kalshi becomes the primary venue for US users. Polymarket code stays but is not actively used.

### 2. All market categories from day one
Target crypto, economics, weather, and politics markets on Kalshi - not just crypto.

### 3. Direct httpx client (no SDK dependency)
Build our own async Kalshi client using httpx, matching the existing Polymarket adapter pattern. Full control, no external dependencies, consistent with codebase style.

### 4. FRED + Weather oracle APIs for non-crypto markets
- **FRED API** (Federal Reserve Economic Data) for economics: Fed rate, CPI, GDP, unemployment
- **NOAA/weather API** for weather markets
- Existing Binance/CoinGecko oracles continue for crypto markets

### 5. Fix VenueAdapter.place_order() interface first
Standardize on `place_order(request: TradeRequest) -> Trade` as the base contract. Polymarket adapter must conform (internal translation from TradeRequest to its token-based API). Then Kalshi implements the same clean interface.

## Kalshi API Details

- **Base URL:** `https://api.elections.kalshi.com/trade-api/v2`
- **Auth:** RSA-PSS signed requests OR API key + private key. JWT tokens expire every 30 minutes - adapter needs auto-refresh.
- **Market structure:** Events -> Series -> Markets. Tickers like `BTCUSD-26FEB04-T104000`
- **Order book:** Central limit order book, USD-settled
- **Key endpoints:** `/markets`, `/events`, `/orders`, `/portfolio`
- **Market ID convention:** `kalshi:{ticker}` (e.g., `kalshi:BTCUSD-26FEB04-T104000`)

### Sources

- [Kalshi Python SDK Quickstart](https://docs.kalshi.com/sdks/python/quickstart)
- [Kalshi API First Request](https://docs.kalshi.com/getting_started/making_your_first_request)
- [aiokalshi - Async client](https://github.com/the-odds-company/aiokalshi)
- [kalshi-python on PyPI](https://pypi.org/project/kalshi-python/)

## Scope of Work (High Level)

### Phase 1: Interface Cleanup
- Fix `VenueAdapter.place_order()` signature to use `TradeRequest`
- Update `PolymarketAdapter` to conform (translate internally)
- Update `LiveExecutorAgent` to use the generic interface
- Generalize `load_credentials()` in auth.py

### Phase 2: Kalshi Adapter
- Implement `KalshiAdapter` with httpx
  - JWT auth with auto-refresh (30-min expiry)
  - Market discovery (`get_markets()`)
  - Price polling (`subscribe_prices()`)
  - Order placement (`place_order()`)
  - Balance checking (`get_balance()`)
  - Order book retrieval (`get_order_book()`)
- Add `KalshiCredentials` to auth.py
- Market ID format: `kalshi:{ticker}`

### Phase 3: New Oracle Adapters
- `FredOracle` - FRED API for economic indicators (free API key)
- `WeatherOracle` - NOAA API for weather data (free)
- Register new market-oracle mappings in `MarketMatcher`

### Phase 4: Wiring
- Add Kalshi `VenueWatcherAgent` in pilot.py
- Add `venue.kalshi.prices` channel to opportunity scanner
- Extend `MarketMatcher` regex/LLM for Kalshi market title formats
- Update CLI and dashboard for Kalshi visibility

## Open Questions

1. **Kalshi rate limits** - What are the API rate limits? May need throttling in the adapter.
2. **Market matching quality** - Kalshi ticker format is structured (contains date/threshold). May be easier to parse than Polymarket titles. Need to investigate.
3. **Fee structure impact** - Kalshi fees differ from Polymarket. Need to factor into edge calculations in strategies.
4. **WebSocket support** - Does Kalshi offer WebSocket streaming for prices, or REST-only? Affects polling frequency.
5. **Paper trading** - Does Kalshi have a sandbox/demo environment for testing?

## Next Steps

Run `/workflows:plan` to create a detailed sprint plan from this brainstorm.
