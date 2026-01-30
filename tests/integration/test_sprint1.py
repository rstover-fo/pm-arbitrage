"""Integration test for Sprint 1: Foundation."""

import asyncio
from typing import Any

import pytest
import redis.asyncio as redis

from pm_arb.agents.base import BaseAgent


class EchoAgent(BaseAgent):
    """Test agent that echoes messages to output channel."""

    name = "echo-agent"

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url)
        self.received: list[dict[str, Any]] = []

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Echo message to output channel."""
        self.received.append(data)
        await self.publish("test.output", {"echoed": data.get("value", "")})

    def get_subscriptions(self) -> list[str]:
        return ["test.input"]


class CollectorAgent(BaseAgent):
    """Test agent that collects messages."""

    name = "collector-agent"

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url)
        self.collected: list[dict[str, Any]] = []

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Collect message."""
        self.collected.append(data)

    def get_subscriptions(self) -> list[str]:
        return ["test.output"]


@pytest.mark.asyncio
async def test_two_agents_communicate() -> None:
    """Two agents should communicate via message bus."""
    redis_url = "redis://localhost:6379"

    # Clean up any leftover streams from previous test runs
    client = redis.from_url(redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
    await client.delete("test.input", "test.output", "system.commands")
    await client.aclose()

    echo = EchoAgent(redis_url)
    collector = CollectorAgent(redis_url)

    # Start both agents
    echo_task = asyncio.create_task(echo.run())
    collector_task = asyncio.create_task(collector.run())

    # Wait for agents to initialize
    await asyncio.sleep(0.2)

    # Publish test message
    await echo.publish("test.input", {"value": "hello"})

    # Wait for message to flow through (need enough time for message bus iterations)
    await asyncio.sleep(1.5)

    # Verify echo agent received input
    assert len(echo.received) == 1
    assert echo.received[0]["value"] == "hello"

    # Verify collector received echoed output
    assert len(collector.collected) == 1
    assert collector.collected[0]["echoed"] == "hello"

    # Clean shutdown
    await echo.stop()
    await collector.stop()
    await asyncio.wait_for(echo_task, timeout=2.0)
    await asyncio.wait_for(collector_task, timeout=2.0)
