"""Tests for paper trade repository."""

from decimal import Decimal
from uuid import uuid4

import pytest

from pm_arb.db.repository import PaperTradeRepository


@pytest.fixture
def repo(test_db_pool):
    """Create repository with test pool."""
    return PaperTradeRepository(test_db_pool)


@pytest.mark.asyncio
async def test_insert_and_get_trade(repo):
    """Test inserting and retrieving a paper trade."""
    trade_id = await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
        strategy_id="oracle-sniper",
    )

    assert trade_id is not None

    trade = await repo.get_trade(trade_id)
    assert trade is not None
    assert trade["opportunity_type"] == "oracle_lag"
    assert trade["market_id"] == "polymarket:btc-100k"
    assert trade["status"] == "open"


@pytest.mark.asyncio
async def test_duplicate_trade_returns_none(repo):
    """Test that duplicate trades are handled gracefully."""
    opp_id = f"opp-{uuid4().hex[:8]}"

    # First insert succeeds
    trade_id_1 = await repo.insert_trade(
        opportunity_id=opp_id,
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )
    assert trade_id_1 is not None

    # Duplicate returns None (same opportunity_id + market_id + side)
    trade_id_2 = await repo.insert_trade(
        opportunity_id=opp_id,
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )
    assert trade_id_2 is None


@pytest.mark.asyncio
async def test_get_trades_by_date_range(repo):
    """Test retrieving trades within a date range."""
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="mispricing",
        market_id="polymarket:eth-5k",
        venue="polymarket",
        side="sell",
        outcome="NO",
        quantity=Decimal("5.00"),
        price=Decimal("0.48"),
        fees=Decimal("0.005"),
        expected_edge=Decimal("0.03"),
        strategy_id="mispricing-hunter",
    )

    trades = await repo.get_trades_since_days(days=1)
    assert len(trades) >= 1
    assert trades[0]["opportunity_type"] == "mispricing"


@pytest.mark.asyncio
async def test_get_open_trades(repo):
    """Test retrieving open trades for state recovery."""
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
    )

    open_trades = await repo.get_open_trades()
    assert len(open_trades) >= 1
    assert open_trades[0]["status"] == "open"


@pytest.mark.asyncio
async def test_get_daily_summary(repo):
    """Test daily summary aggregation."""
    await repo.insert_trade(
        opportunity_id=f"opp-{uuid4().hex[:8]}",
        opportunity_type="oracle_lag",
        market_id="polymarket:btc-100k",
        venue="polymarket",
        side="buy",
        outcome="YES",
        quantity=Decimal("10.00"),
        price=Decimal("0.52"),
        fees=Decimal("0.01"),
        expected_edge=Decimal("0.05"),
        strategy_id="oracle-sniper",
    )

    summary = await repo.get_daily_summary(days=1)
    assert summary["total_trades"] >= 1
    assert "by_opportunity_type" in summary
    assert "win_rate" in summary
