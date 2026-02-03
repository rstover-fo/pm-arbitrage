"""Streamlit Dashboard connected to live agents."""

import pandas as pd
import plotly.express as px
import streamlit as st
import structlog

from pm_arb.core.registry import AgentRegistry
from pm_arb.dashboard.service import DashboardService

logger = structlog.get_logger()

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
        logger.error("dashboard_service_init_failed", error=str(e))
        st.error("Agents not running. Start with: python scripts/run_agents.py")
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
                df,
                x="strategy",
                y="total_pnl",
                color="total_pnl",
                color_continuous_scale=["red", "green"],
                color_continuous_midpoint=0,
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
        st.metric(
            "Drawdown",
            f"${risk['drawdown']:,.0f}",
            delta=f"-{drawdown_pct:.1f}%",
            delta_color="inverse",
        )

    with col4:
        daily = risk["daily_pnl"]
        st.metric("Daily P&L", f"${daily:,.0f}", delta="positive" if daily > 0 else "negative")

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Position Exposure")
        positions = risk["positions"]
        if positions:
            pos_data = [{"Market": k, "Exposure": f"${v:,.0f}"} for k, v in positions.items()]
            pos_df = pd.DataFrame(pos_data)
            st.dataframe(pos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No open positions")

    with col2:
        st.subheader("Platform Exposure")
        platforms = risk["platform_exposure"]
        if platforms:
            plat_data = [{"Platform": k, "Exposure": f"${v:,.0f}"} for k, v in platforms.items()]
            plat_df = pd.DataFrame(plat_data)
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

        st.subheader("Real-Time Connection")
        from pm_arb.dashboard.websocket_client import check_websocket_health

        ws_health = check_websocket_health()
        if ws_health.get("status") == "healthy":
            connections = ws_health.get("connections", 0)
            st.success(f"🟢 WebSocket Server Running ({connections} clients)")
        else:
            st.warning("🟡 WebSocket Server Not Running")
            st.caption("Start with: `python scripts/run_websocket.py`")

    with col2:
        st.subheader("Controls")
        if st.button("🛑 HALT ALL", type="primary"):
            st.warning("⚠️ HALT command would be sent to message bus")


if __name__ == "__main__":
    main()
