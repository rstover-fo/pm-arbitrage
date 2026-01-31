"""Tests for Dashboard Service."""

from decimal import Decimal
from typing import Any

import pytest

from pm_arb.dashboard.service import DashboardService


class MockCapitalAllocator:
    """Mock allocator for testing."""

    def __init__(self) -> None:
        self._strategies = ["oracle-sniper", "cross-arb"]
        self._strategy_performance = {
            "oracle-sniper": {
                "total_pnl": Decimal("150"),
                "trades": 10,
                "wins": 7,
                "losses": 3,
                "largest_win": Decimal("50"),
                "largest_loss": Decimal("-20"),
            },
            "cross-arb": {
                "total_pnl": Decimal("-25"),
                "trades": 5,
                "wins": 2,
                "losses": 3,
                "largest_win": Decimal("20"),
                "largest_loss": Decimal("-30"),
            },
        }
        self._allocations = {
            "oracle-sniper": Decimal("0.60"),
            "cross-arb": Decimal("0.40"),
        }
        self._total_capital = Decimal("1000")

    def get_all_performance(self) -> dict[str, dict[str, Any]]:
        return {
            strategy: {
                **self._strategy_performance[strategy],
                "allocation_pct": self._allocations.get(strategy, Decimal("0")),
            }
            for strategy in self._strategies
        }


class MockRiskGuardian:
    """Mock guardian for testing."""

    def __init__(self) -> None:
        self._current_value = Decimal("950")
        self._high_water_mark = Decimal("1000")
        self._daily_pnl = Decimal("-50")
        self._initial_bankroll = Decimal("1000")
        self._positions: dict[str, Decimal] = {"polymarket:btc-100k": Decimal("100")}
        self._platform_exposure: dict[str, Decimal] = {"polymarket": Decimal("100")}
        self._halted = False


def test_get_strategy_summary() -> None:
    """Should aggregate strategy performance."""
    allocator = MockCapitalAllocator()
    guardian = MockRiskGuardian()
    service = DashboardService(allocator=allocator, guardian=guardian)

    summary = service.get_strategy_summary()

    assert len(summary) == 2
    assert summary[0]["strategy"] == "oracle-sniper"
    assert summary[0]["total_pnl"] == Decimal("150")
    assert summary[0]["win_rate"] == Decimal("0.70")
    assert summary[0]["allocation_pct"] == Decimal("0.60")


def test_get_risk_state() -> None:
    """Should return current risk metrics."""
    allocator = MockCapitalAllocator()
    guardian = MockRiskGuardian()
    service = DashboardService(allocator=allocator, guardian=guardian)

    risk = service.get_risk_state()

    assert risk["current_value"] == Decimal("950")
    assert risk["high_water_mark"] == Decimal("1000")
    assert risk["drawdown_pct"] == Decimal("0.05")  # 5% drawdown
    assert risk["daily_pnl"] == Decimal("-50")
    assert risk["halted"] is False


def test_get_portfolio_summary() -> None:
    """Should return overall portfolio metrics."""
    allocator = MockCapitalAllocator()
    guardian = MockRiskGuardian()
    service = DashboardService(allocator=allocator, guardian=guardian)

    portfolio = service.get_portfolio_summary()

    assert portfolio["total_capital"] == Decimal("1000")
    assert portfolio["current_value"] == Decimal("950")
    assert portfolio["total_pnl"] == Decimal("125")  # 150 - 25
    assert portfolio["total_trades"] == 15  # 10 + 5
    assert portfolio["overall_win_rate"] == Decimal("0.60")  # 9/15
