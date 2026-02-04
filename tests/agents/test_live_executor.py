"""Tests for Live Executor agent."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_executor_processes_approved_trade(mock_credentials: PolymarketCredentials) -> None:
    """Should execute approved trade via venue adapter."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    # Track published results
    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Mock the adapter's place_order
    mock_order_response = MagicMock()
    mock_order_response.external_id = "ext-123"
    mock_order_response.status = OrderStatus.FILLED
    mock_order_response.filled_amount = Decimal("10")
    mock_order_response.average_price = Decimal("0.50")
    mock_order_response.error_message = None

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.get_balance.return_value = Decimal("1000")  # Sufficient balance
        mock_adapter.place_order.return_value = mock_order_response
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-001",
                "market_id": "polymarket:test-market",
                "token_id": "token-abc",
                "side": "buy",
                "amount": "10",
                "max_price": "0.55",
            }
        )

    # Should publish trade result
    assert len(results) == 1
    assert results[0][0] == "trade.results"
    assert results[0][1]["request_id"] == "req-001"
    assert results[0][1]["status"] == "filled"


@pytest.mark.asyncio
async def test_executor_reports_failure(mock_credentials: PolymarketCredentials) -> None:
    """Should report when trade execution fails."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    mock_order_response = MagicMock()
    mock_order_response.status = OrderStatus.REJECTED
    mock_order_response.error_message = "Insufficient balance"
    mock_order_response.external_id = ""
    mock_order_response.filled_amount = Decimal("0")
    mock_order_response.average_price = None

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.get_balance.return_value = Decimal("1000")  # Sufficient balance
        mock_adapter.place_order.return_value = mock_order_response
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-002",
                "market_id": "polymarket:test",
                "token_id": "token-xyz",
                "side": "buy",
                "amount": "100",
                "max_price": "0.50",
            }
        )

    assert len(results) == 1
    assert results[0][1]["status"] == "rejected"
    assert "Insufficient balance" in results[0][1]["error"]


@pytest.mark.asyncio
async def test_executor_subscribes_to_approved_trades(
    mock_credentials: PolymarketCredentials,
) -> None:
    """Executor should subscribe to trade decisions and requests channels."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    subs = executor.get_subscriptions()

    # LiveExecutor now subscribes to same channels as PaperExecutor
    assert "trade.decisions" in subs
    assert "trade.requests" in subs


@pytest.mark.asyncio
async def test_executor_connects_adapter_when_needed(
    mock_credentials: PolymarketCredentials,
) -> None:
    """Executor should connect adapter if not already connected."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    mock_order_response = MagicMock()
    mock_order_response.external_id = "ext-456"
    mock_order_response.status = OrderStatus.FILLED
    mock_order_response.filled_amount = Decimal("10")
    mock_order_response.average_price = Decimal("0.50")
    mock_order_response.error_message = None

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = False  # Not yet connected
        mock_adapter.get_balance.return_value = Decimal("1000")  # Sufficient balance
        mock_adapter.place_order.return_value = mock_order_response
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-003",
                "market_id": "polymarket:test",
                "token_id": "token-abc",
                "side": "buy",
                "amount": "10",
                "max_price": "0.55",
            }
        )

        # Should have called connect()
        mock_adapter.connect.assert_called_once()


@pytest.mark.asyncio
async def test_executor_handles_exception(mock_credentials: PolymarketCredentials) -> None:
    """Executor should handle adapter exceptions gracefully."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.get_balance.return_value = Decimal("1000")  # Sufficient balance
        mock_adapter.place_order.side_effect = Exception("Network timeout")
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-004",
                "market_id": "polymarket:test",
                "token_id": "token-abc",
                "side": "buy",
                "amount": "10",
                "max_price": "0.55",
            }
        )

    assert len(results) == 1
    assert results[0][1]["status"] == "rejected"
    assert "Network timeout" in results[0][1]["error"]


@pytest.mark.asyncio
async def test_executor_rejects_insufficient_balance(
    mock_credentials: PolymarketCredentials,
) -> None:
    """Executor should reject trade when balance is insufficient."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.get_balance.return_value = Decimal("1")  # Only $1 available
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-005",
                "market_id": "polymarket:test",
                "token_id": "token-abc",
                "side": "buy",
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
async def test_executor_resolves_token_id(mock_credentials: PolymarketCredentials) -> None:
    """Executor should resolve token_id when not provided in request."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    mock_order_response = MagicMock()
    mock_order_response.external_id = "ext-789"
    mock_order_response.status = OrderStatus.FILLED
    mock_order_response.filled_amount = Decimal("10")
    mock_order_response.average_price = Decimal("0.50")
    mock_order_response.error_message = None

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.get_balance.return_value = Decimal("1000")
        mock_adapter.get_token_id.return_value = "resolved-token-123"
        mock_adapter.place_order.return_value = mock_order_response
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade(
            {
                "request_id": "req-006",
                "market_id": "polymarket:test-market",
                # No token_id provided - should be resolved
                "outcome": "YES",
                "side": "buy",
                "amount": "10",
                "max_price": "0.55",
            }
        )

        # get_token_id should have been called
        mock_adapter.get_token_id.assert_called_once_with("polymarket:test-market", "YES")

        # place_order should use resolved token_id
        mock_adapter.place_order.assert_called_once()
        call_args = mock_adapter.place_order.call_args
        assert call_args.kwargs["token_id"] == "resolved-token-123"

    assert len(results) == 1
    assert results[0][1]["status"] == "filled"
