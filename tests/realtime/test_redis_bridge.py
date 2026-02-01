"""Tests for Redis to WebSocket bridge."""

import asyncio

import pytest

from pm_arb.realtime.redis_bridge import RedisBridge


@pytest.mark.asyncio
async def test_bridge_receives_messages() -> None:
    """Should receive messages from Redis and call handler."""
    received = []

    async def handler(channel: str, data: dict) -> None:
        received.append((channel, data))

    bridge = RedisBridge(redis_url="redis://localhost:6379")
    bridge.on_message = handler

    # Start bridge in background
    task = asyncio.create_task(bridge.run())

    # Give it time to connect
    await asyncio.sleep(0.2)

    # Publish a test message directly to Redis
    import redis.asyncio as redis

    client = redis.from_url("redis://localhost:6379", decode_responses=True)
    await client.publish("agent.updates", '{"test": "data"}')
    await client.aclose()

    # Wait for message to be received
    await asyncio.sleep(0.2)

    # Stop bridge
    await bridge.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0][0] == "agent.updates"
