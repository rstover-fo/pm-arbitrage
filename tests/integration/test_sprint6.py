"""Integration test for Sprint 6: Dashboard Service with real agents."""

from decimal import Decimal

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.models import Side, Trade, TradeStatus
from pm_arb.dashboard.service import DashboardService


@pytest.mark.asyncio
async def test_dashboard_service_with_real_agents() -> None:
    """Dashboard service should work with real agent instances."""
    redis_url = "redis://localhost:6379"

    # Create real agents
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")
    allocator.register_strategy("cross-arb")

    # Simulate some performance
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("100")
    allocator._strategy_performance["oracle-sniper"]["trades"] = 8
    allocator._strategy_performance["oracle-sniper"]["wins"] = 6
    allocator._strategy_performance["oracle-sniper"]["losses"] = 2

    allocator._strategy_performance["cross-arb"]["total_pnl"] = Decimal("-20")
    allocator._strategy_performance["cross-arb"]["trades"] = 4
    allocator._strategy_performance["cross-arb"]["wins"] = 1
    allocator._strategy_performance["cross-arb"]["losses"] = 3

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
    )
    guardian._current_value = Decimal("1080")
    guardian._high_water_mark = Decimal("1100")
    guardian._daily_pnl = Decimal("30")

    executor = PaperExecutorAgent(redis_url=redis_url)
    # Add a mock trade
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

    # Create dashboard service
    service = DashboardService(
        allocator=allocator,
        guardian=guardian,
        executor=executor,
    )

    # Test strategy summary
    strategies = service.get_strategy_summary()
    assert len(strategies) == 2
    assert strategies[0]["strategy"] == "oracle-sniper"  # Sorted by PnL
    assert strategies[0]["total_pnl"] == Decimal("100")
    assert strategies[0]["win_rate"] == Decimal("0.75")

    # Test risk state
    risk = service.get_risk_state()
    assert risk["current_value"] == Decimal("1080")
    assert risk["drawdown_pct"] < Decimal("0.02")  # Less than 2%
    assert risk["halted"] is False

    # Test portfolio summary
    portfolio = service.get_portfolio_summary()
    assert portfolio["total_capital"] == Decimal("1000")
    assert portfolio["total_pnl"] == Decimal("80")  # 100 - 20
    assert portfolio["total_trades"] == 12  # 8 + 4

    # Test recent trades
    trades = service.get_recent_trades()
    assert len(trades) == 1
    assert trades[0]["id"] == "paper-test"

    print(f"\nStrategies: {strategies}")
    print(f"Risk: {risk}")
    print(f"Portfolio: {portfolio}")
    print(f"Trades: {trades}")
