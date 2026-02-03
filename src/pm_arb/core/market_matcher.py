"""Market-Oracle Matcher - parses market titles and registers oracle mappings."""

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
