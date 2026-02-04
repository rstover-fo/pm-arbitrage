"""Strategy Agent base class - evaluates opportunities and generates trade requests."""

from abc import abstractmethod
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent

logger = structlog.get_logger()


class StrategyAgent(BaseAgent):
    """Base class for trading strategies."""

    def __init__(
        self,
        redis_url: str,
        strategy_name: str,
        min_edge: Decimal = Decimal("0.02"),
        min_signal: Decimal = Decimal("0.50"),
    ) -> None:
        self.name = f"strategy-{strategy_name}"
        super().__init__(redis_url)
        self._strategy_name = strategy_name
        self._min_edge = min_edge
        self._min_signal = min_signal

        # Capital allocation (updated by Capital Allocator)
        self._allocation_pct = Decimal("0.10")  # Default 10%
        self._total_capital = Decimal("500")  # Will be updated

        # Performance tracking
        self._trades_submitted = 0
        self._trades_filled = 0
        self._total_pnl = Decimal("0")

    def get_subscriptions(self) -> list[str]:
        """Subscribe to opportunities and allocation updates."""
        return ["opportunities.detected", "allocations.update"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Route messages to appropriate handler."""
        if channel == "opportunities.detected":
            await self._handle_opportunity(data)
        elif channel == "allocations.update":
            await self._handle_allocation_update(data)

    async def _handle_opportunity(self, data: dict[str, Any]) -> None:
        """Evaluate opportunity and generate trade request if suitable."""
        # Check minimum thresholds
        edge = Decimal(str(data.get("expected_edge", "0")))
        signal = Decimal(str(data.get("signal_strength", "0")))

        if edge < self._min_edge or signal < self._min_signal:
            return

        # Let subclass evaluate
        trade_params = self.evaluate_opportunity(data)
        if not trade_params:
            return

        # Generate trade request
        await self._submit_trade_request(data, trade_params)

    @abstractmethod
    def evaluate_opportunity(self, opportunity: dict[str, Any]) -> dict[str, Any] | None:
        """
        Evaluate opportunity and return trade parameters if suitable.

        Returns:
            dict with keys: market_id, side, outcome, amount, max_price
            or None if opportunity should be skipped
        """
        ...

    async def _submit_trade_request(
        self,
        opportunity: dict[str, Any],
        trade_params: dict[str, Any],
    ) -> None:
        """Submit trade request to Risk Guardian."""
        request_id = f"req-{uuid4().hex[:8]}"

        # Calculate position size based on allocation
        max_position = self._total_capital * self._allocation_pct
        amount = min(trade_params["amount"], max_position)

        request = {
            "id": request_id,
            "opportunity_id": opportunity["id"],
            "strategy": self._strategy_name,
            "market_id": trade_params["market_id"],
            "side": trade_params["side"],
            "outcome": trade_params["outcome"],
            "amount": str(amount),
            "max_price": str(trade_params["max_price"]),
            "expected_edge": str(opportunity.get("expected_edge", "0")),
            "created_at": datetime.now(UTC).isoformat(),
        }

        logger.info(
            "trade_request_submitted",
            strategy=self._strategy_name,
            request_id=request_id,
            opportunity_id=opportunity["id"],
            amount=str(amount),
        )

        await self.publish("trade.requests", request)
        self._trades_submitted += 1

    async def _handle_allocation_update(self, data: dict[str, Any]) -> None:
        """Handle capital allocation update from allocator."""
        if data.get("strategy") != self._strategy_name:
            return

        self._allocation_pct = Decimal(str(data.get("allocation_pct", "0.10")))
        self._total_capital = Decimal(str(data.get("total_capital", "500")))

        logger.info(
            "allocation_updated",
            strategy=self._strategy_name,
            allocation_pct=str(self._allocation_pct),
            total_capital=str(self._total_capital),
        )

    def get_available_capital(self) -> Decimal:
        """Get current available capital for this strategy."""
        return self._total_capital * self._allocation_pct
