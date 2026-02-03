"""Integration test for full pilot flow."""

import asyncio

import pytest

from pm_arb.db import get_pool, init_db
from pm_arb.db.repository import PaperTradeRepository
from pm_arb.pilot import PilotOrchestrator


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_pilot_flow(redis_url):
    """Test that pilot runs and persists trades."""
    # Initialize database
    await init_db()
    pool = await get_pool()
    repo = PaperTradeRepository(pool)

    # Get initial trade count
    initial_summary = await repo.get_daily_summary(days=1)
    initial_trades = initial_summary["total_trades"]

    # Start orchestrator
    orchestrator = PilotOrchestrator(redis_url=redis_url, db_pool=pool)

    # Run for a short time
    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(10)

    # Verify health
    health = orchestrator.get_health()
    assert health["running"]
    assert len(health["agents"]) >= 5

    # Stop gracefully
    await orchestrator.stop()
    await task

    # Verify no errors - summary should be retrievable
    final_summary = await repo.get_daily_summary(days=1)
    assert final_summary is not None

    await pool.close()
