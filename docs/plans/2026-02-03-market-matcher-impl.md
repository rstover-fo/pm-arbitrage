# Market-Oracle Matcher Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Parse Polymarket titles to extract crypto threshold info and register mappings with OpportunityScannerAgent so the pilot can detect oracle lag opportunities.

**Architecture:** A `MarketMatcher` class with regex-first parsing and Claude LLM fallback. Called in `pilot.py` at startup before agents begin scanning. Data classes capture parsed results for logging/debugging.

**Tech Stack:** Python 3.11+, pydantic (dataclasses), re (regex), anthropic SDK (LLM fallback), pytest (testing)

---

## Task 1: Create ParsedMarket and MatchResult Data Classes

**Files:**
- Create: `src/pm_arb/core/market_matcher.py`
- Test: `tests/core/test_market_matcher.py`

**Step 1: Write the failing test**

Create `tests/core/test_market_matcher.py`:

```python
"""Tests for MarketMatcher."""

from decimal import Decimal

from pm_arb.core.market_matcher import MatchResult, ParsedMarket


class TestParsedMarket:
    """Tests for ParsedMarket dataclass."""

    def test_creates_with_all_fields(self) -> None:
        """Should create ParsedMarket with all fields."""
        parsed = ParsedMarket(
            market_id="polymarket:123",
            asset="BTC",
            threshold=Decimal("100000"),
            direction="above",
            expiry="February 28",
            parse_method="regex",
        )
        assert parsed.market_id == "polymarket:123"
        assert parsed.asset == "BTC"
        assert parsed.threshold == Decimal("100000")
        assert parsed.direction == "above"
        assert parsed.expiry == "February 28"
        assert parsed.parse_method == "regex"

    def test_creates_with_none_values(self) -> None:
        """Should allow None for optional fields."""
        parsed = ParsedMarket(
            market_id="polymarket:456",
            asset=None,
            threshold=None,
            direction=None,
            expiry=None,
            parse_method="regex",
        )
        assert parsed.asset is None
        assert parsed.threshold is None


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_creates_with_counts(self) -> None:
        """Should create MatchResult with counts."""
        result = MatchResult(
            total_markets=100,
            matched=25,
            skipped=70,
            failed=5,
            matched_markets=[],
        )
        assert result.total_markets == 100
        assert result.matched == 25
        assert result.skipped == 70
        assert result.failed == 5
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'pm_arb.core.market_matcher'`

**Step 3: Write minimal implementation**

Create `src/pm_arb/core/market_matcher.py`:

```python
"""Market-Oracle Matcher - parses market titles and registers oracle mappings."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ParsedMarket:
    """Result of parsing a market title."""

    market_id: str
    asset: str | None
    threshold: Decimal | None
    direction: str | None  # "above" or "below"
    expiry: str | None
    parse_method: str  # "regex" or "llm"


@dataclass
class MatchResult:
    """Summary of matching run."""

    total_markets: int
    matched: int
    skipped: int  # Non-crypto markets
    failed: int  # Parse failures
    matched_markets: list[ParsedMarket]
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py -v`

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/core/market_matcher.py tests/core/test_market_matcher.py
git commit -m "feat(matcher): add ParsedMarket and MatchResult data classes"
```

---

## Task 2: Add Asset Alias Mapping

**Files:**
- Modify: `src/pm_arb/core/market_matcher.py`
- Test: `tests/core/test_market_matcher.py`

**Step 1: Write the failing test**

Add to `tests/core/test_market_matcher.py`:

```python
from pm_arb.core.market_matcher import MarketMatcher


class TestAssetAliases:
    """Tests for asset alias resolution."""

    def test_resolves_btc_lowercase(self) -> None:
        """Should resolve 'btc' to 'BTC'."""
        assert MarketMatcher.ASSET_ALIASES["btc"] == "BTC"

    def test_resolves_bitcoin(self) -> None:
        """Should resolve 'bitcoin' to 'BTC'."""
        assert MarketMatcher.ASSET_ALIASES["bitcoin"] == "BTC"

    def test_resolves_ethereum(self) -> None:
        """Should resolve 'ethereum' to 'ETH'."""
        assert MarketMatcher.ASSET_ALIASES["ethereum"] == "ETH"

    def test_resolves_solana(self) -> None:
        """Should resolve 'solana' to 'SOL'."""
        assert MarketMatcher.ASSET_ALIASES["solana"] == "SOL"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestAssetAliases -v`

Expected: FAIL with `ImportError: cannot import name 'MarketMatcher'`

**Step 3: Write minimal implementation**

Add to `src/pm_arb/core/market_matcher.py`:

```python
class MarketMatcher:
    """Parses market titles and registers oracle mappings."""

    ASSET_ALIASES: dict[str, str] = {
        "btc": "BTC",
        "bitcoin": "BTC",
        "eth": "ETH",
        "ethereum": "ETH",
        "sol": "SOL",
        "solana": "SOL",
    }
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestAssetAliases -v`

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/core/market_matcher.py tests/core/test_market_matcher.py
git commit -m "feat(matcher): add asset alias mapping"
```

---

## Task 3: Implement _is_crypto_market Helper

**Files:**
- Modify: `src/pm_arb/core/market_matcher.py`
- Test: `tests/core/test_market_matcher.py`

**Step 1: Write the failing test**

Add to `tests/core/test_market_matcher.py`:

```python
class TestIsCryptoMarket:
    """Tests for _is_crypto_market helper."""

    def test_btc_is_crypto(self) -> None:
        """Should identify BTC market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Will BTC be above $100,000?") is True

    def test_bitcoin_is_crypto(self) -> None:
        """Should identify Bitcoin market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Bitcoin above $95,000") is True

    def test_ethereum_is_crypto(self) -> None:
        """Should identify Ethereum market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("ETH price above $4,000") is True

    def test_politics_not_crypto(self) -> None:
        """Should reject politics market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Will Biden win?") is False

    def test_sports_not_crypto(self) -> None:
        """Should reject sports market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Super Bowl winner 2026?") is False

    def test_case_insensitive(self) -> None:
        """Should match regardless of case."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("BITCOIN above $100k") is True
        assert matcher._is_crypto_market("ethereum BELOW $3000") is True
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestIsCryptoMarket -v`

Expected: FAIL with `TypeError: MarketMatcher() takes no arguments` or similar

**Step 3: Write minimal implementation**

Update `MarketMatcher` in `src/pm_arb/core/market_matcher.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent


@dataclass
class ParsedMarket:
    """Result of parsing a market title."""

    market_id: str
    asset: str | None
    threshold: Decimal | None
    direction: str | None
    expiry: str | None
    parse_method: str


@dataclass
class MatchResult:
    """Summary of matching run."""

    total_markets: int
    matched: int
    skipped: int
    failed: int
    matched_markets: list[ParsedMarket]


class MarketMatcher:
    """Parses market titles and registers oracle mappings."""

    ASSET_ALIASES: dict[str, str] = {
        "btc": "BTC",
        "bitcoin": "BTC",
        "eth": "ETH",
        "ethereum": "ETH",
        "sol": "SOL",
        "solana": "SOL",
    }

    def __init__(
        self,
        scanner: OpportunityScannerAgent,
        anthropic_api_key: str | None = None,
    ) -> None:
        self._scanner = scanner
        self._api_key = anthropic_api_key

    def _is_crypto_market(self, title: str) -> bool:
        """Check if title mentions a supported crypto asset."""
        title_lower = title.lower()
        return any(alias in title_lower for alias in self.ASSET_ALIASES)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestIsCryptoMarket -v`

Expected: PASS (6 tests)

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/core/market_matcher.py tests/core/test_market_matcher.py
git commit -m "feat(matcher): add _is_crypto_market helper"
```

---

## Task 4: Implement Regex Parser

**Files:**
- Modify: `src/pm_arb/core/market_matcher.py`
- Test: `tests/core/test_market_matcher.py`

**Step 1: Write the failing test**

Add to `tests/core/test_market_matcher.py`:

```python
from pm_arb.core.models import Market


class TestParseWithRegex:
    """Tests for _parse_with_regex."""

    def test_parses_btc_above(self) -> None:
        """Should parse 'Will BTC be above $100,000 on February 28?'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:123",
            venue="polymarket",
            external_id="123",
            title="Will BTC be above $100,000 on February 28?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("100000")
        assert result.direction == "above"
        assert result.parse_method == "regex"

    def test_parses_bitcoin_alias(self) -> None:
        """Should parse 'Bitcoin above $95,000'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:456",
            venue="polymarket",
            external_id="456",
            title="Bitcoin above $95,000 on March 1?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("95000")

    def test_parses_eth_above(self) -> None:
        """Should parse 'ETH price above $4,000'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:789",
            venue="polymarket",
            external_id="789",
            title="ETH price above $4,000 at end of February?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.threshold == Decimal("4000")
        assert result.direction == "above"

    def test_parses_reach_as_above(self) -> None:
        """Should parse 'reach' as direction='above'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:111",
            venue="polymarket",
            external_id="111",
            title="Will Ethereum reach $5,000 in Q1 2025?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.direction == "above"
        assert result.threshold == Decimal("5000")

    def test_parses_below(self) -> None:
        """Should parse 'below' direction."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:222",
            venue="polymarket",
            external_id="222",
            title="BTC below $90,000 by March?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.direction == "below"
        assert result.threshold == Decimal("90000")

    def test_handles_commas_in_price(self) -> None:
        """Should strip commas from price."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:333",
            venue="polymarket",
            external_id="333",
            title="Will BTC be above $1,000,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.threshold == Decimal("1000000")

    def test_returns_none_for_politics(self) -> None:
        """Should return None for non-crypto market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:444",
            venue="polymarket",
            external_id="444",
            title="Will Biden win the 2024 election?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is None

    def test_returns_none_for_crypto_without_threshold(self) -> None:
        """Should return None if crypto mentioned but no threshold pattern."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:555",
            venue="polymarket",
            external_id="555",
            title="Will Bitcoin ETF be approved?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestParseWithRegex -v`

Expected: FAIL with `AttributeError: 'MarketMatcher' object has no attribute '_parse_with_regex'`

**Step 3: Write minimal implementation**

Add to `MarketMatcher` class in `src/pm_arb/core/market_matcher.py`:

```python
import re

# Add at module level, after imports:
# Regex pattern for crypto threshold markets
CRYPTO_PATTERN = re.compile(
    r"(BTC|Bitcoin|ETH|Ethereum|SOL|Solana)"  # Asset
    r".*?"  # Filler
    r"(above|below|reach|over|under)"  # Direction
    r".*?"  # Filler
    r"\$([0-9,]+)",  # Threshold
    re.IGNORECASE,
)

# Direction normalization
DIRECTION_MAP: dict[str, str] = {
    "above": "above",
    "over": "above",
    "reach": "above",
    "below": "below",
    "under": "below",
}
```

Add method to `MarketMatcher`:

```python
    def _parse_with_regex(self, market: Market) -> ParsedMarket | None:
        """Fast regex extraction. Returns None if no match."""
        match = CRYPTO_PATTERN.search(market.title)
        if not match:
            return None

        asset_raw = match.group(1).lower()
        asset = self.ASSET_ALIASES.get(asset_raw, asset_raw.upper())

        direction_raw = match.group(2).lower()
        direction = DIRECTION_MAP.get(direction_raw, "above")

        threshold_raw = match.group(3).replace(",", "")
        threshold = Decimal(threshold_raw)

        return ParsedMarket(
            market_id=market.id,
            asset=asset,
            threshold=threshold,
            direction=direction,
            expiry=None,  # Could extract date later
            parse_method="regex",
        )
```

Also add the import at the top:

```python
from pm_arb.core.models import Market
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestParseWithRegex -v`

Expected: PASS (8 tests)

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/core/market_matcher.py tests/core/test_market_matcher.py
git commit -m "feat(matcher): implement regex parser for crypto threshold markets"
```

---

## Task 5: Implement LLM Fallback Parser

**Files:**
- Modify: `src/pm_arb/core/market_matcher.py`
- Test: `tests/core/test_market_matcher.py`

**Step 1: Write the failing test**

Add to `tests/core/test_market_matcher.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestParseWithLLM:
    """Tests for _parse_with_llm."""

    @pytest.mark.asyncio
    async def test_calls_anthropic_with_batch(self) -> None:
        """Should batch multiple titles in one API call."""
        matcher = MarketMatcher(scanner=None, anthropic_api_key="test-key")  # type: ignore[arg-type]

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Will the price of Bitcoin exceed one hundred thousand dollars?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:222",
                venue="polymarket",
                external_id="222",
                title="Crypto winter: ETH under 3k by April?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='[{"asset": "BTC", "threshold": 100000, "direction": "above"}, {"asset": "ETH", "threshold": 3000, "direction": "below"}]'
            )
        ]

        with patch("pm_arb.core.market_matcher.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            results = await matcher._parse_with_llm(markets)

        assert len(results) == 2
        assert results[0].asset == "BTC"
        assert results[0].threshold == Decimal("100000")
        assert results[0].direction == "above"
        assert results[0].parse_method == "llm"
        assert results[1].asset == "ETH"
        assert results[1].threshold == Decimal("3000")
        assert results[1].direction == "below"

    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self) -> None:
        """Should return empty list if no API key configured."""
        matcher = MarketMatcher(scanner=None, anthropic_api_key=None)  # type: ignore[arg-type]

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Unusual crypto phrasing",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        results = await matcher._parse_with_llm(markets)
        assert results == []

    @pytest.mark.asyncio
    async def test_handles_llm_returning_null(self) -> None:
        """Should skip markets where LLM returns null."""
        matcher = MarketMatcher(scanner=None, anthropic_api_key="test-key")  # type: ignore[arg-type]

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Some weird market",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[null]")]

        with patch("pm_arb.core.market_matcher.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            results = await matcher._parse_with_llm(markets)

        assert results == []
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestParseWithLLM -v`

Expected: FAIL with `AttributeError: 'MarketMatcher' object has no attribute '_parse_with_llm'`

**Step 3: Write minimal implementation**

Add import at top of `src/pm_arb/core/market_matcher.py`:

```python
import json

import anthropic
import structlog

logger = structlog.get_logger()
```

Add method to `MarketMatcher`:

```python
    async def _parse_with_llm(self, markets: list[Market]) -> list[ParsedMarket]:
        """Batch LLM fallback for titles regex couldn't handle."""
        if not self._api_key or not markets:
            return []

        # Build prompt
        titles_text = "\n".join(
            f"{i+1}. \"{m.title}\"" for i, m in enumerate(markets)
        )

        prompt = f"""Extract crypto price threshold info from these market titles.
Return a JSON array with one object per title. Each object should have:
- "asset": The crypto symbol (BTC, ETH, SOL) or null if not a crypto threshold market
- "threshold": The price threshold as a number (no commas) or null
- "direction": "above" or "below" or null

Titles:
{titles_text}

Return ONLY the JSON array, no other text."""

        try:
            client = anthropic.AsyncAnthropic(api_key=self._api_key)
            response = await client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse response
            response_text = response.content[0].text
            parsed_data = json.loads(response_text)

            results = []
            for i, item in enumerate(parsed_data):
                if item is None or item.get("asset") is None:
                    continue

                results.append(
                    ParsedMarket(
                        market_id=markets[i].id,
                        asset=item["asset"],
                        threshold=Decimal(str(item["threshold"])) if item.get("threshold") else None,
                        direction=item.get("direction"),
                        expiry=None,
                        parse_method="llm",
                    )
                )

            return results

        except Exception as e:
            logger.error("llm_parse_failed", error=str(e))
            return []
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestParseWithLLM -v`

Expected: PASS (3 tests)

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/core/market_matcher.py tests/core/test_market_matcher.py
git commit -m "feat(matcher): implement LLM fallback parser"
```

---

## Task 6: Implement match_markets Main Method

**Files:**
- Modify: `src/pm_arb/core/market_matcher.py`
- Test: `tests/core/test_market_matcher.py`

**Step 1: Write the failing test**

Add to `tests/core/test_market_matcher.py`:

```python
class TestMatchMarkets:
    """Tests for match_markets main method."""

    @pytest.mark.asyncio
    async def test_matches_regex_parseable_markets(self) -> None:
        """Should match markets that regex can parse."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key=None)

        markets = [
            Market(
                id="polymarket:123",
                venue="polymarket",
                external_id="123",
                title="Will BTC be above $100,000 on February 28?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:456",
                venue="polymarket",
                external_id="456",
                title="ETH price above $4,000?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        result = await matcher.match_markets(markets)

        assert result.total_markets == 2
        assert result.matched == 2
        assert result.skipped == 0
        assert result.failed == 0
        assert len(result.matched_markets) == 2

    @pytest.mark.asyncio
    async def test_skips_non_crypto_markets(self) -> None:
        """Should skip non-crypto markets without calling LLM."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key="test-key")

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Will Biden win?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:222",
                venue="polymarket",
                external_id="222",
                title="Super Bowl 2026 winner?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        with patch.object(matcher, "_parse_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            result = await matcher.match_markets(markets)

        assert result.total_markets == 2
        assert result.matched == 0
        assert result.skipped == 2
        # LLM should NOT be called for non-crypto markets
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_registers_mappings_with_scanner(self) -> None:
        """Should call scanner.register_market_oracle_mapping for each match."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key=None)

        markets = [
            Market(
                id="polymarket:123",
                venue="polymarket",
                external_id="123",
                title="Will BTC be above $100,000?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        await matcher.match_markets(markets)

        mock_scanner.register_market_oracle_mapping.assert_called_once_with(
            market_id="polymarket:123",
            oracle_symbol="BTC",
            threshold=Decimal("100000"),
            direction="above",
        )

    @pytest.mark.asyncio
    async def test_uses_llm_fallback_for_unparsed_crypto(self) -> None:
        """Should call LLM for crypto markets that regex couldn't parse."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key="test-key")

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Will BTC be above $100,000?",  # Regex parseable
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:222",
                venue="polymarket",
                external_id="222",
                title="Bitcoin exceeds one hundred thousand USD?",  # Needs LLM
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        with patch.object(matcher, "_parse_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = [
                ParsedMarket(
                    market_id="polymarket:222",
                    asset="BTC",
                    threshold=Decimal("100000"),
                    direction="above",
                    expiry=None,
                    parse_method="llm",
                )
            ]
            result = await matcher.match_markets(markets)

        assert result.matched == 2
        # LLM called with only the unparsed crypto market
        mock_llm.assert_called_once()
        llm_markets = mock_llm.call_args[0][0]
        assert len(llm_markets) == 1
        assert llm_markets[0].id == "polymarket:222"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestMatchMarkets -v`

Expected: FAIL with `AttributeError: 'MarketMatcher' object has no attribute 'match_markets'`

**Step 3: Write minimal implementation**

Add method to `MarketMatcher`:

```python
    async def match_markets(self, markets: list[Market]) -> MatchResult:
        """Parse all markets and register mappings with scanner.

        1. Try regex on each market
        2. Batch unparsed crypto titles to LLM
        3. Register all successful parses with scanner
        """
        matched_markets: list[ParsedMarket] = []
        skipped = 0
        failed = 0
        needs_llm: list[Market] = []

        # First pass: regex
        for market in markets:
            if not self._is_crypto_market(market.title):
                skipped += 1
                continue

            parsed = self._parse_with_regex(market)
            if parsed:
                matched_markets.append(parsed)
            else:
                needs_llm.append(market)

        # Second pass: LLM fallback for unparsed crypto markets
        if needs_llm:
            llm_results = await self._parse_with_llm(needs_llm)
            matched_markets.extend(llm_results)
            failed = len(needs_llm) - len(llm_results)

        # Register mappings with scanner
        for parsed in matched_markets:
            if parsed.asset and parsed.threshold and parsed.direction:
                self._scanner.register_market_oracle_mapping(
                    market_id=parsed.market_id,
                    oracle_symbol=parsed.asset,
                    threshold=parsed.threshold,
                    direction=parsed.direction,
                )

        logger.info(
            "market_matching_complete",
            total=len(markets),
            matched=len(matched_markets),
            skipped=skipped,
            failed=failed,
        )

        return MatchResult(
            total_markets=len(markets),
            matched=len(matched_markets),
            skipped=skipped,
            failed=failed,
            matched_markets=matched_markets,
        )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/core/test_market_matcher.py::TestMatchMarkets -v`

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/core/market_matcher.py tests/core/test_market_matcher.py
git commit -m "feat(matcher): implement match_markets main method"
```

---

## Task 7: Integrate MarketMatcher into Pilot

**Files:**
- Modify: `src/pm_arb/pilot.py`
- Test: `tests/test_pilot.py`

**Step 1: Write the failing test**

Add to `tests/test_pilot.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.core.market_matcher import MatchResult
from pm_arb.pilot import PilotOrchestrator


class TestPilotMarketMatching:
    """Tests for market matching integration in pilot."""

    @pytest.mark.asyncio
    async def test_matches_markets_before_scanning(self) -> None:
        """Should match markets after creating agents but before running."""
        with patch("pm_arb.pilot.PolymarketAdapter") as mock_adapter_cls, \
             patch("pm_arb.pilot.CoinGeckoOracle"), \
             patch("pm_arb.pilot.MarketMatcher") as mock_matcher_cls, \
             patch("pm_arb.pilot.init_db", new_callable=AsyncMock), \
             patch("pm_arb.pilot.get_pool", new_callable=AsyncMock):

            # Setup mock adapter
            mock_adapter = AsyncMock()
            mock_adapter.get_markets = AsyncMock(return_value=[])
            mock_adapter_cls.return_value = mock_adapter

            # Setup mock matcher
            mock_matcher = MagicMock()
            mock_matcher.match_markets = AsyncMock(
                return_value=MatchResult(
                    total_markets=0,
                    matched=0,
                    skipped=0,
                    failed=0,
                    matched_markets=[],
                )
            )
            mock_matcher_cls.return_value = mock_matcher

            orchestrator = PilotOrchestrator(redis_url="redis://localhost:6379")

            # Run briefly then stop
            async def run_and_stop() -> None:
                task = asyncio.create_task(orchestrator.run())
                await asyncio.sleep(0.1)
                await orchestrator.stop()
                await task

            await run_and_stop()

            # Verify matcher was called
            mock_matcher.match_markets.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/test_pilot.py::TestPilotMarketMatching -v`

Expected: FAIL with `ImportError: cannot import name 'MarketMatcher' from 'pm_arb.pilot'`

**Step 3: Write minimal implementation**

Modify `src/pm_arb/pilot.py`:

1. Add import at top:
```python
from pm_arb.core.market_matcher import MarketMatcher
```

2. Change `_create_agents` to be async and add market matching:

```python
    async def _create_agents(self) -> list[BaseAgent]:
        """Create all agents in startup order."""
        # Create adapters
        polymarket_adapter = PolymarketAdapter()
        await polymarket_adapter.connect()
        coingecko_oracle = CoinGeckoOracle()

        # Configure oracle for batch fetching (avoids rate limits)
        symbols = ["BTC", "ETH"]
        coingecko_oracle.set_symbols(symbols)

        # Define channels for scanner
        venue_channels = ["venue.polymarket.prices"]
        oracle_channels = [f"oracle.coingecko.{sym}" for sym in symbols]

        # Create scanner
        scanner = OpportunityScannerAgent(
            self._redis_url,
            venue_channels=venue_channels,
            oracle_channels=oracle_channels,
        )

        # Match markets to oracles before scanning starts
        matcher = MarketMatcher(scanner, anthropic_api_key=settings.anthropic_api_key)
        markets = await polymarket_adapter.get_markets()
        await matcher.match_markets(markets)

        return [
            # Data feeds first
            VenueWatcherAgent(
                self._redis_url,
                adapter=polymarket_adapter,
                poll_interval=5.0,
            ),
            OracleAgent(
                self._redis_url,
                oracle=coingecko_oracle,
                symbols=symbols,
                poll_interval=15.0,
            ),
            # Detection layer
            scanner,
            # Risk & execution
            RiskGuardianAgent(self._redis_url),
            PaperExecutorAgent(self._redis_url, db_pool=self._db_pool),
            # Strategy & capital
            OracleSniperStrategy(self._redis_url),
            CapitalAllocatorAgent(self._redis_url),
        ]
```

3. Update the `run` method to await `_create_agents`:

Change:
```python
self._agents = self._create_agents()
```

To:
```python
self._agents = await self._create_agents()
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest tests/test_pilot.py::TestPilotMarketMatching -v`

Expected: PASS

**Step 5: Commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add src/pm_arb/pilot.py tests/test_pilot.py
git commit -m "feat(pilot): integrate MarketMatcher at startup"
```

---

## Task 8: Run Full Test Suite and Fix Any Issues

**Files:**
- All test files

**Step 1: Run full test suite**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && pytest -v`

**Step 2: Fix any failures**

Address any test failures that arise from the integration.

**Step 3: Run linter**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && ruff check src tests`

**Step 4: Format code**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && ruff format src tests`

**Step 5: Final commit**

```bash
cd /Users/robstover/Development/personal/pm-arbitrage
git add -A
git commit -m "chore: fix lint and test issues from market matcher integration"
```

---

## Task 9: Manual Verification

**Step 1: Run the pilot and observe logs**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && python -m pm_arb.pilot`

**Step 2: Verify market matching logs appear**

Expected log output:
```
market_matching_complete total=95 matched=12 skipped=80 failed=3
```

**Step 3: Verify opportunity detection**

If BTC price is near a threshold (e.g., $97,842 vs $100,000 threshold), you should see:
```
opportunity_detected opp_id=opp-abc123 type=oracle_lag edge=0.05 signal=0.7
```

**Step 4: Document results**

If working, update the design doc with actual matched market counts.

---

## Summary

| Task | Description | Est. |
|------|-------------|------|
| 1 | Data classes (ParsedMarket, MatchResult) | 5 min |
| 2 | Asset alias mapping | 3 min |
| 3 | _is_crypto_market helper | 5 min |
| 4 | Regex parser | 10 min |
| 5 | LLM fallback parser | 10 min |
| 6 | match_markets main method | 10 min |
| 7 | Pilot integration | 10 min |
| 8 | Full test suite + lint | 5 min |
| 9 | Manual verification | 5 min |

**Total: 9 tasks, ~63 minutes**
