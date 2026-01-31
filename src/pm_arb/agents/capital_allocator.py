"""Capital Allocator Agent - manages capital allocation across strategies."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import TradeStatus

logger = structlog.get_logger()


class CapitalAllocatorAgent(BaseAgent):
    """
    Manages capital allocation across trading strategies.

    Uses tournament-style scoring to allocate more capital to better performers.
    """

    def __init__(
        self,
        redis_url: str,
        total_capital: Decimal = Decimal("500"),
        min_allocation: Decimal = Decimal("0.05"),  # 5% minimum per strategy
        max_allocation: Decimal = Decimal("0.50"),  # 50% maximum per strategy
        rebalance_interval_trades: int = 10,  # Rebalance every N trades
    ) -> None:
        self.name = "capital-allocator"
        super().__init__(redis_url)

        self._total_capital = total_capital
        self._min_allocation = min_allocation
        self._max_allocation = max_allocation
        self._rebalance_interval = rebalance_interval_trades

        # Strategy tracking
        self._strategies: list[str] = []
        self._allocations: dict[str, Decimal] = {}
        self._strategy_performance: dict[str, dict[str, Any]] = {}

        # Trade counter for rebalancing
        self._trades_since_rebalance = 0

    def get_subscriptions(self) -> list[str]:
        """Subscribe to trade results."""
        return ["trade.results"]

    def register_strategy(self, strategy_name: str) -> None:
        """Register a strategy for allocation tracking."""
        if strategy_name in self._strategies:
            return

        self._strategies.append(strategy_name)
        self._strategy_performance[strategy_name] = {
            "total_pnl": Decimal("0"),
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "largest_win": Decimal("0"),
            "largest_loss": Decimal("0"),
        }

        # Equal initial allocation
        self._recalculate_equal_allocation()

        logger.info("strategy_registered", strategy=strategy_name)

    def _recalculate_equal_allocation(self) -> None:
        """Set equal allocation across all strategies."""
        if not self._strategies:
            return

        equal_share = Decimal("1.0") / len(self._strategies)
        for strategy in self._strategies:
            self._allocations[strategy] = equal_share

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Process trade results."""
        if channel == "trade.results":
            await self._handle_trade_result(data)

    async def _handle_trade_result(self, data: dict[str, Any]) -> None:
        """Update strategy performance based on trade result."""
        strategy = data.get("strategy")
        if not strategy or strategy not in self._strategies:
            # Try to extract strategy from the trade
            strategy = data.get("request", {}).get("strategy")
            if not strategy:
                return

        status = data.get("status", "")
        if status != TradeStatus.FILLED.value:
            return

        pnl = Decimal(str(data.get("pnl", "0")))
        perf = self._strategy_performance[strategy]

        perf["trades"] += 1
        perf["total_pnl"] += pnl

        if pnl > 0:
            perf["wins"] += 1
            if pnl > perf["largest_win"]:
                perf["largest_win"] = pnl
        elif pnl < 0:
            perf["losses"] += 1
            if pnl < perf["largest_loss"]:
                perf["largest_loss"] = pnl

        logger.info(
            "strategy_pnl_updated",
            strategy=strategy,
            pnl=str(pnl),
            total_pnl=str(perf["total_pnl"]),
            trades=perf["trades"],
        )

        # Check if rebalance needed
        self._trades_since_rebalance += 1
        if self._trades_since_rebalance >= self._rebalance_interval:
            await self.rebalance_allocations()
            self._trades_since_rebalance = 0

    async def rebalance_allocations(self) -> None:
        """Rebalance allocations based on strategy performance."""
        if len(self._strategies) < 2:
            return

        # Calculate scores for each strategy
        scores: dict[str, Decimal] = {}
        total_score = Decimal("0")

        for strategy in self._strategies:
            score = self._calculate_strategy_score(strategy)
            scores[strategy] = score
            total_score += score

        if total_score <= 0:
            # No positive scores, use equal allocation
            self._recalculate_equal_allocation()
            return

        # Allocate proportionally to scores
        for strategy in self._strategies:
            raw_allocation = scores[strategy] / total_score

            # Apply min/max constraints
            allocation = max(self._min_allocation, min(self._max_allocation, raw_allocation))
            self._allocations[strategy] = allocation

        # Normalize to ensure sum = 1.0
        total_alloc = sum(self._allocations.values())
        if total_alloc > 0:
            for strategy in self._strategies:
                self._allocations[strategy] /= total_alloc

        # Publish allocation updates
        for strategy in self._strategies:
            await self._publish_allocation(strategy)

        logger.info(
            "allocations_rebalanced",
            allocations={s: str(a) for s, a in self._allocations.items()},
        )

    def _calculate_strategy_score(self, strategy: str) -> Decimal:
        """
        Calculate tournament score for a strategy.

        Score = PnL + (win_rate_bonus) + (consistency_bonus)
        Minimum score is 0.1 to ensure all strategies get some allocation.
        """
        perf = self._strategy_performance[strategy]
        trades = perf["trades"]

        if trades == 0:
            return Decimal("0.1")  # Base allocation for new strategies

        total_pnl = perf["total_pnl"]
        wins = perf["wins"]
        win_rate = Decimal(str(wins)) / Decimal(str(trades))

        # Base score from PnL (normalized)
        pnl_score = max(Decimal("0"), total_pnl / Decimal("100") + Decimal("1"))

        # Win rate bonus (0 to 0.5)
        win_rate_bonus = win_rate * Decimal("0.5")

        # Combine
        score = pnl_score + win_rate_bonus

        min_score = Decimal("0.1")
        return score if score > min_score else min_score

    async def _publish_allocation(self, strategy: str) -> None:
        """Publish allocation update for a strategy."""
        await self.publish(
            "allocations.update",
            {
                "strategy": strategy,
                "allocation_pct": str(self._allocations.get(strategy, Decimal("0.10"))),
                "total_capital": str(self._total_capital),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

    def get_allocation(self, strategy: str) -> Decimal:
        """Get current allocation for a strategy."""
        return self._allocations.get(strategy, Decimal("0.10"))

    def get_strategy_performance(self, strategy: str) -> dict[str, Any]:
        """Get performance metrics for a strategy."""
        return self._strategy_performance.get(
            strategy,
            {"total_pnl": Decimal("0"), "trades": 0, "wins": 0, "losses": 0},
        )

    def get_all_performance(self) -> dict[str, dict[str, Any]]:
        """Get performance metrics for all strategies."""
        return {
            strategy: {
                **self._strategy_performance[strategy],
                "allocation_pct": self._allocations.get(strategy, Decimal("0")),
            }
            for strategy in self._strategies
        }

    def get_state_snapshot(self) -> dict[str, Any]:
        """Return complete state snapshot for dashboard."""
        return {
            "total_capital": self._total_capital,
            "strategies": {
                strategy: {
                    **self._strategy_performance[strategy],
                    "allocation_pct": self._allocations.get(strategy, Decimal("0")),
                }
                for strategy in self._strategies
            },
            "trades_since_rebalance": self._trades_since_rebalance,
        }
