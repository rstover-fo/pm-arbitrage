"""Oracle Agent - streams real-world data from external sources."""

import asyncio
from typing import Any

import structlog

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import OracleData

logger = structlog.get_logger()


class OracleAgent(BaseAgent):
    """Publishes real-world data from oracle sources."""

    def __init__(
        self,
        redis_url: str,
        oracle: OracleAdapter,
        symbols: list[str],
        poll_interval: float = 1.0,
    ) -> None:
        self.name = f"oracle-{oracle.name}"
        super().__init__(redis_url)
        self._oracle = oracle
        self._symbols = symbols
        self._poll_interval = poll_interval
        self._last_values: dict[str, OracleData] = {}

    def get_subscriptions(self) -> list[str]:
        """No subscriptions - this agent only publishes."""
        return []

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """No incoming messages to handle."""
        pass

    async def run(self) -> None:
        """Override run to add oracle connection and streaming/polling."""
        await self._oracle.connect()
        self._running = True
        self._stop_event.clear()
        try:
            # Start base agent in background for system commands
            base_task = asyncio.create_task(super().run())

            if self._oracle.supports_streaming:
                await self._stream_with_reconnect()
            else:
                # Poll loop
                while self._running or not self._stop_event.is_set():
                    if self._stop_event.is_set():
                        break
                    await self._poll_and_publish()
                    await asyncio.sleep(self._poll_interval)

            # Cancel base task when we're done
            base_task.cancel()
            try:
                await base_task
            except asyncio.CancelledError:
                pass
        finally:
            await self._oracle.disconnect()

    async def _stream_with_reconnect(self) -> None:
        """Stream oracle data with automatic reconnection on failure."""
        backoff = 1.0
        max_backoff = 30.0

        while self._running and not self._stop_event.is_set():
            try:
                await self._oracle.subscribe(self._symbols)
                backoff = 1.0  # Reset on successful connection

                async for data in self._oracle.stream():
                    if self._stop_event.is_set():
                        break
                    await self._publish_value(data)
                    self._last_values[data.symbol] = data

            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "oracle_stream_disconnected",
                    agent=self.name,
                    error=str(e),
                    reconnect_in=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _poll_and_publish(self) -> None:
        """Fetch current values and publish updates."""
        for symbol in self._symbols:
            try:
                data = await self._oracle.get_current(symbol)
                if data:
                    await self._publish_value(data)
                    self._last_values[symbol] = data
            except Exception as e:
                logger.error(
                    "oracle_poll_error",
                    agent=self.name,
                    symbol=symbol,
                    error=str(e),
                )

    async def _publish_value(self, data: OracleData) -> None:
        """Publish oracle data update."""
        await self.publish(
            f"oracle.{data.source}.{data.symbol}",
            {
                "source": data.source,
                "symbol": data.symbol,
                "value": str(data.value),
                "timestamp": data.timestamp.isoformat(),
                "metadata": data.metadata,
            },
        )
        logger.debug(
            "oracle_published",
            source=data.source,
            symbol=data.symbol,
            value=str(data.value),
        )
