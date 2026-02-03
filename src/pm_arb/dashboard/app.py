"""Streamlit Dashboard for PM Arbitrage System."""

import asyncio
from datetime import datetime

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


@st.cache_resource
def get_cached_db_pool():
    """Get cached database pool for dashboard."""
    from pm_arb.db import get_pool, init_db

    async def _get_pool():
        await init_db()
        return await get_pool()

    return asyncio.run(_get_pool())


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
        ["Overview", "Pilot Monitor", "Strategies", "Trades", "Risk", "System", "How It Works"],
    )

    if page == "Overview":
        render_overview()
    elif page == "Pilot Monitor":
        render_pilot_monitor()
    elif page == "Strategies":
        render_strategies()
    elif page == "Trades":
        render_trades()
    elif page == "Risk":
        render_risk()
    elif page == "System":
        render_system()
    elif page == "How It Works":
        render_how_it_works()


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


def render_pilot_monitor() -> None:
    """Render pilot monitoring page with real-time metrics."""
    st.header("Pilot Monitor")

    # Connection status indicator
    col_status, col_refresh = st.columns([3, 1])
    with col_status:
        st.markdown("🟢 **Live** - Connected to database")
    with col_refresh:
        if st.button("Refresh"):
            st.rerun()

    # Get data
    try:
        summary = asyncio.run(_get_pilot_summary())
    except Exception as e:
        st.error(f"Database error: {e}")
        summary = _get_mock_pilot_summary()

    # Key metrics row
    col1, col2, col3 = st.columns(3)

    with col1:
        pnl = summary.get("realized_pnl", 0)
        st.metric(
            label="Cumulative P&L",
            value=f"${pnl:,.2f}",
        )

    with col2:
        st.metric(
            label="Trades Today",
            value=str(summary.get("total_trades", 0)),
        )

    with col3:
        win_rate = summary.get("win_rate", 0) * 100
        st.metric(
            label="Win Rate",
            value=f"{win_rate:.0f}%",
        )

    st.markdown("---")

    # Two columns: recent trades and breakdown
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Recent Trades")
        trades = summary.get("recent_trades", [])
        if trades:
            df = pd.DataFrame(trades[:20])
            if "created_at" in df.columns:
                df["time"] = pd.to_datetime(df["created_at"]).dt.strftime("%H:%M")
            else:
                df["time"] = "N/A"
            display_cols = ["time", "market_id", "side", "price", "expected_edge", "status"]
            available_cols = [c for c in display_cols if c in df.columns]
            if available_cols:
                st.dataframe(df[available_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No trades yet. Start the pilot to see results.")

    with col2:
        st.subheader("By Opportunity Type")
        by_type = summary.get("by_opportunity_type", [])
        if by_type:
            for row in by_type:
                pnl = row.get("pnl", 0)
                pnl_color = "green" if pnl >= 0 else "red"
                st.markdown(
                    f"**{row['type']}**  \n"
                    f"{row['trades']} trades · "
                    f":{pnl_color}[${pnl:+,.2f}]"
                )
        else:
            st.info("No data yet.")


async def _get_pilot_summary() -> dict:
    """Fetch summary from database."""
    from pm_arb.db.repository import PaperTradeRepository

    pool = get_cached_db_pool()
    repo = PaperTradeRepository(pool)

    summary = await repo.get_daily_summary(days=7)
    trades = await repo.get_trades_since_days(days=1)

    return {
        "realized_pnl": summary["realized_pnl"],
        "total_trades": summary["total_trades"],
        "win_rate": summary["win_rate"],
        "by_opportunity_type": summary["by_opportunity_type"],
        "recent_trades": trades,
    }


def _get_mock_pilot_summary() -> dict:
    """Mock data for when database isn't available."""
    return {
        "realized_pnl": 0,
        "total_trades": 0,
        "win_rate": 0,
        "by_opportunity_type": [],
        "recent_trades": [],
    }


def render_how_it_works() -> None:
    """Render educational explainer panel."""
    st.header("How Arbitrage Works")

    st.markdown("""
    ### The Basic Idea

    Prediction markets price outcomes as probabilities. When the market price
    **lags behind reality**, we profit by trading before the market corrects.
    """)

    # Live example section
    st.subheader("Live Example")

    example_col1, example_col2 = st.columns(2)

    with example_col1:
        st.markdown("""
        **Polymarket**
        Market: "BTC above $97,000 at 4pm ET?"
        YES Price: **$0.52** (52% implied odds)
        """)

    with example_col2:
        st.markdown("""
        **Binance (Oracle)**
        BTC Price: **$97,842**
        (Already above threshold!)
        """)

    st.info("""
    **The Opportunity**
    BTC is ALREADY above $97k, but the market only prices YES at 52%.
    True probability: ~85%+

    **Edge = 85% - 52% = 33% mispricing**
    """)

    # The math
    st.subheader("The Math")

    st.markdown("""
    We buy YES at **$0.52**

    | Outcome | Payout | Profit/Loss |
    |---------|--------|-------------|
    | BTC stays above $97k | YES pays $1.00 | **+$0.48** per share (92% return) |
    | BTC drops below $97k | YES pays $0.00 | **-$0.52** per share |

    **Expected value** (at 85% true odds):
    `(0.85 x $0.48) + (0.15 x -$0.52)` = **+$0.33 per share**
    """)

    # Why it works
    st.subheader("Why This Works")

    st.code("""
Timeline:
---------*------------*------------*----------->
      BTC moves    We trade    Market corrects
        (0ms)       (50ms)       (2-5 sec)
    """, language=None)

    st.markdown("""
    - **Binance** updates every millisecond
    - **Polymarket** updates every few seconds
    - In that gap, we see the future price before the prediction market catches up
    """)

    # Three types
    st.subheader("Three Types We Detect")

    type_col1, type_col2, type_col3 = st.columns(3)

    with type_col1:
        st.markdown("""
        **1. Oracle Lag**
        Real-world data moves before the market.

        *Example: BTC pumps on Binance, Polymarket BTC markets lag behind.*
        """)

    with type_col2:
        st.markdown("""
        **2. Mispricing**
        YES + NO don't sum to ~100%.

        *Example: YES = 45%, NO = 48%. Buy both, guaranteed profit.*
        """)

    with type_col3:
        st.markdown("""
        **3. Cross-Platform**
        Same event priced differently.

        *Example: Polymarket YES = 52%, Kalshi YES = 58%.*
        """)

    # Glossary
    with st.expander("Glossary"):
        st.markdown("""
        | Term | Definition |
        |------|------------|
        | **Edge** | The difference between market price and true probability |
        | **VWAP** | Volume-Weighted Average Price - what you'll actually pay accounting for order book depth |
        | **Slippage** | The difference between expected price and actual fill price |
        | **Oracle** | External data source (Binance, weather APIs, etc.) |
        | **Venue** | Prediction market platform (Polymarket, Kalshi) |
        """)


if __name__ == "__main__":
    main()
