"""Oracle Sniper Strategy - exploits oracle lag in prediction markets."""

from decimal import Decimal
from typing import Any

import structlog

from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.core.models import OpportunityType

logger = structlog.get_logger()


class OracleSniperStrategy(StrategyAgent):
    """
    Strategy that exploits lag between oracle data and prediction market prices.

    When oracle shows BTC > $100k but market still prices YES at 0.80,
    this strategy buys YES expecting convergence to fair value (~0.95).
    """

    def __init__(
        self,
        redis_url: str,
        min_edge: Decimal = Decimal("0.05"),  # 5% minimum edge
        min_signal: Decimal = Decimal("0.60"),  # 60% minimum signal
        max_position_pct: Decimal = Decimal("0.50"),  # Max 50% of allocation per trade
    ) -> None:
        super().__init__(
            redis_url=redis_url,
            strategy_name="oracle-sniper",
            min_edge=min_edge,
            min_signal=min_signal,
        )
        self._max_position_pct = max_position_pct

    def evaluate_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any] | None:
        """
        Evaluate oracle lag opportunity.

        Only accepts ORACLE_LAG type. Sizes position by signal strength.
        """
        # Only handle oracle lag opportunities
        opp_type = opportunity.get("type", "")
        if opp_type != OpportunityType.ORACLE_LAG.value:
            return None

        markets = opportunity.get("markets", [])
        if not markets:
            return None

        metadata = opportunity.get("metadata", {})
        edge = Decimal(str(opportunity.get("expected_edge", "0")))
        signal = Decimal(str(opportunity.get("signal_strength", "0")))

        # Determine trade direction from edge sign
        # Positive edge = YES underpriced, buy YES
        # Negative edge = YES overpriced, buy NO (sell YES)
        if edge > 0:
            side = "buy"
            outcome = "YES"
        else:
            side = "buy"
            outcome = "NO"

        # Get current price from metadata
        current_price = Decimal(str(metadata.get("current_yes_price", "0.50")))
        if outcome == "NO":
            current_price = Decimal("1") - current_price

        # Size position based on signal strength and allocation
        max_position = self.get_available_capital() * self._max_position_pct
        position_size = max_position * signal

        logger.info(
            "oracle_sniper_evaluation",
            opportunity_id=opportunity.get("id"),
            edge=str(edge),
            signal=str(signal),
            outcome=outcome,
            position_size=str(position_size),
        )

        return {
            "market_id": markets[0],
            "side": side,
            "outcome": outcome,
            "amount": position_size,
            "max_price": current_price,  # Willing to pay current price
        }
