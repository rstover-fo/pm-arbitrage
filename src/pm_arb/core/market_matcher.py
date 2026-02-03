"""Market-Oracle Matcher - parses market titles and registers oracle mappings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pm_arb.core.models import Market

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
