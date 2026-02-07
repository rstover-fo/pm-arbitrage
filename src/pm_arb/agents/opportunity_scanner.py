"""Opportunity Scanner Agent - detects arbitrage opportunities."""

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import (
    Market,
    MultiOutcomeMarket,
    Opportunity,
    OpportunityType,
    OracleData,
    Outcome,
)

logger = structlog.get_logger()

# Keywords for detecting 15-minute crypto markets with taker fees
CRYPTO_KEYWORDS = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "xrp"]
DURATION_PATTERNS = [
    r"15\s*min",
    r"15-min",
    r"fifteen\s*min",
    r"15\s*minute",
]

# Threshold below which a market is considered effectively resolved
RESOLVED_PRICE_THRESHOLD = Decimal("0.02")

# Cooldown in seconds before re-emitting an opportunity for the same market
OPPORTUNITY_COOLDOWN_SECONDS = 60

# Maximum credible edge — anything above this is likely a resolved market
MAX_CREDIBLE_EDGE = Decimal("0.30")


class OpportunityScannerAgent(BaseAgent):
    """Scans for arbitrage opportunities across venues and oracles."""

    def __init__(
        self,
        redis_url: str,
        venue_channels: list[str],
        oracle_channels: list[str],
        min_edge_pct: Decimal = Decimal("0.02"),  # 2% minimum edge
        min_signal_strength: Decimal = Decimal("0.5"),
    ) -> None:
        self.name = "opportunity-scanner"
        super().__init__(redis_url)
        self._venue_channels = venue_channels
        self._oracle_channels = oracle_channels
        self._min_edge_pct = min_edge_pct
        self._min_signal_strength = min_signal_strength

        # Cache of current state
        self._markets: dict[str, Market] = {}
        self._oracle_values: dict[str, OracleData] = {}
        self._market_oracle_map: dict[str, str] = {}  # market_id -> oracle_symbol
        self._market_thresholds: dict[str, dict[str, Any]] = {}

        # Cross-platform matching
        self._matched_markets: dict[str, list[str]] = {}  # event_id -> [market_ids]
        self._market_to_event: dict[str, str] = {}  # market_id -> event_id

        # Multi-outcome markets
        self._multi_outcome_markets: dict[str, MultiOutcomeMarket] = {}

        # Opportunity deduplication cooldown: market_id -> last emit time
        self._last_opportunity_time: dict[str, datetime] = {}

    def get_subscriptions(self) -> list[str]:
        """Subscribe to venue prices and oracle data."""
        return self._venue_channels + self._oracle_channels

    def register_market_oracle_mapping(
        self,
        market_id: str,
        oracle_symbol: str,
        threshold: Decimal,
        direction: str,  # "above" or "below"
    ) -> None:
        """Register a market that tracks an oracle threshold."""
        self._market_oracle_map[market_id] = oracle_symbol
        self._market_thresholds[market_id] = {
            "threshold": threshold,
            "direction": direction,
            "oracle_symbol": oracle_symbol,
        }

    def register_matched_markets(
        self,
        market_ids: list[str],
        event_id: str,
    ) -> None:
        """Register markets that track the same underlying event."""
        self._matched_markets[event_id] = market_ids
        for market_id in market_ids:
            self._market_to_event[market_id] = event_id

    def _is_fee_market(self, market: Market) -> bool:
        """Check if market has taker fees.

        Kalshi charges fees on ALL markets.
        Polymarket charges taker fees on 15-minute crypto markets only.
        All other Polymarket markets (longer duration, non-crypto) are fee-free.
        """
        # Kalshi charges fees on all markets
        if market.venue == "kalshi":
            return True

        # Polymarket: only 15-min crypto markets have fees
        title_lower = market.title.lower()

        # Must be crypto-related
        is_crypto = any(kw in title_lower for kw in CRYPTO_KEYWORDS)
        if not is_crypto:
            return False

        # Must be 15-minute duration
        is_15min = any(re.search(p, title_lower) for p in DURATION_PATTERNS)

        return is_15min

    def _calculate_taker_fee(self, price: Decimal) -> Decimal:
        """Calculate expected taker fee rate for 15-min crypto markets.

        Fee formula from Polymarket docs:
            fee_rate = 0.0312 * (0.5 - abs(price - 0.5))

        Fee is highest at 50% probability (~1.56%), zero at 0% or 100%.
        """
        # Distance from edge (0 or 1) - maximized at 0.5
        distance_from_edge = Decimal("0.5") - abs(price - Decimal("0.5"))
        fee_rate = Decimal("0.0312") * distance_from_edge
        return fee_rate

    def _calculate_kalshi_fee(self, price: Decimal) -> Decimal:
        """Calculate Kalshi fee rate.

        Kalshi charges ~2 cents per contract per side.
        Fee rate relative to contract price varies with price.
        """
        fee_per_contract = Decimal("0.02")
        if price <= Decimal("0") or price >= Decimal("1"):
            return Decimal("0")
        return fee_per_contract / price

    def _calculate_net_edge(
        self,
        gross_edge: Decimal,
        market: Market,
        entry_price: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Calculate edge after accounting for fees.

        Args:
            gross_edge: Raw edge before fees
            market: Market being evaluated
            entry_price: Expected entry price

        Returns:
            Tuple of (net_edge, fee_rate)
        """
        if market.venue == "kalshi":
            fee_rate = self._calculate_kalshi_fee(entry_price)
            return gross_edge - fee_rate, fee_rate
        elif self._is_fee_market(market):
            fee_rate = self._calculate_taker_fee(entry_price)
            return gross_edge - fee_rate, fee_rate
        return gross_edge, Decimal("0")  # No fees on non-fee markets

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Route messages to appropriate handler."""
        if channel.startswith("venue.") and channel.endswith(".multi"):
            await self._handle_multi_outcome_market(channel, data)
        elif channel.startswith("venue."):
            await self._handle_venue_price(channel, data)
        elif channel.startswith("oracle."):
            await self._handle_oracle_data(channel, data)

    async def _handle_venue_price(self, channel: str, data: dict[str, Any]) -> None:
        """Process venue price update."""
        market_id = data.get("market_id", "")
        if not market_id:
            return

        market = Market(
            id=market_id,
            venue=data.get("venue", ""),
            external_id=data.get("external_id", market_id),
            title=data.get("title", ""),
            yes_price=Decimal(str(data.get("yes_price", "0.5"))),
            no_price=Decimal(str(data.get("no_price", "0.5"))),
        )
        self._markets[market_id] = market

        # Check for opportunities
        await self._scan_for_opportunities(market)

    async def _handle_oracle_data(self, channel: str, data: dict[str, Any]) -> None:
        """Process oracle data update."""
        symbol = data.get("symbol", "")
        if not symbol:
            return

        oracle_data = OracleData(
            source=data.get("source", ""),
            symbol=symbol,
            value=Decimal(str(data.get("value", "0"))),
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now(UTC).isoformat())),
            metadata=data.get("metadata", {}),
        )
        self._oracle_values[symbol] = oracle_data

        # Check all markets that depend on this oracle
        await self._scan_oracle_opportunities(symbol, oracle_data)

    async def _scan_for_opportunities(self, market: Market) -> None:
        """Scan for opportunities involving this market."""
        # Check single-condition mispricing first (YES + NO < 1)
        await self._check_single_condition_arb(market)

        # Check oracle-based opportunities
        if market.id in self._market_thresholds:
            threshold_info = self._market_thresholds[market.id]
            oracle_symbol = threshold_info["oracle_symbol"]
            if oracle_symbol in self._oracle_values:
                oracle_data = self._oracle_values[oracle_symbol]
                await self._check_oracle_lag(market, oracle_data, threshold_info)

        # Check cross-platform opportunities
        if market.id in self._market_to_event:
            await self._check_cross_platform(market)

    async def _scan_oracle_opportunities(self, symbol: str, oracle_data: OracleData) -> None:
        """Scan for oracle-based opportunities when oracle updates."""
        # Find all markets that track this oracle
        for market_id, oracle_symbol in self._market_oracle_map.items():
            if oracle_symbol != symbol:
                continue
            if market_id not in self._markets:
                continue
            if market_id not in self._market_thresholds:
                continue

            market = self._markets[market_id]
            threshold_info = self._market_thresholds[market_id]
            await self._check_oracle_lag(market, oracle_data, threshold_info)

    async def _check_oracle_lag(
        self,
        market: Market,
        oracle_data: OracleData,
        threshold_info: dict[str, Any],
    ) -> None:
        """Check if market price lags behind oracle reality."""
        # Skip stale markets — zero-priced markets produce phantom signals
        if self._is_stale_market(market):
            return

        # Skip resolved markets — near-0 or near-1 prices indicate the outcome
        # is already determined (e.g., 15-min market expired)
        if self._is_resolved_market(market):
            return

        threshold = threshold_info["threshold"]
        direction = threshold_info["direction"]

        # Calculate what the fair price should be based on oracle
        if direction == "above":
            # If oracle > threshold, YES should be ~1.0
            oracle_suggests_yes = oracle_data.value > threshold
        else:
            # If oracle < threshold, YES should be ~1.0
            oracle_suggests_yes = oracle_data.value < threshold

        # Calculate implied probability from oracle
        # If condition is met, fair value is high (0.95)
        # If not met, fair value is low (0.05)
        # Add buffer zone around threshold
        distance_pct = abs(oracle_data.value - threshold) / threshold

        if oracle_suggests_yes:
            # Condition met - YES should be high
            if distance_pct > Decimal("0.05"):  # 5% buffer
                fair_yes_price = Decimal("0.95")
            else:
                fair_yes_price = Decimal("0.50") + (distance_pct * 10)  # Scale up
        else:
            # Condition not met - YES should be low
            if distance_pct > Decimal("0.05"):
                fair_yes_price = Decimal("0.05")
            else:
                fair_yes_price = Decimal("0.50") - (distance_pct * 10)

        # Calculate edge
        current_yes = market.yes_price
        gross_edge = fair_yes_price - current_yes

        # Apply fee-aware edge calculation for 15-min crypto markets
        net_edge, fee_rate = self._calculate_net_edge(gross_edge, market, current_yes)

        if abs(net_edge) < self._min_edge_pct:
            if fee_rate > 0:
                logger.debug(
                    "opportunity_filtered_by_fees",
                    market_id=market.id,
                    gross_edge=str(gross_edge),
                    net_edge=str(net_edge),
                    fee_rate=str(fee_rate),
                )
            return  # Not enough edge after fees

        # Cap edge at credible maximum — anything above 30% is likely a
        # resolved market that slipped past the resolved-market filter
        if abs(net_edge) > MAX_CREDIBLE_EDGE:
            logger.debug(
                "opportunity_filtered_incredible_edge",
                market_id=market.id,
                net_edge=str(net_edge),
                current_yes=str(current_yes),
            )
            return

        # Calculate signal strength based on oracle distance from threshold
        signal_strength = min(Decimal("1.0"), distance_pct * 10)

        if signal_strength < self._min_signal_strength:
            return

        # Publish opportunity with fee metadata
        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.ORACLE_LAG,
            markets=[market.id],
            oracle_source=oracle_data.source,
            oracle_value=oracle_data.value,
            expected_edge=net_edge,  # Use net edge after fees
            signal_strength=signal_strength,
            metadata={
                "threshold": str(threshold),
                "direction": direction,
                "fair_yes_price": str(fair_yes_price),
                "current_yes_price": str(current_yes),
                "gross_edge": str(gross_edge),
                "fee_rate": str(fee_rate),
                "is_fee_market": self._is_fee_market(market),
            },
        )

        await self._publish_opportunity(opportunity)

    async def _check_cross_platform(self, updated_market: Market) -> None:
        """Check for cross-platform arbitrage opportunities."""
        event_id = self._market_to_event.get(updated_market.id)
        if not event_id:
            return

        matched_ids = self._matched_markets.get(event_id, [])
        if len(matched_ids) < 2:
            return

        # Get all markets for this event
        markets = [self._markets[mid] for mid in matched_ids if mid in self._markets]

        if len(markets) < 2:
            return

        # Find max and min YES prices
        prices = [(m, m.yes_price) for m in markets]
        prices.sort(key=lambda x: x[1])

        lowest_market, lowest_price = prices[0]
        highest_market, highest_price = prices[-1]

        # Calculate edge (buy YES on cheap venue, buy NO on expensive venue)
        edge = highest_price - lowest_price

        if edge < self._min_edge_pct:
            return

        # Signal strength based on price difference
        signal_strength = min(Decimal("1.0"), edge * 5)

        if signal_strength < self._min_signal_strength:
            return

        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.CROSS_PLATFORM,
            markets=[lowest_market.id, highest_market.id],
            expected_edge=edge,
            signal_strength=signal_strength,
            metadata={
                "event_id": event_id,
                "buy_yes_venue": lowest_market.venue,
                "buy_yes_price": str(lowest_price),
                "buy_no_venue": highest_market.venue,
                "buy_no_price": str(Decimal("1") - highest_price),
            },
        )

        await self._publish_opportunity(opportunity)

    def _is_stale_market(self, market: Market) -> bool:
        """Check if market has no meaningful price data.

        Markets with both prices at or near zero are dead/inactive and
        produce phantom arbitrage signals.
        """
        min_price = Decimal("0.01")
        return market.yes_price < min_price and market.no_price < min_price

    def _is_resolved_market(self, market: Market) -> bool:
        """Check if market outcome is already determined.

        A market with YES near 0 or YES near 1 has effectively resolved.
        These produce phantom oracle-lag signals because the oracle still
        sees the condition being met, but the market has already settled.
        """
        return market.yes_price < RESOLVED_PRICE_THRESHOLD or market.yes_price > (
            Decimal("1") - RESOLVED_PRICE_THRESHOLD
        )

    async def _check_single_condition_arb(self, market: Market) -> None:
        """Check if YES + NO < 1.0 (simple mispricing).

        This captures the $10.5M opportunity class from research.
        """
        # Skip stale markets with no real price data
        if self._is_stale_market(market):
            return

        price_sum = market.yes_price + market.no_price

        # Calculate edge (how much under $1.00)
        edge = Decimal("1.0") - price_sum

        # Must be positive edge and exceed minimum
        if edge <= 0 or edge < self._min_edge_pct:
            return

        # Signal strength proportional to edge (capped at 1.0)
        signal_strength = min(Decimal("1.0"), edge * 5)

        if signal_strength < self._min_signal_strength:
            return

        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.MISPRICING,
            markets=[market.id],
            expected_edge=edge,
            signal_strength=signal_strength,
            metadata={
                "arb_type": "single_condition",
                "yes_price": str(market.yes_price),
                "no_price": str(market.no_price),
                "price_sum": str(price_sum),
            },
        )

        await self._publish_opportunity(opportunity)

    async def _handle_multi_outcome_market(self, channel: str, data: dict[str, Any]) -> None:
        """Process multi-outcome market update."""
        market_id = data.get("market_id", "")
        if not market_id:
            return

        outcomes = [
            Outcome(
                name=o.get("name", ""),
                price=Decimal(str(o.get("price", "0"))),
                external_id=o.get("external_id", ""),
            )
            for o in data.get("outcomes", [])
        ]

        market = MultiOutcomeMarket(
            id=market_id,
            venue=data.get("venue", ""),
            external_id=data.get("external_id", market_id),
            title=data.get("title", ""),
            outcomes=outcomes,
        )

        self._multi_outcome_markets[market_id] = market
        await self._check_multi_outcome_arb(market)

    async def _check_multi_outcome_arb(self, market: MultiOutcomeMarket) -> None:
        """Check if all outcome prices sum < 1.0.

        This captures the $29M opportunity class from research.
        """
        edge = market.arbitrage_edge

        if edge <= 0 or edge < self._min_edge_pct:
            return

        signal_strength = min(Decimal("1.0"), edge * 5)

        if signal_strength < self._min_signal_strength:
            return

        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.MISPRICING,
            markets=[market.id],
            expected_edge=edge,
            signal_strength=signal_strength,
            metadata={
                "arb_type": "multi_outcome",
                "outcome_count": len(market.outcomes),
                "price_sum": str(market.price_sum),
                "outcomes": [{"name": o.name, "price": str(o.price)} for o in market.outcomes],
            },
        )

        await self._publish_opportunity(opportunity)

    def _is_on_cooldown(self, market_id: str) -> bool:
        """Check if opportunity for this market is within cooldown period."""
        last_time = self._last_opportunity_time.get(market_id)
        if last_time is None:
            return False
        elapsed = (datetime.now(UTC) - last_time).total_seconds()
        return elapsed < OPPORTUNITY_COOLDOWN_SECONDS

    async def _publish_opportunity(self, opportunity: Opportunity) -> None:
        """Publish detected opportunity with per-market cooldown."""
        # Deduplicate: skip if we recently emitted for the same market(s)
        primary_market = opportunity.markets[0] if opportunity.markets else ""
        if primary_market and self._is_on_cooldown(primary_market):
            return

        logger.info(
            "opportunity_detected",
            opp_id=opportunity.id,
            type=opportunity.type.value,
            edge=str(opportunity.expected_edge),
            signal=str(opportunity.signal_strength),
            markets=opportunity.markets,
        )

        await self.publish(
            "opportunities.detected",
            {
                "id": opportunity.id,
                "type": opportunity.type.value,
                "markets": opportunity.markets,
                "oracle_source": opportunity.oracle_source,
                "oracle_value": str(opportunity.oracle_value) if opportunity.oracle_value else None,
                "expected_edge": str(opportunity.expected_edge),
                "signal_strength": str(opportunity.signal_strength),
                "detected_at": opportunity.detected_at.isoformat(),
                "metadata": opportunity.metadata,
            },
        )

        # Record cooldown
        if primary_market:
            self._last_opportunity_time[primary_market] = datetime.now(UTC)
