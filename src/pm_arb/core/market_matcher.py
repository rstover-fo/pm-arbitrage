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
