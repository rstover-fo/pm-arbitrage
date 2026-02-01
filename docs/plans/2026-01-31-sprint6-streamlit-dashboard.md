# Sprint 6: Streamlit Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a real-time monitoring dashboard using Streamlit to visualize strategy performance, trade flow, opportunities, and risk state.

**Architecture:** Dashboard reads from Redis Streams and agent state. A DashboardService class aggregates data from all agents. Streamlit pages render metrics, charts, and tables with auto-refresh. No database required—all state is in Redis and agent memory.

**Tech Stack:** Python 3.12, Streamlit, Plotly, Redis, asyncio

**Demo:** Start dashboard → See live strategy scoreboard → Watch trade flow → Monitor risk limits → Trigger halt from UI.

---

## Task 6.1: Dashboard Service Layer

**Files:**
- Create: `src/pm_arb/dashboard/service.py`
- Create: `src/pm_arb/dashboard/__init__.py`
- Create: `tests/dashboard/__init__.py`
- Create: `tests/dashboard/test_service.py`

**Step 1: Write the failing test**

Create `tests/dashboard/__init__.py`:
```python
"""Dashboard tests."""
```

Create `tests/dashboard/test_service.py`:

```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/dashboard/test_service.py -v`
Expected: FAIL (ModuleNotFoundError)

**Step 3: Write implementation**

Create `src/pm_arb/dashboard/__init__.py`:
```python
"""Dashboard package."""

from pm_arb.dashboard.service import DashboardService

__all__ = ["DashboardService"]
```

Create `src/pm_arb/dashboard/service.py`:

```python
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
```

**Step 4: Run test**

Run: `pytest tests/dashboard/test_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/dashboard/ tests/dashboard/
git commit -m "feat: add Dashboard Service for data aggregation"
```

---

## Task 6.2: Trade History Tracking

**Files:**
- Modify: `src/pm_arb/dashboard/service.py`
- Modify: `tests/dashboard/test_service.py`

**Step 1: Write the failing test**

Add to `tests/dashboard/test_service.py`:

```python
from datetime import UTC, datetime


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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/dashboard/test_service.py::test_get_recent_trades -v`
Expected: FAIL (TypeError - executor parameter)

**Step 3: Update implementation**

Update `src/pm_arb/dashboard/service.py`:

```python
"""Dashboard Service - aggregates data from agents for UI display."""

from decimal import Decimal
from typing import Any, Protocol

from pm_arb.core.models import Trade


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


class ExecutorProtocol(Protocol):
    """Protocol for Paper Executor interface."""

    _trades: list[Trade]


class DashboardService:
    """Aggregates data from agents for dashboard display."""

    def __init__(
        self,
        allocator: AllocatorProtocol,
        guardian: GuardianProtocol,
        executor: ExecutorProtocol | None = None,
    ) -> None:
        self._allocator = allocator
        self._guardian = guardian
        self._executor = executor

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

    def get_recent_trades(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent trades in reverse chronological order."""
        if not self._executor:
            return []

        trades = list(self._executor._trades)
        # Sort by executed_at descending
        trades.sort(key=lambda t: t.executed_at, reverse=True)

        return [
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
            for t in trades[:limit]
        ]
```

**Step 4: Run test**

Run: `pytest tests/dashboard/test_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/dashboard/service.py tests/dashboard/test_service.py
git commit -m "feat: add trade history to Dashboard Service"
```

---

## Task 6.3: Streamlit Main App

**Files:**
- Create: `src/pm_arb/dashboard/app.py`

**Step 1: Create Streamlit app**

Create `src/pm_arb/dashboard/app.py`:

```python
"""Streamlit Dashboard for PM Arbitrage System."""

import streamlit as st

st.set_page_config(
    page_title="PM Arbitrage Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Main dashboard entry point."""
    st.title("📊 PM Arbitrage Dashboard")
    st.markdown("---")

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Overview", "Strategies", "Trades", "Risk", "System"],
    )

    if page == "Overview":
        render_overview()
    elif page == "Strategies":
        render_strategies()
    elif page == "Trades":
        render_trades()
    elif page == "Risk":
        render_risk()
    elif page == "System":
        render_system()


def render_overview() -> None:
    """Render overview page with key metrics."""
    st.header("Portfolio Overview")

    # Placeholder metrics - will connect to real data in Task 6.4
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Capital",
            value="$1,000",
        )

    with col2:
        st.metric(
            label="Current Value",
            value="$1,125",
            delta="$125 (12.5%)",
        )

    with col3:
        st.metric(
            label="Total Trades",
            value="15",
        )

    with col4:
        st.metric(
            label="Win Rate",
            value="60%",
        )

    st.markdown("---")

    # Strategy allocation chart placeholder
    st.subheader("Capital Allocation")
    st.info("📈 Allocation chart will be rendered here")


def render_strategies() -> None:
    """Render strategy performance page."""
    st.header("Strategy Performance")

    st.info("📊 Strategy scoreboard will be rendered here")


def render_trades() -> None:
    """Render trade history page."""
    st.header("Trade History")

    st.info("📋 Trade history table will be rendered here")


def render_risk() -> None:
    """Render risk monitoring page."""
    st.header("Risk Monitor")

    st.info("⚠️ Risk metrics will be rendered here")


def render_system() -> None:
    """Render system control page."""
    st.header("System Control")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("System Status")
        st.success("🟢 System Running")

    with col2:
        st.subheader("Controls")
        if st.button("🛑 HALT ALL", type="primary"):
            st.warning("HALT command would be sent here")


if __name__ == "__main__":
    main()
```

**Step 2: Verify app runs**

Run: `cd /Users/robstover/Development/personal/pm-arbitrage && source .venv/bin/activate && streamlit run src/pm_arb/dashboard/app.py --server.headless true &`

Then: `curl -s http://localhost:8501 | head -20`
Expected: HTML response containing "PM Arbitrage Dashboard"

Stop: `pkill -f streamlit`

**Step 3: Commit**

```bash
git add src/pm_arb/dashboard/app.py
git commit -m "feat: add Streamlit dashboard skeleton"
```

---

## Task 6.4: Connect Dashboard to Mock Data

**Files:**
- Create: `src/pm_arb/dashboard/mock_data.py`
- Modify: `src/pm_arb/dashboard/app.py`

**Step 1: Create mock data provider**

Create `src/pm_arb/dashboard/mock_data.py`:

```python
"""Mock data for dashboard development and testing."""

from datetime import UTC, datetime
from decimal import Decimal


def get_mock_portfolio() -> dict:
    """Return mock portfolio summary."""
    return {
        "total_capital": Decimal("1000"),
        "current_value": Decimal("1125"),
        "total_pnl": Decimal("125"),
        "total_trades": 15,
        "total_wins": 9,
        "overall_win_rate": Decimal("0.60"),
        "strategy_count": 2,
    }


def get_mock_strategies() -> list[dict]:
    """Return mock strategy summaries."""
    return [
        {
            "strategy": "oracle-sniper",
            "total_pnl": Decimal("150"),
            "trades": 10,
            "wins": 7,
            "losses": 3,
            "win_rate": Decimal("0.70"),
            "largest_win": Decimal("50"),
            "largest_loss": Decimal("-20"),
            "allocation_pct": Decimal("0.60"),
        },
        {
            "strategy": "cross-arb",
            "total_pnl": Decimal("-25"),
            "trades": 5,
            "wins": 2,
            "losses": 3,
            "win_rate": Decimal("0.40"),
            "largest_win": Decimal("20"),
            "largest_loss": Decimal("-30"),
            "allocation_pct": Decimal("0.40"),
        },
    ]


def get_mock_risk_state() -> dict:
    """Return mock risk metrics."""
    return {
        "current_value": Decimal("1125"),
        "high_water_mark": Decimal("1150"),
        "drawdown": Decimal("25"),
        "drawdown_pct": Decimal("0.0217"),
        "daily_pnl": Decimal("45"),
        "initial_bankroll": Decimal("1000"),
        "positions": {
            "polymarket:btc-100k": Decimal("100"),
            "polymarket:eth-5k": Decimal("50"),
        },
        "platform_exposure": {
            "polymarket": Decimal("150"),
        },
        "halted": False,
    }


def get_mock_trades() -> list[dict]:
    """Return mock recent trades."""
    return [
        {
            "id": "paper-abc123",
            "request_id": "req-001",
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "side": "buy",
            "outcome": "YES",
            "amount": Decimal("50"),
            "price": Decimal("0.55"),
            "fees": Decimal("0.05"),
            "status": "filled",
            "executed_at": datetime(2026, 1, 31, 14, 30, 0, tzinfo=UTC).isoformat(),
        },
        {
            "id": "paper-def456",
            "request_id": "req-002",
            "market_id": "polymarket:eth-5k",
            "venue": "polymarket",
            "side": "buy",
            "outcome": "NO",
            "amount": Decimal("30"),
            "price": Decimal("0.40"),
            "fees": Decimal("0.03"),
            "status": "filled",
            "executed_at": datetime(2026, 1, 31, 14, 15, 0, tzinfo=UTC).isoformat(),
        },
        {
            "id": "paper-ghi789",
            "request_id": "req-003",
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "side": "sell",
            "outcome": "YES",
            "amount": Decimal("25"),
            "price": Decimal("0.65"),
            "fees": Decimal("0.025"),
            "status": "filled",
            "executed_at": datetime(2026, 1, 31, 14, 0, 0, tzinfo=UTC).isoformat(),
        },
    ]
```

**Step 2: Update app to use mock data**

Replace `src/pm_arb/dashboard/app.py`:

```python
"""Streamlit Dashboard for PM Arbitrage System."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from pm_arb.dashboard.mock_data import (
    get_mock_portfolio,
    get_mock_risk_state,
    get_mock_strategies,
    get_mock_trades,
)

st.set_page_config(
    page_title="PM Arbitrage Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Main dashboard entry point."""
    st.title("📊 PM Arbitrage Dashboard")

    # Auto-refresh toggle
    auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=False)
    if auto_refresh:
        st.rerun()

    st.markdown("---")

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Overview", "Strategies", "Trades", "Risk", "System"],
    )

    if page == "Overview":
        render_overview()
    elif page == "Strategies":
        render_strategies()
    elif page == "Trades":
        render_trades()
    elif page == "Risk":
        render_risk()
    elif page == "System":
        render_system()


def render_overview() -> None:
    """Render overview page with key metrics."""
    st.header("Portfolio Overview")

    portfolio = get_mock_portfolio()
    strategies = get_mock_strategies()

    # Key metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Capital",
            value=f"${portfolio['total_capital']:,.0f}",
        )

    with col2:
        pnl = portfolio["total_pnl"]
        pnl_pct = (pnl / portfolio["total_capital"]) * 100
        st.metric(
            label="Current Value",
            value=f"${portfolio['current_value']:,.0f}",
            delta=f"${pnl:,.0f} ({pnl_pct:.1f}%)",
        )

    with col3:
        st.metric(
            label="Total Trades",
            value=f"{portfolio['total_trades']}",
        )

    with col4:
        st.metric(
            label="Win Rate",
            value=f"{portfolio['overall_win_rate'] * 100:.0f}%",
        )

    st.markdown("---")

    # Capital allocation pie chart
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Capital Allocation")
        df = pd.DataFrame(strategies)
        fig = px.pie(
            df,
            values="allocation_pct",
            names="strategy",
            hole=0.4,
            color_discrete_sequence=px.colors.qualitative.Set2,
        )
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Strategy P&L")
        df = pd.DataFrame(strategies)
        fig = px.bar(
            df,
            x="strategy",
            y="total_pnl",
            color="total_pnl",
            color_continuous_scale=["red", "green"],
            color_continuous_midpoint=0,
        )
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)


def render_strategies() -> None:
    """Render strategy performance page."""
    st.header("Strategy Performance")

    strategies = get_mock_strategies()
    df = pd.DataFrame(strategies)

    # Format for display
    df["total_pnl"] = df["total_pnl"].apply(lambda x: f"${x:,.2f}")
    df["win_rate"] = df["win_rate"].apply(lambda x: f"{x * 100:.0f}%")
    df["allocation_pct"] = df["allocation_pct"].apply(lambda x: f"{x * 100:.0f}%")
    df["largest_win"] = df["largest_win"].apply(lambda x: f"${x:,.2f}")
    df["largest_loss"] = df["largest_loss"].apply(lambda x: f"${x:,.2f}")

    # Rename columns
    df.columns = [
        "Strategy",
        "Total P&L",
        "Trades",
        "Wins",
        "Losses",
        "Win Rate",
        "Largest Win",
        "Largest Loss",
        "Allocation",
    ]

    st.dataframe(df, use_container_width=True, hide_index=True)


def render_trades() -> None:
    """Render trade history page."""
    st.header("Trade History")

    trades = get_mock_trades()
    df = pd.DataFrame(trades)

    # Format for display
    df["amount"] = df["amount"].apply(lambda x: f"${x:,.2f}")
    df["price"] = df["price"].apply(lambda x: f"{x:.2f}")
    df["fees"] = df["fees"].apply(lambda x: f"${x:,.3f}")

    # Select columns
    display_df = df[
        ["executed_at", "market_id", "side", "outcome", "amount", "price", "status"]
    ]
    display_df.columns = ["Time", "Market", "Side", "Outcome", "Amount", "Price", "Status"]

    st.dataframe(display_df, use_container_width=True, hide_index=True)


def render_risk() -> None:
    """Render risk monitoring page."""
    st.header("Risk Monitor")

    risk = get_mock_risk_state()

    # Risk metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Current Value",
            value=f"${risk['current_value']:,.0f}",
        )

    with col2:
        st.metric(
            label="High Water Mark",
            value=f"${risk['high_water_mark']:,.0f}",
        )

    with col3:
        st.metric(
            label="Drawdown",
            value=f"${risk['drawdown']:,.0f}",
            delta=f"-{risk['drawdown_pct'] * 100:.1f}%",
            delta_color="inverse",
        )

    with col4:
        daily = risk["daily_pnl"]
        st.metric(
            label="Daily P&L",
            value=f"${daily:,.0f}",
            delta="positive" if daily > 0 else "negative",
        )

    st.markdown("---")

    # Position exposure
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Position Exposure")
        positions = risk["positions"]
        if positions:
            pos_df = pd.DataFrame(
                [{"Market": k, "Exposure": f"${v:,.0f}"} for k, v in positions.items()]
            )
            st.dataframe(pos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No open positions")

    with col2:
        st.subheader("Platform Exposure")
        platforms = risk["platform_exposure"]
        if platforms:
            plat_df = pd.DataFrame(
                [{"Platform": k, "Exposure": f"${v:,.0f}"} for k, v in platforms.items()]
            )
            st.dataframe(plat_df, use_container_width=True, hide_index=True)
        else:
            st.info("No platform exposure")


def render_system() -> None:
    """Render system control page."""
    st.header("System Control")

    risk = get_mock_risk_state()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("System Status")
        if risk["halted"]:
            st.error("🔴 System HALTED")
        else:
            st.success("🟢 System Running")

    with col2:
        st.subheader("Controls")
        if st.button("🛑 HALT ALL", type="primary"):
            st.warning("⚠️ HALT command would be sent to message bus")
            st.info("In production, this sends HALT_ALL to system.commands channel")


if __name__ == "__main__":
    main()
```

**Step 3: Verify app runs with charts**

Run: `streamlit run src/pm_arb/dashboard/app.py --server.headless true &`
Then manually verify: `open http://localhost:8501`
Expected: Dashboard with charts, metrics, and tables
Stop: `pkill -f streamlit`

**Step 4: Commit**

```bash
git add src/pm_arb/dashboard/mock_data.py src/pm_arb/dashboard/app.py
git commit -m "feat: connect dashboard to mock data with charts"
```

---

## Task 6.5: Add Run Script and Dependencies

**Files:**
- Modify: `pyproject.toml` (verify dashboard deps)
- Create: `scripts/run_dashboard.py`

**Step 1: Verify dependencies in pyproject.toml**

Check that `pyproject.toml` has:
```toml
[project.optional-dependencies]
dashboard = [
    "streamlit>=1.31.0",
    "plotly>=5.18.0",
]
```

If missing, add them.

**Step 2: Create run script**

Create `scripts/run_dashboard.py`:

```python
#!/usr/bin/env python3
"""Script to run the PM Arbitrage dashboard."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run the Streamlit dashboard."""
    # Get the path to app.py
    project_root = Path(__file__).parent.parent
    app_path = project_root / "src" / "pm_arb" / "dashboard" / "app.py"

    if not app_path.exists():
        print(f"Error: Dashboard app not found at {app_path}")
        sys.exit(1)

    print("🚀 Starting PM Arbitrage Dashboard...")
    print(f"   App: {app_path}")
    print("   URL: http://localhost:8501")
    print()

    # Run streamlit
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

**Step 3: Make script executable**

```bash
chmod +x scripts/run_dashboard.py
```

**Step 4: Test run script**

Run: `python scripts/run_dashboard.py &`
Expected: Dashboard starts at http://localhost:8501
Stop: `pkill -f streamlit`

**Step 5: Commit**

```bash
git add scripts/run_dashboard.py pyproject.toml
git commit -m "feat: add dashboard run script"
```

---

## Task 6.6: Sprint 6 Integration Test

**Files:**
- Create: `tests/integration/test_sprint6.py`

**Step 1: Write integration test**

Create `tests/integration/test_sprint6.py`:

```python
"""Integration test for Sprint 6: Dashboard Service with real agents."""

from decimal import Decimal
from typing import Any

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
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_sprint6.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/test_sprint6.py
git commit -m "test: add Sprint 6 integration test - dashboard with real agents"
```

---

## Task 6.7: Sprint 6 Final Commit

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
git commit -m "chore: Sprint 6 complete - Streamlit Dashboard

- DashboardService for data aggregation
- Streamlit app with Overview, Strategies, Trades, Risk, System pages
- Plotly charts for allocation and P&L
- Mock data provider for development
- Run script for easy startup
- Integration test with real agents

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Sprint 6 Complete

**Demo steps:**
1. `pip install -e ".[dashboard]"` (if not already)
2. `python scripts/run_dashboard.py`
3. Open http://localhost:8501
4. Navigate pages: Overview → Strategies → Trades → Risk → System

**What we built:**
- DashboardService class for data aggregation
- Streamlit app with 5 pages
- Plotly charts (pie chart, bar chart)
- Risk monitoring display
- System control placeholder (HALT button)
- Mock data for standalone testing

**Data flow:**
```
Agents (in-memory state)
       ↓
DashboardService (aggregation)
       ↓
Streamlit App (visualization)
```

**Next: Sprint 7 - Live Agent Connection (connect dashboard to running agents via Redis)**
