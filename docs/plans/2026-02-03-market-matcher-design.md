# Market-Oracle Matcher Design

**Date:** 2026-02-03
**Status:** Approved
**Author:** Rob + Claude

## Problem

The pm-arbitrage pilot fetches Polymarket markets and CoinGecko prices but never connects them. The `OpportunityScannerAgent` has `register_market_oracle_mapping()` but nothing calls it. Result: zero oracle lag opportunities detected.

## Solution

A `MarketMatcher` class that:
1. Parses market titles to extract asset/threshold/direction
2. Uses regex for common patterns, LLM fallback for edge cases
3. Registers mappings with the scanner at startup

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where to call | `pilot.py` at startup | Simple, mappings ready before scanning |
| Parsing strategy | Regex + LLM fallback | Fast for common cases, flexible for edge cases |
| LLM batching | Async batch after regex pass | One API call, 100% mappings before scan starts |
| LLM provider | Claude (Anthropic API) | Already in ecosystem |

## Data Structures

```python
# src/pm_arb/core/market_matcher.py

from dataclasses import dataclass
from decimal import Decimal

@dataclass
class ParsedMarket:
    """Result of parsing a market title."""
    market_id: str
    asset: str | None          # "BTC", "ETH", etc.
    threshold: Decimal | None  # 100000, 5000, etc.
    direction: str | None      # "above" or "below"
    expiry: str | None         # Raw date string if found
    parse_method: str          # "regex" or "llm"

@dataclass
class MatchResult:
    """Summary of matching run."""
    total_markets: int
    matched: int
    skipped: int  # Non-crypto markets
    failed: int   # Parse failures
    matched_markets: list[ParsedMarket]
```

## Class Interface

```python
class MarketMatcher:
    """Parses market titles and registers oracle mappings."""

    ASSET_ALIASES: dict[str, str] = {
        "btc": "BTC", "bitcoin": "BTC",
        "eth": "ETH", "ethereum": "ETH",
        "sol": "SOL", "solana": "SOL",
    }

    def __init__(
        self,
        scanner: OpportunityScannerAgent,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._scanner = scanner
        self._api_key = anthropic_api_key

    async def match_markets(self, markets: list[Market]) -> MatchResult:
        """Parse all markets and register mappings with scanner.

        1. Try regex on each market
        2. Batch unparsed crypto titles to LLM
        3. Register all successful parses with scanner
        """
        ...

    def _parse_with_regex(self, market: Market) -> ParsedMarket | None:
        """Fast regex extraction. Returns None if no match."""
        ...

    def _is_crypto_market(self, title: str) -> bool:
        """Check if title mentions a supported crypto asset."""
        ...

    async def _parse_with_llm(self, markets: list[Market]) -> list[ParsedMarket]:
        """Batch LLM fallback for titles regex couldn't handle."""
        ...
```

## Regex Patterns

Target titles:
```
"Will BTC be above $100,000 on February 28?"
"Bitcoin above $95,000 on March 1?"
"ETH price above $4,000 at end of February?"
"Will Ethereum reach $5,000 in Q1 2025?"
"BTC below $90,000 by March?"
```

Pattern:
```python
CRYPTO_PATTERN = re.compile(
    r"(BTC|Bitcoin|ETH|Ethereum|SOL|Solana)"  # Asset
    r".*?"                                      # Filler
    r"(above|below|reach|over|under)"           # Direction
    r".*?"                                      # Filler
    r"\$([0-9,]+)",                             # Threshold
    re.IGNORECASE
)
```

Direction normalization:
- `reach`, `over`, `above` → `"above"`
- `under`, `below` → `"below"`

## LLM Fallback

Prompt structure:
```
Extract crypto price threshold info from these market titles.
Return JSON array with: asset, threshold, direction (above/below), or null if not a crypto threshold market.

Titles:
1. "Will the price of Bitcoin exceed one hundred thousand dollars?"
2. "Crypto winter: ETH under 3k by April?"

Response format:
[
  {"asset": "BTC", "threshold": 100000, "direction": "above"},
  {"asset": "ETH", "threshold": 3000, "direction": "below"}
]
```

## Integration

In `pilot.py`:

```python
async def _create_agents(self) -> list[BaseAgent]:
    polymarket_adapter = PolymarketAdapter()
    await polymarket_adapter.connect()

    # ... create scanner ...

    scanner = OpportunityScannerAgent(
        self._redis_url,
        venue_channels=venue_channels,
        oracle_channels=oracle_channels,
    )

    # Match markets to oracles before scanning starts
    matcher = MarketMatcher(scanner, anthropic_api_key=settings.anthropic_api_key)
    markets = await polymarket_adapter.get_markets()
    result = await matcher.match_markets(markets)
    logger.info(
        "market_matching_complete",
        total=result.total_markets,
        matched=result.matched,
        skipped=result.skipped,
        failed=result.failed,
    )

    return [venue_watcher, oracle_agent, scanner, ...]
```

Note: `_create_agents()` becomes async to support the market fetch.

## Test Plan

| Test | Input | Expected |
|------|-------|----------|
| `test_regex_parses_btc_above` | "Will BTC be above $100,000..." | asset=BTC, threshold=100000, direction=above |
| `test_regex_parses_ethereum_alias` | "Ethereum above $4,000" | asset=ETH |
| `test_regex_parses_reach_as_above` | "reach $5,000" | direction=above |
| `test_regex_handles_commas` | "$100,000" | threshold=100000 |
| `test_regex_returns_none_for_politics` | "Will Biden win?" | None |
| `test_is_crypto_market_true` | "BTC price prediction" | True |
| `test_is_crypto_market_false` | "Super Bowl winner" | False |
| `test_llm_fallback_called_for_unparsed` | Unusual phrasing | LLM called |
| `test_llm_batch_processes_multiple` | 3 unparsed titles | Single API call |
| `test_match_result_counts` | Mixed markets | Correct tallies |
| `test_registers_with_scanner` | Parsed market | scanner._market_thresholds populated |
| `test_skips_non_crypto_no_llm` | Politics market | Not sent to LLM |

## File Locations

- **Implementation:** `src/pm_arb/core/market_matcher.py`
- **Tests:** `tests/core/test_market_matcher.py`
- **Config:** Add `anthropic_api_key` to `src/pm_arb/core/config.py`

## Acceptance Criteria

1. ✅ Regex parses common crypto threshold titles
2. ✅ LLM fallback handles unusual phrasing
3. ✅ Non-crypto markets skipped (not sent to LLM)
4. ✅ Mappings registered with scanner at startup
5. ✅ Logs show matched/skipped/failed counts
6. ✅ Scanner can detect oracle lag opportunities
