"""Opportunity Scanner Agent - detects arbitrage opportunities."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Market, MultiOutcomeMarket, Opportunity, OpportunityType, OracleData, Outcome

logger = structlog.get_logger()


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
        edge = fair_yes_price - current_yes

        if abs(edge) < self._min_edge_pct:
            return  # Not enough edge

        # Calculate signal strength based on oracle distance from threshold
        signal_strength = min(Decimal("1.0"), distance_pct * 10)

        if signal_strength < self._min_signal_strength:
            return

        # Publish opportunity
        opportunity = Opportunity(
            id=f"opp-{uuid4().hex[:8]}",
            type=OpportunityType.ORACLE_LAG,
            markets=[market.id],
            oracle_source=oracle_data.source,
            oracle_value=oracle_data.value,
            expected_edge=edge,
            signal_strength=signal_strength,
            metadata={
                "threshold": str(threshold),
                "direction": direction,
                "fair_yes_price": str(fair_yes_price),
                "current_yes_price": str(current_yes),
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

    async def _check_single_condition_arb(self, market: Market) -> None:
        """Check if YES + NO < 1.0 (simple mispricing).

        This captures the $10.5M opportunity class from research.
        """
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

    async def _handle_multi_outcome_market(
        self, channel: str, data: dict[str, Any]
    ) -> None:
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
                "outcomes": [
                    {"name": o.name, "price": str(o.price)}
                    for o in market.outcomes
                ],
            },
        )

        await self._publish_opportunity(opportunity)

    async def _publish_opportunity(self, opportunity: Opportunity) -> None:
        """Publish detected opportunity."""
        logger.info(
            "opportunity_detected",
            opp_id=opportunity.id,
            type=opportunity.type.value,
            edge=str(opportunity.expected_edge),
            signal=str(opportunity.signal_strength),
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
