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
