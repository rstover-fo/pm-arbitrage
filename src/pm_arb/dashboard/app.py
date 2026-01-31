"""Streamlit Dashboard for PM Arbitrage System."""

import pandas as pd
import plotly.express as px
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
    display_df = df[["executed_at", "market_id", "side", "outcome", "amount", "price", "status"]]
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
