"""Integration test for Sprint 7: Live Agent Dashboard Connection."""

from decimal import Decimal

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import Side, Trade, TradeStatus
from pm_arb.core.registry import AgentRegistry
from pm_arb.dashboard.service import DashboardService


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Reset registry before and after each test."""
    AgentRegistry.reset_instance()
    yield
    AgentRegistry.reset_instance()


@pytest.mark.asyncio
async def test_dashboard_via_registry_with_live_agents() -> None:
    """Dashboard should work via registry with real agent instances."""
    redis_url = "redis://localhost:6379"
    registry = AgentRegistry()

    # Create and register agents
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("150")
    allocator._strategy_performance["oracle-sniper"]["trades"] = 10
    allocator._strategy_performance["oracle-sniper"]["wins"] = 7
    allocator._strategy_performance["oracle-sniper"]["losses"] = 3

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
    )
    guardian._current_value = Decimal("1150")
    guardian._high_water_mark = Decimal("1150")

    executor = PaperExecutorAgent(redis_url=redis_url)
    executor._trades.append(
        Trade(
            id="paper-live-test",
            request_id="req-live",
            market_id="polymarket:btc-100k",
            venue="polymarket",
            side=Side.BUY,
            outcome="YES",
            amount=Decimal("50"),
            price=Decimal("0.55"),
            status=TradeStatus.FILLED,
        )
    )

    # Register agents
    registry.register(allocator)
    registry.register(guardian)
    registry.register(executor)

    # Create service from registry
    service = DashboardService.from_registry(registry)

    # Verify data flows through
    portfolio = service.get_portfolio_summary()
    assert portfolio["total_capital"] == Decimal("1000")
    assert portfolio["current_value"] == Decimal("1150")
    assert portfolio["total_pnl"] == Decimal("150")

    strategies = service.get_strategy_summary()
    assert len(strategies) == 1
    assert strategies[0]["strategy"] == "oracle-sniper"
    assert strategies[0]["win_rate"] == Decimal("0.70")

    trades = service.get_recent_trades()
    assert len(trades) == 1
    assert trades[0]["id"] == "paper-live-test"

    risk = service.get_risk_state()
    assert risk["halted"] is False

    # Verify state snapshots work
    allocator_snapshot = allocator.get_state_snapshot()
    assert allocator_snapshot["total_capital"] == Decimal("1000")

    guardian_snapshot = guardian.get_state_snapshot()
    assert guardian_snapshot["current_value"] == Decimal("1150")

    executor_snapshot = executor.get_state_snapshot()
    assert executor_snapshot["trade_count"] == 1

    print(f"\nPortfolio: {portfolio}")
    print(f"Strategies: {strategies}")
    print(f"Trades: {trades}")
    print(f"Registry agents: {registry.list_agents()}")
