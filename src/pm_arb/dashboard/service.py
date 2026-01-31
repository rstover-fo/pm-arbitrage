"""Dashboard Service - aggregates data from agents for UI display."""

from decimal import Decimal
from typing import Any, Protocol


class AllocatorProtocol(Protocol):
    """Protocol for Capital Allocator interface."""

    _strategies: list[str]
    _total_capital: Decimal

    def get_all_performance(self) -> dict[str, dict[str, Any]]: ...


class GuardianProtocol(Protocol):
    """Protocol for Risk Guardian interface."""

    _current_value: Decimal
    _high_water_mark: Decimal
    _daily_pnl: Decimal
    _initial_bankroll: Decimal
    _positions: dict[str, Decimal]
    _platform_exposure: dict[str, Decimal]
    _halted: bool


class DashboardService:
    """Aggregates data from agents for dashboard display."""

    def __init__(
        self,
        allocator: AllocatorProtocol,
        guardian: GuardianProtocol,
    ) -> None:
        self._allocator = allocator
        self._guardian = guardian

    def get_strategy_summary(self) -> list[dict[str, Any]]:
        """Get performance summary for all strategies."""
        performance = self._allocator.get_all_performance()
        summaries = []

        for strategy, perf in performance.items():
            trades = perf.get("trades", 0)
            wins = perf.get("wins", 0)
            win_rate = Decimal(str(wins)) / Decimal(str(trades)) if trades > 0 else Decimal("0")

            summaries.append({
                "strategy": strategy,
                "total_pnl": perf.get("total_pnl", Decimal("0")),
                "trades": trades,
                "wins": wins,
                "losses": perf.get("losses", 0),
                "win_rate": win_rate,
                "largest_win": perf.get("largest_win", Decimal("0")),
                "largest_loss": perf.get("largest_loss", Decimal("0")),
                "allocation_pct": perf.get("allocation_pct", Decimal("0")),
            })

        # Sort by PnL descending
        summaries.sort(key=lambda x: x["total_pnl"], reverse=True)
        return summaries

    def get_risk_state(self) -> dict[str, Any]:
        """Get current risk metrics."""
        current = self._guardian._current_value
        hwm = self._guardian._high_water_mark

        drawdown = hwm - current if hwm > 0 else Decimal("0")
        drawdown_pct = drawdown / hwm if hwm > 0 else Decimal("0")

        return {
            "current_value": current,
            "high_water_mark": hwm,
            "drawdown": drawdown,
            "drawdown_pct": drawdown_pct,
            "daily_pnl": self._guardian._daily_pnl,
            "initial_bankroll": self._guardian._initial_bankroll,
            "positions": dict(self._guardian._positions),
            "platform_exposure": dict(self._guardian._platform_exposure),
            "halted": self._guardian._halted,
        }

    def get_portfolio_summary(self) -> dict[str, Any]:
        """Get overall portfolio metrics."""
        strategies = self.get_strategy_summary()

        total_pnl = sum(s["total_pnl"] for s in strategies)
        total_trades = sum(s["trades"] for s in strategies)
        total_wins = sum(s["wins"] for s in strategies)

        overall_win_rate = (
            Decimal(str(total_wins)) / Decimal(str(total_trades))
            if total_trades > 0
            else Decimal("0")
        )

        return {
            "total_capital": self._allocator._total_capital,
            "current_value": self._guardian._current_value,
            "total_pnl": total_pnl,
            "total_trades": total_trades,
            "total_wins": total_wins,
            "overall_win_rate": overall_win_rate,
            "strategy_count": len(strategies),
        }
