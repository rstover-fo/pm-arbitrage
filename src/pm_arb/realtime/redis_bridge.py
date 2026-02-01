"""Bridge between Redis pub/sub and WebSocket connections."""

import asyncio
import json
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()

# Channels to subscribe to for dashboard updates
DASHBOARD_CHANNELS = [
    "agent.updates",
    "trade.results",
    "risk.state",
    "portfolio.summary",
    "strategy.performance",
]


class RedisBridge:
    """Bridges Redis pub/sub messages to WebSocket clients."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._running = False
        self.on_message: Callable[[str, dict], Awaitable[None]] | None = None

    async def run(self) -> None:
        """Start listening for Redis messages."""
        self._client = redis.from_url(self._redis_url, decode_responses=True)
        self._pubsub = self._client.pubsub()
        self._running = True

        # Subscribe to all dashboard-relevant channels
        await self._pubsub.subscribe(*DASHBOARD_CHANNELS)
        logger.info("redis_bridge_subscribed", channels=DASHBOARD_CHANNELS)

        try:
            while self._running:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )

                if message and message["type"] == "message":
                    channel = message["channel"]
                    try:
                        data = json.loads(message["data"])
                    except json.JSONDecodeError:
                        data = {"raw": message["data"]}

                    if self.on_message:
                        await self.on_message(channel, data)

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info("redis_bridge_cancelled")
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """Stop the bridge."""
        self._running = False

    async def _cleanup(self) -> None:
        """Clean up connections."""
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
        if self._client:
            await self._client.aclose()
        logger.info("redis_bridge_stopped")
