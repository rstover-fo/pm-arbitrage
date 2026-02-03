"""Tests for paper executor persistence."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.db.repository import PaperTradeRepository


@pytest.mark.asyncio
async def test_paper_executor_persists_trade(test_db_pool, redis_url):
    """Test that paper executor writes trades to database."""
    repo = PaperTradeRepository(test_db_pool)
    agent = PaperExecutorAgent(redis_url, db_pool=test_db_pool)
    agent._repo = repo  # Set repo directly for test

    # Mock publish to avoid "Agent not running" error
    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Simulate a trade request
    request_id = f"req-{uuid4().hex[:8]}"
    agent._pending_requests[request_id] = {
        "id": request_id,
        "opportunity_id": f"opp-{uuid4().hex[:8]}",
        "opportunity_type": "oracle_lag",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10.00",
        "max_price": "0.52",
        "expected_edge": "0.05",
        "strategy": "oracle-sniper",
    }

    # Execute paper trade
    await agent._execute_paper_trade(request_id)

    # Verify it was persisted
    trades = await repo.get_trades_since_days(1)
    assert len(trades) >= 1

    trade = trades[0]
    assert trade["opportunity_type"] == "oracle_lag"
    assert trade["market_id"] == "polymarket:btc-100k"
    assert trade["side"] == "buy"
    assert trade["risk_approved"] is True


@pytest.mark.asyncio
async def test_paper_executor_persists_rejection(test_db_pool, redis_url):
    """Test that paper executor writes rejections to database."""
    repo = PaperTradeRepository(test_db_pool)
    agent = PaperExecutorAgent(redis_url, db_pool=test_db_pool)
    agent._repo = repo

    # Mock publish to avoid "Agent not running" error
    published: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        published.append((channel, data))
        return "mock-id"

    agent.publish = capture_publish  # type: ignore[method-assign]

    # Simulate a trade request
    request_id = f"req-{uuid4().hex[:8]}"
    agent._pending_requests[request_id] = {
        "id": request_id,
        "opportunity_id": f"opp-{uuid4().hex[:8]}",
        "opportunity_type": "oracle_lag",
        "market_id": "polymarket:btc-100k",
        "side": "buy",
        "outcome": "YES",
        "amount": "10.00",
        "max_price": "0.52",
        "expected_edge": "0.05",
        "strategy": "oracle-sniper",
    }

    # Handle rejection
    await agent._handle_rejection(request_id, "position_limit_exceeded")

    # Verify rejection was persisted
    trades = await repo.get_trades_since_days(1)
    assert len(trades) >= 1

    trade = trades[0]
    assert trade["risk_approved"] is False
    assert trade["risk_rejection_reason"] == "position_limit_exceeded"


@pytest.mark.asyncio
async def test_paper_executor_state_recovery(test_db_pool, redis_url):
    """Test that paper executor recovers state from database."""
    repo = PaperTradeRepository(test_db_pool)

    # Insert a trade directly
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

    # Create agent and recover state
    agent = PaperExecutorAgent(redis_url, db_pool=test_db_pool)
    agent._repo = repo
    await agent._recover_state()

    # Verify state was recovered
    assert len(agent._trades) == 1
    assert agent._trades[0].market_id == "polymarket:btc-100k"
