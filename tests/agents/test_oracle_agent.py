"""Tests for Oracle Agent."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.core.models import OracleData


@pytest.mark.asyncio
async def test_oracle_agent_publishes_prices() -> None:
    """Oracle agent should publish real-world data to message bus."""
    mock_oracle = MagicMock()
    mock_oracle.name = "test-oracle"
    mock_oracle.connect = AsyncMock()
    mock_oracle.disconnect = AsyncMock()
    mock_oracle.get_current = AsyncMock(
        return_value=OracleData(
            source="test",
            symbol="BTC",
            value=Decimal("65000"),
        )
    )

    agent = OracleAgent(
        redis_url="redis://localhost:6379",
        oracle=mock_oracle,
        symbols=["BTC"],
        poll_interval=0.1,
    )

    published = []
    original_publish = agent.publish

    async def capture_publish(channel, data):
        published.append((channel, data))
        return await original_publish(channel, data)

    agent.publish = capture_publish

    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.3)
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)

    oracle_messages = [p for p in published if "oracle" in p[0]]
    assert len(oracle_messages) > 0
    assert "BTC" in oracle_messages[0][0]
