"""Tests for base agent class."""

import asyncio
from typing import Any

import pytest

from pm_arb.agents.base import BaseAgent


class ConcreteTestAgent(BaseAgent):
    """Concrete test implementation."""

    name = "test-agent"

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url)
        self.messages_processed: list[dict[str, Any]] = []

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Record received messages."""
        self.messages_processed.append({"channel": channel, "data": data})

    def get_subscriptions(self) -> list[str]:
        """Subscribe to test channel."""
        return ["test.input"]


@pytest.mark.asyncio
async def test_agent_starts_and_stops() -> None:
    """Agent should start, run, and stop cleanly."""
    agent = ConcreteTestAgent("redis://localhost:6379")

    # Start agent in background
    task = asyncio.create_task(agent.run())

    # Give it time to start
    await asyncio.sleep(0.1)
    assert agent.is_running

    # Stop it
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert not agent.is_running


@pytest.mark.asyncio
async def test_agent_responds_to_halt_command() -> None:
    """Agent should stop when HALT_ALL command received."""
    agent = ConcreteTestAgent("redis://localhost:6379")

    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.1)

    # Send halt command
    assert agent._bus is not None  # For type checker
    await agent._bus.publish_command("HALT_ALL")

    # Agent should stop
    await asyncio.wait_for(task, timeout=2.0)
    assert not agent.is_running
