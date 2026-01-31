"""Venue Watcher Agent - streams prices from a prediction market venue."""

import asyncio
from typing import Any

import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Market

logger = structlog.get_logger()


class VenueWatcherAgent(BaseAgent):
    """Watches a single venue and publishes price updates."""

    def __init__(
        self,
        redis_url: str,
        adapter: VenueAdapter,
        poll_interval: float = 5.0,
    ) -> None:
        self.name = f"venue-watcher-{adapter.name}"
        super().__init__(redis_url)
        self._adapter = adapter
        self._poll_interval = poll_interval
        self._markets: dict[str, Market] = {}

    def get_subscriptions(self) -> list[str]:
        """No subscriptions - this agent only publishes."""
        return []

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """No incoming messages to handle."""
        pass

    async def run(self) -> None:
        """Override run to add venue connection and polling."""
        await self._adapter.connect()
        try:
            # Start base agent in background for system commands
            base_task = asyncio.create_task(super().run())

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
            await self._adapter.disconnect()

    async def _poll_and_publish(self) -> None:
        """Fetch markets and publish updates."""
        try:
            markets = await self._adapter.get_markets()
            log = logger.bind(agent=self.name, market_count=len(markets))

            for market in markets:
                # Check if price changed
                old = self._markets.get(market.id)
                if old is None or old.yes_price != market.yes_price:
                    await self._publish_price(market)

                self._markets[market.id] = market

            # Also publish market discovery for matcher
            await self._publish_markets(markets)

            log.debug("venue_poll_complete")

        except Exception as e:
            logger.error("venue_poll_error", agent=self.name, error=str(e))

    async def _publish_price(self, market: Market) -> None:
        """Publish price update."""
        await self.publish(
            f"venue.{self._adapter.name}.prices",
            {
                "market_id": market.id,
                "venue": market.venue,
                "title": market.title,
                "yes_price": str(market.yes_price),
                "no_price": str(market.no_price),
                "timestamp": market.last_updated.isoformat(),
            },
        )

    async def _publish_markets(self, markets: list[Market]) -> None:
        """Publish market list for matcher."""
        await self.publish(
            f"venue.{self._adapter.name}.markets",
            {
                "venue": self._adapter.name,
                "market_count": len(markets),
                "markets": [
                    {
                        "id": m.id,
                        "external_id": m.external_id,
                        "title": m.title,
                        "description": m.description,
                    }
                    for m in markets[:50]  # Limit to avoid huge messages
                ],
            },
        )
