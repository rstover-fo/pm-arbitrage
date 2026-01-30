"""Redis Streams message bus for agent communication."""

import json
from typing import Any

import redis.asyncio as redis


class MessageBus:
    """Wrapper around Redis Streams for pub/sub messaging."""

    def __init__(self, client: redis.Redis) -> None:
        """Initialize with Redis client."""
        self._client = client

    def _deserialize_value(self, value: str) -> Any:
        """Attempt to deserialize a JSON string back to Python object."""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def _deserialize_message(self, data: dict[str, str]) -> dict[str, Any]:
        """Deserialize all values in a message."""
        return {k: self._deserialize_value(v) for k, v in data.items()}

    async def publish(self, channel: str, data: dict[str, Any]) -> str:
        """Publish message to a stream. Returns message ID."""
        # Serialize nested objects as JSON strings
        flat_data: dict[str, str] = {
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in data.items()
        }
        message_id: str = await self._client.xadd(channel, flat_data)  # type: ignore[arg-type]
        return message_id

    async def consume(
        self,
        channel: str,
        count: int = 10,
        last_id: str = "0",
    ) -> list[dict[str, Any]]:
        """Read messages from stream (simple read, not consumer group)."""
        results = await self._client.xread({channel: last_id}, count=count, block=1000)

        messages: list[dict[str, Any]] = []
        for _, entries in results:
            for _, data in entries:
                messages.append(self._deserialize_message(data))
        return messages

    async def create_consumer_group(
        self,
        channel: str,
        group: str,
        start_id: str = "0",
    ) -> None:
        """Create consumer group for competing consumers."""
        try:
            await self._client.xgroup_create(channel, group, id=start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume_group(
        self,
        channel: str,
        group: str,
        consumer: str,
        count: int = 10,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read messages as part of consumer group. Returns (id, data) tuples."""
        results = await self._client.xreadgroup(
            group,
            consumer,
            {channel: ">"},
            count=count,
            block=1000,
        )

        messages: list[tuple[str, dict[str, Any]]] = []
        for _, entries in results:
            for msg_id, data in entries:
                messages.append((msg_id, self._deserialize_message(data)))
        return messages

    async def ack(self, channel: str, group: str, message_id: str) -> None:
        """Acknowledge message processing in consumer group."""
        await self._client.xack(channel, group, message_id)

    async def publish_command(self, command: str, **kwargs: Any) -> str:
        """Publish system command (halt, pause, resume)."""
        data = {"command": command, **kwargs}
        return await self.publish("system.commands", data)
