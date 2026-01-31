"""Tests for Dashboard Service."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

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


class MockPaperExecutor:
    """Mock executor for testing."""

    def __init__(self) -> None:
        from pm_arb.core.models import Side, Trade, TradeStatus

        self._trades = [
            Trade(
                id="trade-001",
                request_id="req-001",
                market_id="polymarket:btc-100k",
                venue="polymarket",
                side=Side.BUY,
                outcome="YES",
                amount=Decimal("50"),
                price=Decimal("0.55"),
                fees=Decimal("0.05"),
                status=TradeStatus.FILLED,
                executed_at=datetime(2026, 1, 31, 10, 0, 0, tzinfo=UTC),
            ),
            Trade(
                id="trade-002",
                request_id="req-002",
                market_id="polymarket:btc-100k",
                venue="polymarket",
                side=Side.BUY,
                outcome="YES",
                amount=Decimal("100"),
                price=Decimal("0.60"),
                fees=Decimal("0.10"),
                status=TradeStatus.FILLED,
                executed_at=datetime(2026, 1, 31, 11, 0, 0, tzinfo=UTC),
            ),
        ]


def test_get_recent_trades() -> None:
    """Should return recent trades in reverse chronological order."""
    allocator = MockCapitalAllocator()
    guardian = MockRiskGuardian()
    executor = MockPaperExecutor()
    service = DashboardService(allocator=allocator, guardian=guardian, executor=executor)

    trades = service.get_recent_trades(limit=10)

    assert len(trades) == 2
    # Most recent first
    assert trades[0]["id"] == "trade-002"
    assert trades[1]["id"] == "trade-001"
    assert trades[0]["amount"] == Decimal("100")
