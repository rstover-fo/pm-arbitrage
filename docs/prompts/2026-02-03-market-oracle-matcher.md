# Market-Oracle Matcher Feature

## Context

The pm-arbitrage project is a prediction market arbitrage bot that:
- Fetches markets from Polymarket (100+ active markets)
- Fetches crypto prices from CoinGecko (BTC, ETH)
- Looks for oracle lag opportunities (market price lags behind real-world data)

**Current state:** The pilot runs successfully but **never detects opportunities** because there's a missing link between markets and oracles.

## The Problem

The `OpportunityScannerAgent` has methods to register market-oracle mappings:

```python
scanner.register_market_oracle_mapping(
    market_id="polymarket:12345",
    oracle_symbol="BTC",
    threshold=Decimal("100000"),  # $100k
    direction="above",
)
```

But **nothing calls these methods**. The pilot:
1. Fetches Polymarket markets (titles like "Will BTC be above $100,000 on Feb 28?")
2. Fetches CoinGecko prices (BTC = $97,842)
3. Never connects them together

## What We Need

A **MarketMatcher** component that:

1. **Parses market titles** to extract:
   - Asset (BTC, ETH, SOL, etc.)
   - Threshold value ($100,000, $5,000, etc.)
   - Direction (above/below)
   - Expiry date (optional)

2. **Registers mappings** with the OpportunityScannerAgent

3. **Handles edge cases:**
   - Markets with non-standard phrasing
   - Multi-outcome markets (BTC price ranges)
   - Markets that don't track crypto at all (politics, sports)

## Example Market Titles from Polymarket

```
"Will BTC be above $100,000 on February 28?"
"Bitcoin above $95,000 on March 1?"
"ETH price above $4,000 at end of February?"
"Will Ethereum reach $5,000 in Q1 2025?"
```

## Technical Constraints

- **Location:** `src/pm_arb/core/market_matcher.py` or similar
- **Integration point:** Called in `pilot.py` after `OpportunityScannerAgent` is created
- **Pattern matching:** Regex or LLM-based parsing (start with regex)
- **Testing:** Unit tests with various market title formats

## Files to Review

- `src/pm_arb/pilot.py` - Where agents are created (lines 86-126)
- `src/pm_arb/agents/opportunity_scanner.py` - The `register_market_oracle_mapping()` method (lines 58-71)
- `src/pm_arb/adapters/venues/polymarket.py` - How markets are fetched and parsed

## Acceptance Criteria

1. Given Polymarket markets with crypto threshold titles, the matcher extracts asset/threshold/direction
2. Matcher registers mappings with the scanner on startup
3. Scanner can now detect oracle lag when BTC price crosses a threshold but market hasn't updated
4. Unit tests cover common title patterns and edge cases
5. Logs show which markets were matched and which were skipped

## Starting Command

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
```

## Session Goal

Plan and implement the MarketMatcher feature so the pilot can actually detect oracle lag opportunities.
