"""Tests for Oracle Agent."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from pm_arb.agents.base import BaseAgent
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.core.models import OracleData


def _make_polling_oracle() -> MagicMock:
    """Create a mock oracle that does NOT support streaming (polling mode)."""
    mock = MagicMock()
    mock.name = "test-oracle"
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    type(mock).supports_streaming = PropertyMock(return_value=False)
    mock.get_current = AsyncMock(
        return_value=OracleData(
            source="test",
            symbol="BTC",
            value=Decimal("65000"),
        )
    )
    return mock


def _make_streaming_oracle(data_items: list[OracleData]) -> MagicMock:
    """Create a mock oracle that supports streaming."""
    mock = MagicMock()
    mock.name = "test-stream-oracle"
    mock.connect = AsyncMock()
    mock.disconnect = AsyncMock()
    mock.subscribe = AsyncMock()
    type(mock).supports_streaming = PropertyMock(return_value=True)

    async def fake_stream():
        for item in data_items:
            yield item

    mock.stream = fake_stream
    return mock


@pytest.mark.asyncio
async def test_oracle_agent_publishes_prices() -> None:
    """Oracle agent should publish real-world data to message bus (polling)."""
    mock_oracle = _make_polling_oracle()

    agent = OracleAgent(
        redis_url="redis://localhost:6379",
        oracle=mock_oracle,
        symbols=["BTC"],
        poll_interval=0.1,
    )

    published: list[tuple[str, dict]] = []
    original_publish = agent.publish

    async def capture_publish(channel: str, data: dict) -> str:
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


async def _noop_base_run(self: BaseAgent) -> None:
    """Replacement for BaseAgent.run() that skips Redis but sets _running."""
    self._running = True
    self._stop_event.clear()
    while self._running and not self._stop_event.is_set():
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_oracle_agent_uses_streaming_when_supported() -> None:
    """Agent should use stream() instead of polling when oracle supports it."""
    items = [
        OracleData(
            source="binance",
            symbol="BTC",
            value=Decimal("65000"),
            timestamp=datetime.now(UTC),
        ),
        OracleData(
            source="binance",
            symbol="ETH",
            value=Decimal("3400"),
            timestamp=datetime.now(UTC),
        ),
    ]
    mock_oracle = _make_streaming_oracle(items)

    agent = OracleAgent(
        redis_url="redis://localhost:6379",
        oracle=mock_oracle,
        symbols=["BTC", "ETH"],
        poll_interval=1.0,
    )

    published: list[tuple[str, dict]] = []

    async def capture_publish(channel: str, data: dict) -> str:
        published.append((channel, data))
        if len(published) >= len(items):
            await agent.stop()
        return "fake-msg-id"

    agent.publish = capture_publish

    with patch.object(BaseAgent, "run", _noop_base_run):
        task = asyncio.create_task(agent.run())
        await asyncio.wait_for(task, timeout=3.0)

    assert len(published) == 2
    channels = [p[0] for p in published]
    assert "oracle.binance.BTC" in channels
    assert "oracle.binance.ETH" in channels

    # Verify subscribe was called (streaming path)
    mock_oracle.subscribe.assert_called_once_with(["BTC", "ETH"])


@pytest.mark.asyncio
async def test_oracle_agent_polls_when_streaming_not_supported() -> None:
    """Agent should fall back to polling when oracle doesn't support streaming."""
    mock_oracle = _make_polling_oracle()

    agent = OracleAgent(
        redis_url="redis://localhost:6379",
        oracle=mock_oracle,
        symbols=["BTC"],
        poll_interval=0.1,
    )

    published: list[tuple[str, dict]] = []
    original_publish = agent.publish

    async def capture_publish(channel: str, data: dict) -> str:
        published.append((channel, data))
        return await original_publish(channel, data)

    agent.publish = capture_publish

    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.25)
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Should have polled at least once
    assert mock_oracle.get_current.call_count >= 1
    oracle_messages = [p for p in published if "oracle" in p[0]]
    assert len(oracle_messages) >= 1


@pytest.mark.asyncio
async def test_oracle_agent_reconnects_on_stream_error() -> None:
    """Agent should reconnect when streaming fails, then resume."""
    call_count = 0

    mock_oracle = MagicMock()
    mock_oracle.name = "test-reconnect-oracle"
    mock_oracle.connect = AsyncMock()
    mock_oracle.disconnect = AsyncMock()
    mock_oracle.subscribe = AsyncMock()
    type(mock_oracle).supports_streaming = PropertyMock(return_value=True)

    async def flaky_stream():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("WebSocket disconnected")
        # Second call succeeds with one item
        yield OracleData(
            source="binance",
            symbol="BTC",
            value=Decimal("65000"),
            timestamp=datetime.now(UTC),
        )

    mock_oracle.stream = flaky_stream

    agent = OracleAgent(
        redis_url="redis://localhost:6379",
        oracle=mock_oracle,
        symbols=["BTC"],
        poll_interval=0.1,
    )

    published: list[tuple[str, dict]] = []

    async def capture_publish(channel: str, data: dict) -> str:
        published.append((channel, data))
        await agent.stop()
        return "fake-msg-id"

    agent.publish = capture_publish

    with patch.object(BaseAgent, "run", _noop_base_run):
        task = asyncio.create_task(agent.run())
        await asyncio.wait_for(task, timeout=5.0)

    # Should have reconnected: subscribe called twice (fail + success)
    assert mock_oracle.subscribe.call_count == 2
    assert len(published) == 1
    assert published[0][0] == "oracle.binance.BTC"
