"""Integration test for Sprint 8: WebSocket Real-Time Updates."""

import asyncio
from decimal import Decimal

import pytest

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.registry import AgentRegistry
from pm_arb.realtime.redis_bridge import RedisBridge


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Reset registry before and after each test."""
    AgentRegistry.reset_instance()
    yield
    AgentRegistry.reset_instance()


@pytest.mark.asyncio
async def test_realtime_updates_flow() -> None:
    """Agent state changes should flow through Redis pub/sub."""
    redis_url = "redis://localhost:6379"

    # Collect messages from the bridge
    received_messages: list[tuple[str, dict]] = []

    async def collect_message(channel: str, data: dict) -> None:
        received_messages.append((channel, data))

    # Start Redis bridge
    bridge = RedisBridge(redis_url)
    bridge.on_message = collect_message
    bridge_task = asyncio.create_task(bridge.run())

    # Wait for bridge to connect
    await asyncio.sleep(0.3)

    # Create agents
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("100")

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
    )
    guardian._current_value = Decimal("1100")

    executor = PaperExecutorAgent(redis_url=redis_url)

    # Publish state updates
    await allocator.publish_state_update()
    await guardian.publish_state_update()
    await executor.publish_state_update()

    # Wait for messages to be received
    await asyncio.sleep(0.5)

    # Stop bridge
    await bridge.stop()
    bridge_task.cancel()
    try:
        await bridge_task
    except asyncio.CancelledError:
        pass

    # Verify messages were received
    channels = [msg[0] for msg in received_messages]

    print(f"\nReceived {len(received_messages)} messages:")
    for channel, data in received_messages:
        print(f"  {channel}: {data.get('agent', 'unknown')}")

    assert "agent.updates" in channels, "Should receive allocator update"
    assert "risk.state" in channels, "Should receive guardian update"
    assert "trade.results" in channels, "Should receive executor update"
