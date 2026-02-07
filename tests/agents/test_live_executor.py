"""Tests for Live Executor agent with generic VenueAdapter interface."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.core.models import Side, Trade, TradeStatus


def _make_mock_adapter(**overrides) -> MagicMock:
    """Create a mock VenueAdapter."""
    adapter = AsyncMock()
    adapter.name = "polymarket"
    adapter.is_connected = True
    adapter.get_balance.return_value = Decimal("1000")
    for k, v in overrides.items():
        setattr(adapter, k, v)
    return adapter


def _make_trade(request_id: str = "req-001", **overrides) -> Trade:
    """Create a Trade result with sensible defaults."""
    defaults = {
        "id": "trade-001",
        "request_id": request_id,
        "market_id": "polymarket:test-market",
        "venue": "polymarket",
        "side": Side.BUY,
        "outcome": "YES",
        "amount": Decimal("10"),
        "price": Decimal("0.50"),
        "status": TradeStatus.FILLED,
        "external_id": "ext-123",
    }
    defaults.update(overrides)
    return Trade(**defaults)


def _make_executor(adapters: dict[str, Any] | None = None) -> LiveExecutorAgent:
    """Create a LiveExecutorAgent with mock adapters."""
    if adapters is None:
        adapters = {"polymarket": _make_mock_adapter()}
    return LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        adapters=adapters,
    )


def _capture_publish(executor: LiveExecutorAgent) -> list[tuple[str, dict[str, Any]]]:
    """Attach a publish capture to executor, return results list."""
    results: list[tuple[str, dict[str, Any]]] = []

    async def capture(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture  # type: ignore[method-assign]
    return results


@pytest.mark.asyncio
async def test_executor_processes_approved_trade() -> None:
    """Should execute approved trade via generic VenueAdapter.place_order()."""
    mock_adapter = _make_mock_adapter()
    mock_adapter.place_order.return_value = _make_trade()
    executor = _make_executor({"polymarket": mock_adapter})
    results = _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-001",
            "market_id": "polymarket:test-market",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.55",
            "opportunity_id": "opp-001",
            "strategy": "oracle-sniper",
        }
    )

    # Should publish trade result
    assert len(results) == 1
    assert results[0][0] == "trade.results"
    assert results[0][1]["request_id"] == "req-001"
    assert results[0][1]["status"] == "filled"

    # place_order should have been called with a TradeRequest
    mock_adapter.place_order.assert_called_once()
    trade_request = mock_adapter.place_order.call_args[0][0]
    assert trade_request.market_id == "polymarket:test-market"
    assert trade_request.side == Side.BUY
    assert trade_request.outcome == "YES"


@pytest.mark.asyncio
async def test_executor_handles_failed_trade() -> None:
    """Should report when trade execution returns FAILED status."""
    mock_adapter = _make_mock_adapter()
    mock_adapter.place_order.return_value = _make_trade(status=TradeStatus.FAILED)
    executor = _make_executor({"polymarket": mock_adapter})
    results = _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-002",
            "market_id": "polymarket:test",
            "side": "buy",
            "outcome": "YES",
            "amount": "100",
            "max_price": "0.50",
        }
    )

    assert len(results) == 1
    assert results[0][1]["status"] == "failed"


@pytest.mark.asyncio
async def test_executor_subscribes_to_trade_channels() -> None:
    """Executor should subscribe to trade decisions and requests channels."""
    executor = _make_executor()
    subs = executor.get_subscriptions()

    assert "trade.decisions" in subs
    assert "trade.requests" in subs


@pytest.mark.asyncio
async def test_executor_connects_adapter_when_needed() -> None:
    """Executor should connect adapter if not already connected."""
    mock_adapter = _make_mock_adapter(is_connected=False)
    mock_adapter.place_order.return_value = _make_trade()
    executor = _make_executor({"polymarket": mock_adapter})
    _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-003",
            "market_id": "polymarket:test",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.55",
        }
    )

    mock_adapter.connect.assert_called_once()


@pytest.mark.asyncio
async def test_executor_handles_exception() -> None:
    """Executor should handle adapter exceptions gracefully."""
    mock_adapter = _make_mock_adapter()
    mock_adapter.place_order.side_effect = Exception("Network timeout")
    executor = _make_executor({"polymarket": mock_adapter})
    results = _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-004",
            "market_id": "polymarket:test",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.55",
        }
    )

    assert len(results) == 1
    assert results[0][1]["status"] == "rejected"
    assert "Network timeout" in results[0][1]["error"]


@pytest.mark.asyncio
async def test_executor_rejects_insufficient_balance() -> None:
    """Executor should reject trade when balance is insufficient."""
    mock_adapter = _make_mock_adapter()
    mock_adapter.get_balance.return_value = Decimal("1")  # Only $1 available
    executor = _make_executor({"polymarket": mock_adapter})
    results = _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-005",
            "market_id": "polymarket:test",
            "side": "buy",
            "outcome": "YES",
            "amount": "100",  # 100 tokens
            "max_price": "0.50",  # at $0.50 = $50 required
        }
    )

    # place_order should NOT have been called
    mock_adapter.place_order.assert_not_called()

    assert len(results) == 1
    assert results[0][1]["status"] == "rejected"
    assert "Insufficient balance" in results[0][1]["error"]


@pytest.mark.asyncio
async def test_executor_skips_balance_check_when_not_supported() -> None:
    """Executor should proceed if adapter doesn't support balance queries."""
    mock_adapter = _make_mock_adapter()
    mock_adapter.get_balance.side_effect = NotImplementedError("No balance support")
    mock_adapter.place_order.return_value = _make_trade()
    executor = _make_executor({"polymarket": mock_adapter})
    results = _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-006",
            "market_id": "polymarket:test",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.55",
        }
    )

    # Should still place order despite balance check failure
    mock_adapter.place_order.assert_called_once()
    assert len(results) == 1
    assert results[0][1]["status"] == "filled"


@pytest.mark.asyncio
async def test_executor_unknown_venue_raises() -> None:
    """Executor should raise when venue has no configured adapter."""
    executor = _make_executor({"polymarket": _make_mock_adapter()})
    results = _capture_publish(executor)

    await executor._execute_trade(
        {
            "request_id": "req-007",
            "market_id": "unknown_venue:test",
            "side": "buy",
            "outcome": "YES",
            "amount": "10",
            "max_price": "0.55",
        }
    )

    # Should publish failure
    assert len(results) == 1
    assert results[0][1]["status"] == "rejected"
    assert "No adapter configured" in results[0][1]["error"]
