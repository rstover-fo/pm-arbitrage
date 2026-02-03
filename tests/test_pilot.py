"""Tests for pilot orchestrator."""

import asyncio

import pytest

from pm_arb.pilot import PilotOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_starts_agents(redis_url, test_db_pool):
    """Test that orchestrator starts all agents."""
    orchestrator = PilotOrchestrator(
        redis_url=redis_url,
        db_pool=test_db_pool,
    )

    # Start in background
    task = asyncio.create_task(orchestrator.run())

    # Give agents time to start
    await asyncio.sleep(0.5)

    # Verify agents are running
    assert orchestrator.is_running
    assert len(orchestrator.agents) >= 5

    # Stop gracefully
    await orchestrator.stop()
    await task


@pytest.mark.asyncio
async def test_orchestrator_health_check(redis_url, test_db_pool):
    """Test that orchestrator reports health status."""
    orchestrator = PilotOrchestrator(
        redis_url=redis_url,
        db_pool=test_db_pool,
    )

    task = asyncio.create_task(orchestrator.run())
    await asyncio.sleep(0.5)

    health = orchestrator.get_health()
    assert "agents" in health
    assert "uptime_seconds" in health

    await orchestrator.stop()
    await task
