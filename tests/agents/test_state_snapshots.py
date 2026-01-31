"""Tests for agent state snapshot publishing."""

from decimal import Decimal

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent


def test_allocator_get_state_snapshot() -> None:
    """Should return complete state snapshot."""
    allocator = CapitalAllocatorAgent(
        redis_url="redis://localhost:6379",
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("100")
    allocator._strategy_performance["oracle-sniper"]["trades"] = 5

    snapshot = allocator.get_state_snapshot()

    assert snapshot["total_capital"] == Decimal("1000")
    assert "oracle-sniper" in snapshot["strategies"]
    assert snapshot["strategies"]["oracle-sniper"]["total_pnl"] == Decimal("100")


def test_guardian_get_state_snapshot() -> None:
    """Should return risk state snapshot."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("1000"),
    )
    guardian._current_value = Decimal("950")
    guardian._daily_pnl = Decimal("-50")

    snapshot = guardian.get_state_snapshot()

    assert snapshot["current_value"] == Decimal("950")
    assert snapshot["daily_pnl"] == Decimal("-50")
    assert snapshot["halted"] is False


def test_executor_get_state_snapshot() -> None:
    """Should return trade history snapshot."""
    from pm_arb.core.models import Side, Trade, TradeStatus

    executor = PaperExecutorAgent(redis_url="redis://localhost:6379")
    executor._trades.append(
        Trade(
            id="paper-test",
            request_id="req-test",
            market_id="polymarket:btc-100k",
            venue="polymarket",
            side=Side.BUY,
            outcome="YES",
            amount=Decimal("50"),
            price=Decimal("0.55"),
            status=TradeStatus.FILLED,
        )
    )

    snapshot = executor.get_state_snapshot()

    assert snapshot["trade_count"] == 1
    assert len(snapshot["recent_trades"]) == 1
    assert snapshot["recent_trades"][0]["id"] == "paper-test"
