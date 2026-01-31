"""Risk Guardian Agent - evaluates trade requests against risk rules."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import RiskDecision, Side, TradeRequest

logger = structlog.get_logger()


class RiskGuardianAgent(BaseAgent):
    """Evaluates trade requests and enforces risk limits."""

    def __init__(
        self,
        redis_url: str,
        initial_bankroll: Decimal = Decimal("500"),
        position_limit_pct: Decimal = Decimal("0.10"),  # 10% per position
        platform_limit_pct: Decimal = Decimal("0.50"),  # 50% per platform
        daily_loss_limit_pct: Decimal = Decimal("0.10"),  # 10% daily loss
        drawdown_limit_pct: Decimal = Decimal("0.20"),  # 20% from peak
    ) -> None:
        self.name = "risk-guardian"
        super().__init__(redis_url)

        # Configuration
        self._initial_bankroll = initial_bankroll
        self._position_limit_pct = position_limit_pct
        self._platform_limit_pct = platform_limit_pct
        self._daily_loss_limit_pct = daily_loss_limit_pct
        self._drawdown_limit_pct = drawdown_limit_pct

        # State tracking
        self._high_water_mark = initial_bankroll
        self._current_value = initial_bankroll
        self._daily_pnl = Decimal("0")
        self._daily_reset_date = datetime.now(UTC).date()
        self._positions: dict[str, Decimal] = {}  # market_id -> exposure
        self._platform_exposure: dict[str, Decimal] = {}  # venue -> exposure
        self._halted = False

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade requests."""
        return ["trade.requests"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Evaluate trade request against risk rules."""
        if channel == "trade.requests":
            await self._evaluate_request(data)

    async def _evaluate_request(self, data: dict[str, Any]) -> None:
        """Evaluate a trade request against all rules."""
        request = self._parse_request(data)
        if not request:
            return

        # Check each rule
        decision = await self._check_rules(request)

        # Publish decision
        await self._publish_decision(decision)

        # Update state if approved
        if decision.approved:
            await self._update_exposure(request)

    def _parse_request(self, data: dict[str, Any]) -> TradeRequest | None:
        """Parse trade request from message data."""
        try:
            return TradeRequest(
                id=data.get("id", f"req-{uuid4().hex[:8]}"),
                opportunity_id=data.get("opportunity_id", ""),
                strategy=data.get("strategy", "unknown"),
                market_id=data.get("market_id", ""),
                side=Side(data.get("side", "buy")),
                outcome=data.get("outcome", "YES"),
                amount=Decimal(str(data.get("amount", "0"))),
                max_price=Decimal(str(data.get("max_price", "1"))),
            )
        except Exception as e:
            logger.error("invalid_trade_request", error=str(e), data=data)
            return None

    async def _check_rules(self, request: TradeRequest) -> RiskDecision:
        """Check request against all risk rules."""
        # Reset daily tracking if new day
        self._maybe_reset_daily()

        # Rule 1: System halted
        if self._halted:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason="System is halted",
                rule_triggered="system_halt",
            )

        # Rule 2: Drawdown check (halt if exceeded)
        drawdown_floor = self._high_water_mark * (1 - self._drawdown_limit_pct)
        if self._current_value < drawdown_floor:
            self._halted = True
            logger.critical(
                "drawdown_halt_triggered",
                current_value=str(self._current_value),
                high_water_mark=str(self._high_water_mark),
                floor=str(drawdown_floor),
            )
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Drawdown limit exceeded: ${self._current_value} < ${drawdown_floor}",
                rule_triggered="drawdown_halt",
            )

        # Rule 3: Daily loss limit
        daily_loss_limit = self._initial_bankroll * self._daily_loss_limit_pct
        if self._daily_pnl < -daily_loss_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Daily loss limit exceeded: ${abs(self._daily_pnl)} > ${daily_loss_limit}",
                rule_triggered="daily_loss_limit",
            )

        # Rule 4: Position limit
        position_limit = self._initial_bankroll * self._position_limit_pct
        current_position = self._positions.get(request.market_id, Decimal("0"))
        new_position = current_position + request.amount

        if new_position > position_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Position would exceed limit: ${new_position} > ${position_limit}",
                rule_triggered="position_limit",
            )

        # Rule 5: Platform limit
        platform_limit = self._initial_bankroll * self._platform_limit_pct
        venue = request.market_id.split(":")[0] if ":" in request.market_id else "unknown"
        current_platform = self._platform_exposure.get(venue, Decimal("0"))
        new_platform = current_platform + request.amount

        if new_platform > platform_limit:
            return RiskDecision(
                request_id=request.id,
                approved=False,
                reason=f"Platform exposure would exceed limit: ${new_platform} > ${platform_limit}",
                rule_triggered="platform_limit",
            )

        # All rules passed
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="All rules passed",
        )

    def _maybe_reset_daily(self) -> None:
        """Reset daily tracking if it's a new day."""
        today = datetime.now(UTC).date()
        if today != self._daily_reset_date:
            logger.info(
                "daily_reset",
                previous_pnl=str(self._daily_pnl),
                previous_date=str(self._daily_reset_date),
            )
            self._daily_pnl = Decimal("0")
            self._daily_reset_date = today

    async def _publish_decision(self, decision: RiskDecision) -> None:
        """Publish risk decision."""
        logger.info(
            "risk_decision",
            request_id=decision.request_id,
            approved=decision.approved,
            reason=decision.reason,
            rule=decision.rule_triggered,
        )

        await self.publish(
            "trade.decisions",
            {
                "request_id": decision.request_id,
                "approved": decision.approved,
                "reason": decision.reason,
                "rule_triggered": decision.rule_triggered,
                "decided_at": decision.decided_at.isoformat(),
            },
        )

    async def _update_exposure(self, request: TradeRequest) -> None:
        """Update exposure tracking after approved trade."""
        # Update position exposure
        current = self._positions.get(request.market_id, Decimal("0"))
        self._positions[request.market_id] = current + request.amount

        # Update platform exposure
        venue = request.market_id.split(":")[0] if ":" in request.market_id else "unknown"
        platform_current = self._platform_exposure.get(venue, Decimal("0"))
        self._platform_exposure[venue] = platform_current + request.amount

    def record_pnl(self, pnl: Decimal) -> None:
        """Record P&L and update tracking."""
        self._current_value += pnl
        self._daily_pnl += pnl

        # Update high water mark if new peak
        if self._current_value > self._high_water_mark:
            self._high_water_mark = self._current_value
            logger.info(
                "new_high_water_mark",
                value=str(self._high_water_mark),
            )

    def get_state_snapshot(self) -> dict[str, Any]:
        """Return risk state snapshot for dashboard."""
        return {
            "current_value": self._current_value,
            "high_water_mark": self._high_water_mark,
            "daily_pnl": self._daily_pnl,
            "initial_bankroll": self._initial_bankroll,
            "positions": dict(self._positions),
            "platform_exposure": dict(self._platform_exposure),
            "halted": self._halted,
        }
