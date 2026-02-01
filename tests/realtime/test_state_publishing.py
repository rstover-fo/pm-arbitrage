"""Tests for agent state publishing to Redis pub/sub."""

import asyncio
from decimal import Decimal

import pytest
import redis.asyncio as redis

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent


@pytest.mark.asyncio
async def test_allocator_publishes_state_on_change() -> None:
    """Allocator should publish state to Redis pub/sub when it changes."""
    redis_url = "redis://localhost:6379"

    # Set up listener
    client = redis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe("agent.updates")

    # Create allocator
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")

    # Trigger state publish
    await allocator.publish_state_update()

    # Check for message (with timeout)
    message = None
    for _ in range(10):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg and msg["type"] == "message":
            message = msg
            break
        await asyncio.sleep(0.1)

    await pubsub.unsubscribe()
    await pubsub.aclose()
    await client.aclose()

    assert message is not None
    assert message["channel"] == "agent.updates"
