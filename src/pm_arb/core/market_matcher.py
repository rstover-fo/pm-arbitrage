"""Market-Oracle Matcher - parses market titles and registers oracle mappings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import anthropic
import structlog
from anthropic.types import TextBlock

from pm_arb.core.models import Market

logger = structlog.get_logger()

if TYPE_CHECKING:
    from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent

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

    async def _parse_with_llm(self, markets: list[Market]) -> list[ParsedMarket]:
        """Batch LLM fallback for titles regex couldn't handle."""
        if not self._api_key or not markets:
            return []

        # Build prompt
        titles_text = "\n".join(f'{i + 1}. "{m.title}"' for i, m in enumerate(markets))

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
                model="claude-3-haiku-20240307",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            # Parse response
            content_block = response.content[0]
            response_text = cast(TextBlock, content_block).text
            parsed_data = json.loads(response_text)

            results = []
            for i, item in enumerate(parsed_data):
                if item is None or item.get("asset") is None:
                    continue

                threshold = None
                if item.get("threshold"):
                    threshold = Decimal(str(item["threshold"]))

                results.append(
                    ParsedMarket(
                        market_id=markets[i].id,
                        asset=item["asset"],
                        threshold=threshold,
                        direction=item.get("direction"),
                        expiry=None,
                        parse_method="llm",
                    )
                )

            return results

        except Exception as e:
            logger.error("llm_parse_failed", error=str(e))
            return []

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
