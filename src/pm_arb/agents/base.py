"""Base agent class for all system agents."""

import asyncio
from abc import ABC, abstractmethod
from typing import Any

import redis.asyncio as redis
import structlog

from pm_arb.core.message_bus import MessageBus

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    name: str = "base-agent"

    def __init__(self, redis_url: str) -> None:
        """Initialize agent with Redis connection."""
        self._redis_url = redis_url
        self._client: redis.Redis | None = None
        self._bus: MessageBus | None = None
        self._running = False
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self._running

    @abstractmethod
    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Process a message from subscribed channel. Implement in subclass."""
        ...

    @abstractmethod
    def get_subscriptions(self) -> list[str]:
        """Return list of channels this agent subscribes to. Implement in subclass."""
        ...

    async def run(self) -> None:
        """Main agent loop. Start processing messages."""
        self._client = redis.from_url(self._redis_url, decode_responses=True)  # type: ignore[no-untyped-call]
        self._bus = MessageBus(self._client)
        self._running = True
        self._stop_event.clear()

        log = logger.bind(agent=self.name)
        log.info("agent_started")

        try:
            # Create consumer group for this agent's subscriptions
            subscriptions = self.get_subscriptions()
            for channel in subscriptions:
                await self._bus.create_consumer_group(channel, f"{self.name}-group")

            # Also listen for system commands
            await self._bus.create_consumer_group("system.commands", f"{self.name}-group")

            while self._running:
                # Check for stop signal
                if self._stop_event.is_set():
                    break

                # Check system commands first
                await self._check_system_commands()

                # Process subscribed channels
                for channel in subscriptions:
                    await self._process_channel(channel)

                # Small delay to prevent tight loop
                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            log.info("agent_cancelled")
        finally:
            self._running = False
            if self._client:
                await self._client.aclose()
            log.info("agent_stopped")

    async def stop(self) -> None:
        """Signal agent to stop."""
        self._stop_event.set()
        self._running = False

    async def _check_system_commands(self) -> None:
        """Check for system-wide commands (halt, pause, etc.)."""
        if self._bus is None:
            return

        messages = await self._bus.consume_group(
            "system.commands",
            f"{self.name}-group",
            self.name,
            count=10,
        )

        for msg_id, data in messages:
            command = data.get("command", "")
            if command == "HALT_ALL":
                logger.info("halt_command_received", agent=self.name)
                await self.stop()
            await self._bus.ack("system.commands", f"{self.name}-group", msg_id)

    async def _process_channel(self, channel: str) -> None:
        """Process messages from a single channel."""
        if self._bus is None:
            return

        messages = await self._bus.consume_group(
            channel,
            f"{self.name}-group",
            self.name,
            count=10,
        )

        for msg_id, data in messages:
            try:
                await self.handle_message(channel, data)
            except Exception as e:
                logger.error("message_processing_error", agent=self.name, error=str(e))
            finally:
                await self._bus.ack(channel, f"{self.name}-group", msg_id)

    async def publish(self, channel: str, data: dict[str, Any]) -> str:
        """Publish message to a channel."""
        if self._bus is None:
            raise RuntimeError("Agent not running - cannot publish")
        return await self._bus.publish(channel, data)
