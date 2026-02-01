# Sprint 7: Live Agent Connection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the Streamlit dashboard to live running agents via Redis, replacing mock data with real-time agent state.

**Architecture:** Create an AgentRegistry that stores agent references by name, allowing the DashboardService to retrieve live agent instances. A background runner script starts all agents, and the dashboard connects to them via shared Redis state. State sync happens through Redis pub/sub snapshots.

**Tech Stack:** Python 3.12, Streamlit, Redis, asyncio, structlog

**Demo:** Start agents → Start dashboard → See live data updating → Execute trades → Watch metrics change in real-time.

---

## Task 7.1: Agent Registry

**Files:**
- Create: `src/pm_arb/core/registry.py`
- Create: `tests/core/test_registry.py`

**Step 1: Write the failing test**

Create `tests/core/test_registry.py`:

```python
"""Tests for Agent Registry."""

import pytest

from pm_arb.core.registry import AgentRegistry


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_register_and_get_agent() -> None:
    """Should register and retrieve an agent by name."""
    registry = AgentRegistry()
    agent = MockAgent("test-agent")

    registry.register(agent)
    retrieved = registry.get("test-agent")

    assert retrieved is agent


def test_get_unknown_agent_returns_none() -> None:
    """Should return None for unknown agent."""
    registry = AgentRegistry()

    result = registry.get("unknown")

    assert result is None


def test_list_agents() -> None:
    """Should list all registered agent names."""
    registry = AgentRegistry()
    registry.register(MockAgent("agent-a"))
    registry.register(MockAgent("agent-b"))

    names = registry.list_agents()

    assert set(names) == {"agent-a", "agent-b"}


def test_clear_registry() -> None:
    """Should clear all registered agents."""
    registry = AgentRegistry()
    registry.register(MockAgent("agent"))

    registry.clear()

    assert registry.get("agent") is None
    assert registry.list_agents() == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_registry.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/core/registry.py`:

```python
"""Agent Registry - central registry for agent instances."""

from typing import Any, Protocol


class AgentProtocol(Protocol):
    """Protocol for agent interface."""

    name: str


class AgentRegistry:
    """Central registry for agent instances."""

    _instance: "AgentRegistry | None" = None
    _agents: dict[str, Any]

    def __new__(cls) -> "AgentRegistry":
        """Singleton pattern for global registry access."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
        return cls._instance

    def register(self, agent: AgentProtocol) -> None:
        """Register an agent by its name."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> Any | None:
        """Get an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def clear(self) -> None:
        """Clear all registered agents."""
        self._agents.clear()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing."""
        cls._instance = None
```

**Step 4: Run test**

Run: `pytest tests/core/test_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/core/registry.py tests/core/test_registry.py
git commit -m "feat: add Agent Registry for centralized agent access"
```

---

## Task 7.2: State Snapshot Publisher

**Files:**
- Modify: `src/pm_arb/agents/capital_allocator.py`
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `src/pm_arb/agents/paper_executor.py`
- Create: `tests/agents/test_state_snapshots.py`

**Step 1: Write the failing test**

Create `tests/agents/test_state_snapshots.py`:

```python
"""Tests for agent state snapshot publishing."""

from decimal import Decimal

import pytest

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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_state_snapshots.py -v`
Expected: FAIL (AttributeError: 'CapitalAllocatorAgent' object has no attribute 'get_state_snapshot')

**Step 3: Add get_state_snapshot to CapitalAllocatorAgent**

Add to `src/pm_arb/agents/capital_allocator.py` (at end of class):

```python
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
```

**Step 4: Add get_state_snapshot to RiskGuardianAgent**

Add to `src/pm_arb/agents/risk_guardian.py` (at end of class):

```python
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
```

**Step 5: Add get_state_snapshot to PaperExecutorAgent**

Add to `src/pm_arb/agents/paper_executor.py` (at end of class):

```python
    def get_state_snapshot(self) -> dict[str, Any]:
        """Return trade history snapshot for dashboard."""
        recent = self._trades[-50:]  # Last 50 trades
        return {
            "trade_count": len(self._trades),
            "recent_trades": [
                {
                    "id": t.id,
                    "request_id": t.request_id,
                    "market_id": t.market_id,
                    "venue": t.venue,
                    "side": t.side.value,
                    "outcome": t.outcome,
                    "amount": t.amount,
                    "price": t.price,
                    "fees": t.fees,
                    "status": t.status.value,
                    "executed_at": t.executed_at.isoformat(),
                }
                for t in reversed(recent)  # Most recent first
            ],
        }
```

**Step 6: Run test**

Run: `pytest tests/agents/test_state_snapshots.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/pm_arb/agents/capital_allocator.py src/pm_arb/agents/risk_guardian.py src/pm_arb/agents/paper_executor.py tests/agents/test_state_snapshots.py
git commit -m "feat: add state snapshot methods to agents for dashboard"
```

---

## Task 7.3: Live Dashboard Service

**Files:**
- Modify: `src/pm_arb/dashboard/service.py`
- Modify: `tests/dashboard/test_service.py`

**Step 1: Write the failing test**

Add to `tests/dashboard/test_service.py`:

```python
def test_create_from_registry() -> None:
    """Should create service from agent registry."""
    from pm_arb.core.registry import AgentRegistry

    # Reset registry for clean test
    AgentRegistry.reset_instance()
    registry = AgentRegistry()

    allocator = MockCapitalAllocator()
    allocator.name = "capital-allocator"
    guardian = MockRiskGuardian()
    guardian.name = "risk-guardian"
    executor = MockPaperExecutor()
    executor.name = "paper-executor"

    registry.register(allocator)
    registry.register(guardian)
    registry.register(executor)

    service = DashboardService.from_registry(registry)

    assert service.get_portfolio_summary()["total_capital"] == Decimal("1000")
    assert len(service.get_recent_trades()) == 2

    # Cleanup
    AgentRegistry.reset_instance()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/dashboard/test_service.py::test_create_from_registry -v`
Expected: FAIL (AttributeError: type object 'DashboardService' has no attribute 'from_registry')

**Step 3: Add from_registry class method**

Add to `src/pm_arb/dashboard/service.py` (before `__init__`):

```python
    @classmethod
    def from_registry(cls, registry: Any) -> "DashboardService":
        """Create service from agent registry."""
        allocator = registry.get("capital-allocator")
        guardian = registry.get("risk-guardian")
        executor = registry.get("paper-executor")

        if not allocator:
            raise ValueError("capital-allocator not found in registry")
        if not guardian:
            raise ValueError("risk-guardian not found in registry")

        return cls(allocator=allocator, guardian=guardian, executor=executor)
```

**Step 4: Run test**

Run: `pytest tests/dashboard/test_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/dashboard/service.py tests/dashboard/test_service.py
git commit -m "feat: add from_registry factory method to DashboardService"
```

---

## Task 7.4: Agent Runner Script

**Files:**
- Create: `scripts/run_agents.py`

**Step 1: Create agent runner script**

Create `scripts/run_agents.py`:

```python
#!/usr/bin/env python3
"""Script to run all PM Arbitrage agents."""

import asyncio
import signal
import sys
from decimal import Decimal

import structlog

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.core.registry import AgentRegistry
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


async def main() -> None:
    """Run all agents."""
    redis_url = "redis://localhost:6379"
    registry = AgentRegistry()

    # Create agents
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
    )

    executor = PaperExecutorAgent(redis_url=redis_url)

    scanner = OpportunityScannerAgent(redis_url=redis_url)

    strategy = StrategyAgent(
        redis_url=redis_url,
        strategy=OracleSniperStrategy(),
    )

    # Register agents
    registry.register(allocator)
    registry.register(guardian)
    registry.register(executor)
    registry.register(scanner)
    registry.register(strategy)

    # Start all agents
    agents = [allocator, guardian, executor, scanner, strategy]

    logger.info("starting_agents", count=len(agents))

    # Handle shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(sig: int) -> None:
        logger.info("shutdown_signal_received", signal=sig)
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, lambda s=sig: handle_signal(s))

    # Start agents
    tasks = [asyncio.create_task(agent.run()) for agent in agents]

    logger.info(
        "agents_running",
        agents=[a.name for a in agents],
        registry_agents=registry.list_agents(),
    )

    # Wait for shutdown
    await shutdown_event.wait()

    # Stop agents
    logger.info("stopping_agents")
    for agent in agents:
        await agent.stop()

    # Cancel tasks
    for task in tasks:
        task.cancel()

    logger.info("agents_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

**Step 2: Make script executable**

```bash
chmod +x scripts/run_agents.py
```

**Step 3: Verify script syntax**

Run: `python -m py_compile scripts/run_agents.py`
Expected: No output (success)

**Step 4: Commit**

```bash
git add scripts/run_agents.py
git commit -m "feat: add agent runner script"
```

---

## Task 7.5: Live Dashboard App

**Files:**
- Create: `src/pm_arb/dashboard/app_live.py`

**Step 1: Create live dashboard app**

Create `src/pm_arb/dashboard/app_live.py`:

```python
"""Streamlit Dashboard connected to live agents."""

import pandas as pd
import plotly.express as px
import streamlit as st

from pm_arb.core.registry import AgentRegistry
from pm_arb.dashboard.service import DashboardService

st.set_page_config(
    page_title="PM Arbitrage Dashboard (Live)",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def get_service() -> DashboardService | None:
    """Get dashboard service from registry."""
    try:
        registry = AgentRegistry()
        return DashboardService.from_registry(registry)
    except ValueError as e:
        st.error(f"Agents not running: {e}")
        return None


def main() -> None:
    """Main dashboard entry point."""
    st.title("📊 PM Arbitrage Dashboard (Live)")

    service = get_service()
    if not service:
        st.warning("Start agents with: `python scripts/run_agents.py`")
        st.stop()

    # Auto-refresh
    auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=True)
    if auto_refresh:
        import time

        time.sleep(5)
        st.rerun()

    st.markdown("---")

    # Navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Overview", "Strategies", "Trades", "Risk", "System"],
    )

    if page == "Overview":
        render_overview(service)
    elif page == "Strategies":
        render_strategies(service)
    elif page == "Trades":
        render_trades(service)
    elif page == "Risk":
        render_risk(service)
    elif page == "System":
        render_system(service)


def render_overview(service: DashboardService) -> None:
    """Render overview page."""
    st.header("Portfolio Overview")

    portfolio = service.get_portfolio_summary()
    strategies = service.get_strategy_summary()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Capital", f"${portfolio['total_capital']:,.0f}")

    with col2:
        pnl = portfolio["total_pnl"]
        pnl_pct = (pnl / portfolio["total_capital"]) * 100 if portfolio["total_capital"] else 0
        st.metric(
            "Current Value",
            f"${portfolio['current_value']:,.0f}",
            delta=f"${pnl:,.0f} ({pnl_pct:.1f}%)",
        )

    with col3:
        st.metric("Total Trades", f"{portfolio['total_trades']}")

    with col4:
        st.metric("Win Rate", f"{portfolio['overall_win_rate'] * 100:.0f}%")

    st.markdown("---")

    if strategies:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Capital Allocation")
            df = pd.DataFrame(strategies)
            fig = px.pie(df, values="allocation_pct", names="strategy", hole=0.4)
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.subheader("Strategy P&L")
            df = pd.DataFrame(strategies)
            fig = px.bar(
                df, x="strategy", y="total_pnl", color="total_pnl",
                color_continuous_scale=["red", "green"], color_continuous_midpoint=0
            )
            fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No strategies registered yet")


def render_strategies(service: DashboardService) -> None:
    """Render strategies page."""
    st.header("Strategy Performance")

    strategies = service.get_strategy_summary()
    if not strategies:
        st.info("No strategies registered")
        return

    df = pd.DataFrame(strategies)
    df["total_pnl"] = df["total_pnl"].apply(lambda x: f"${x:,.2f}")
    df["win_rate"] = df["win_rate"].apply(lambda x: f"{x * 100:.0f}%")
    df["allocation_pct"] = df["allocation_pct"].apply(lambda x: f"{x * 100:.0f}%")
    df["largest_win"] = df["largest_win"].apply(lambda x: f"${x:,.2f}")
    df["largest_loss"] = df["largest_loss"].apply(lambda x: f"${x:,.2f}")

    df.columns = [
        "Strategy", "Total P&L", "Trades", "Wins", "Losses",
        "Win Rate", "Largest Win", "Largest Loss", "Allocation"
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_trades(service: DashboardService) -> None:
    """Render trades page."""
    st.header("Trade History")

    trades = service.get_recent_trades()
    if not trades:
        st.info("No trades executed yet")
        return

    df = pd.DataFrame(trades)
    df["amount"] = df["amount"].apply(lambda x: f"${x:,.2f}")
    df["price"] = df["price"].apply(lambda x: f"{x:.2f}")

    display_df = df[["executed_at", "market_id", "side", "outcome", "amount", "price", "status"]]
    display_df.columns = ["Time", "Market", "Side", "Outcome", "Amount", "Price", "Status"]
    st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_risk(service: DashboardService) -> None:
    """Render risk page."""
    st.header("Risk Monitor")

    risk = service.get_risk_state()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Current Value", f"${risk['current_value']:,.0f}")

    with col2:
        st.metric("High Water Mark", f"${risk['high_water_mark']:,.0f}")

    with col3:
        drawdown_pct = risk["drawdown_pct"] * 100
        st.metric("Drawdown", f"${risk['drawdown']:,.0f}", delta=f"-{drawdown_pct:.1f}%", delta_color="inverse")

    with col4:
        daily = risk["daily_pnl"]
        st.metric("Daily P&L", f"${daily:,.0f}", delta="positive" if daily > 0 else "negative")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Position Exposure")
        positions = risk["positions"]
        if positions:
            pos_df = pd.DataFrame([{"Market": k, "Exposure": f"${v:,.0f}"} for k, v in positions.items()])
            st.dataframe(pos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No open positions")

    with col2:
        st.subheader("Platform Exposure")
        platforms = risk["platform_exposure"]
        if platforms:
            plat_df = pd.DataFrame([{"Platform": k, "Exposure": f"${v:,.0f}"} for k, v in platforms.items()])
            st.dataframe(plat_df, use_container_width=True, hide_index=True)
        else:
            st.info("No platform exposure")


def render_system(service: DashboardService) -> None:
    """Render system page."""
    st.header("System Control")

    risk = service.get_risk_state()
    registry = AgentRegistry()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("System Status")
        if risk["halted"]:
            st.error("🔴 System HALTED")
        else:
            st.success("🟢 System Running")

        st.subheader("Registered Agents")
        agents = registry.list_agents()
        for agent in agents:
            st.write(f"✓ {agent}")

    with col2:
        st.subheader("Controls")
        if st.button("🛑 HALT ALL", type="primary"):
            st.warning("⚠️ HALT command would be sent to message bus")


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

Run: `python -m py_compile src/pm_arb/dashboard/app_live.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add src/pm_arb/dashboard/app_live.py
git commit -m "feat: add live dashboard app connected to agent registry"
```

---

## Task 7.6: Update Run Scripts

**Files:**
- Modify: `scripts/run_dashboard.py`

**Step 1: Update run script with mode selection**

Replace `scripts/run_dashboard.py`:

```python
#!/usr/bin/env python3
"""Script to run the PM Arbitrage dashboard."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run the Streamlit dashboard."""
    project_root = Path(__file__).parent.parent

    # Parse mode argument
    mode = "mock"
    if len(sys.argv) > 1 and sys.argv[1] == "--live":
        mode = "live"

    if mode == "live":
        app_path = project_root / "src" / "pm_arb" / "dashboard" / "app_live.py"
        title = "PM Arbitrage Dashboard (Live)"
    else:
        app_path = project_root / "src" / "pm_arb" / "dashboard" / "app.py"
        title = "PM Arbitrage Dashboard (Mock)"

    if not app_path.exists():
        print(f"Error: Dashboard app not found at {app_path}")
        sys.exit(1)

    print(f"🚀 Starting {title}...")
    print(f"   App: {app_path}")
    print("   URL: http://localhost:8501")
    if mode == "live":
        print("   Note: Requires agents running (python scripts/run_agents.py)")
    print()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(app_path),
            "--server.headless",
            "false",
            "--browser.gatherUsageStats",
            "false",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
```

**Step 2: Verify syntax**

Run: `python -m py_compile scripts/run_dashboard.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add scripts/run_dashboard.py
git commit -m "feat: add --live mode to dashboard run script"
```

---

## Task 7.7: Sprint 7 Integration Test

**Files:**
- Create: `tests/integration/test_sprint7.py`

**Step 1: Write integration test**

Create `tests/integration/test_sprint7.py`:

```python
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
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_sprint7.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/test_sprint7.py
git commit -m "test: add Sprint 7 integration test - live dashboard via registry"
```

---

## Task 7.8: Sprint 7 Final Commit

**Step 1: Run all tests**

Run: `pytest tests/ -v --ignore=tests/integration/test_sprint2.py --ignore=tests/integration/test_sprint3.py`
Expected: All pass

**Step 2: Lint and type check**

Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`
Run: `mypy src/`
Expected: Clean

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: Sprint 7 complete - Live Agent Dashboard Connection

- AgentRegistry for centralized agent access
- State snapshot methods on all agents
- DashboardService.from_registry() factory method
- Agent runner script for starting all agents
- Live dashboard app connected to registry
- --live mode for dashboard run script
- Integration test verifying registry flow

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Sprint 7 Complete

**Demo steps:**
1. Terminal 1: `python scripts/run_agents.py` (start agents)
2. Terminal 2: `python scripts/run_dashboard.py --live` (start live dashboard)
3. Open http://localhost:8501
4. Watch live metrics from running agents

**What we built:**
- AgentRegistry singleton for centralized agent access
- State snapshot methods on all agents
- Live dashboard connected to real agent instances
- Dual-mode run script (mock vs live)
- Agent runner script for starting all agents

**Data flow:**
```
Agents (running)
       ↓
AgentRegistry (singleton)
       ↓
DashboardService.from_registry()
       ↓
Streamlit App (live visualization)
```

**Next: Sprint 8 - WebSocket Real-Time Updates (push updates instead of polling)**
