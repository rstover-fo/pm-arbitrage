"""Tests for Redis Streams message bus."""

import pytest
import redis.asyncio as redis

from pm_arb.core.message_bus import MessageBus


@pytest.mark.asyncio
async def test_publish_and_consume(redis_client: redis.Redis) -> None:
    """Should publish message and consume it from stream."""
    bus = MessageBus(redis_client)
    channel = "test.channel"

    # Publish a message
    message_id = await bus.publish(channel, {"type": "test", "value": 42})
    assert message_id is not None

    # Consume the message
    messages = await bus.consume(channel, count=1)
    assert len(messages) == 1
    assert messages[0]["type"] == "test"
    assert messages[0]["value"] == 42  # Deserialized back to int


@pytest.mark.asyncio
async def test_publish_and_consume_nested_objects(redis_client: redis.Redis) -> None:
    """Should serialize and deserialize nested dicts and lists."""
    bus = MessageBus(redis_client)
    channel = "test.nested.channel"

    # Publish message with nested structures
    nested_data = {
        "market_id": "polymarket:btc-up",
        "prices": {"yes": 0.45, "no": 0.55},
        "tags": ["crypto", "btc", "short-term"],
        "metadata": {"source": "api", "version": 2},
    }
    await bus.publish(channel, nested_data)

    # Consume and verify nested objects are deserialized
    messages = await bus.consume(channel, count=1)
    assert len(messages) == 1
    msg = messages[0]

    assert msg["market_id"] == "polymarket:btc-up"
    assert msg["prices"] == {"yes": 0.45, "no": 0.55}
    assert msg["tags"] == ["crypto", "btc", "short-term"]
    assert msg["metadata"]["version"] == 2


@pytest.mark.asyncio
async def test_consumer_group(redis_client: redis.Redis) -> None:
    """Should support consumer groups for competing consumers."""
    bus = MessageBus(redis_client)
    channel = "test.group.channel"
    group = "test-group"

    # Create consumer group
    await bus.create_consumer_group(channel, group)

    # Publish messages
    await bus.publish(channel, {"msg": "one"})
    await bus.publish(channel, {"msg": "two"})

    # Consume as group member
    messages = await bus.consume_group(channel, group, "consumer-1", count=2)
    assert len(messages) == 2

    # Acknowledge them
    for msg_id, _ in messages:
        await bus.ack(channel, group, msg_id)


@pytest.mark.asyncio
async def test_publish_command(redis_client: redis.Redis) -> None:
    """Should publish system commands that all agents receive."""
    bus = MessageBus(redis_client)

    # Publish halt command
    await bus.publish_command("HALT_ALL")

    # Check command was published
    messages = await bus.consume("system.commands", count=1)
    assert messages[0]["command"] == "HALT_ALL"
