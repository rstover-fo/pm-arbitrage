"""Pilot Orchestrator - runs all agents with health monitoring."""

import asyncio
import signal
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy
from pm_arb.core.config import settings
from pm_arb.db import get_pool, init_db

logger = structlog.get_logger()


class PilotOrchestrator:
    """Orchestrates all agents with health monitoring and auto-restart."""

    def __init__(
        self,
        redis_url: str | None = None,
        db_pool: asyncpg.Pool | None = None,
    ) -> None:
        self._redis_url = redis_url or settings.redis_url
        self._db_pool = db_pool
        self._agents: list[BaseAgent] = []
        self._agent_tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._stop_event = asyncio.Event()
        self._start_time: datetime | None = None
        self._restart_counts: dict[str, int] = {}
        self._last_heartbeats: dict[str, datetime] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def agents(self) -> list[BaseAgent]:
        return self._agents

    async def run(self) -> None:
        """Start all agents and monitor them."""
        self._running = True
        self._start_time = datetime.now(UTC)
        self._stop_event.clear()

        # Initialize database if pool not provided
        if self._db_pool is None:
            await init_db()
            self._db_pool = await get_pool()

        logger.info("pilot_starting")

        # Create agents in startup order
        self._agents = self._create_agents()

        # Start all agents
        for agent in self._agents:
            await self._start_agent(agent)

        logger.info("pilot_started", agent_count=len(self._agents))

        # Monitor loop
        try:
            while self._running and not self._stop_event.is_set():
                await self._health_check()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("pilot_cancelled")
        finally:
            await self._shutdown()

    def _create_agents(self) -> list[BaseAgent]:
        """Create all agents in startup order."""
        # Create adapters
        polymarket_adapter = PolymarketAdapter()
        binance_oracle = BinanceOracle()

        # Define channels for scanner
        venue_channels = ["venue.polymarket.prices"]
        oracle_channels = ["oracle.binance.prices"]

        return [
            # Data feeds first
            VenueWatcherAgent(
                self._redis_url,
                adapter=polymarket_adapter,
                poll_interval=5.0,
            ),
            OracleAgent(
                self._redis_url,
                oracle=binance_oracle,
                symbols=["BTCUSDT", "ETHUSDT"],
                poll_interval=1.0,
            ),
            # Detection layer
            OpportunityScannerAgent(
                self._redis_url,
                venue_channels=venue_channels,
                oracle_channels=oracle_channels,
            ),
            # Risk & execution
            RiskGuardianAgent(self._redis_url),
            PaperExecutorAgent(self._redis_url, db_pool=self._db_pool),
            # Strategy & capital
            OracleSniperStrategy(self._redis_url),
            CapitalAllocatorAgent(self._redis_url),
        ]

    async def _start_agent(self, agent: BaseAgent) -> None:
        """Start a single agent with error handling and auto-restart."""

        async def run_with_restart() -> None:
            backoff = 1
            max_backoff = 60
            max_failures = 5
            failures = 0

            while self._running and failures < max_failures:
                try:
                    self._last_heartbeats[agent.name] = datetime.now(UTC)
                    await agent.run()
                    break  # Clean exit
                except Exception as e:
                    failures += 1
                    self._restart_counts[agent.name] = (
                        self._restart_counts.get(agent.name, 0) + 1
                    )
                    logger.error(
                        "agent_crashed",
                        agent=agent.name,
                        error=str(e),
                        failures=failures,
                        backoff=backoff,
                    )
                    if failures < max_failures:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                    else:
                        logger.error("agent_max_failures", agent=agent.name)

        task = asyncio.create_task(run_with_restart())
        self._agent_tasks[agent.name] = task
        logger.info("agent_started", agent=agent.name)

    async def _health_check(self) -> None:
        """Check agent health and log warnings for stale agents."""
        now = datetime.now(UTC)
        stale_threshold = 120  # 2 minutes

        for agent in self._agents:
            last_beat = self._last_heartbeats.get(agent.name)
            if last_beat and (now - last_beat).total_seconds() > stale_threshold:
                logger.warning(
                    "agent_stale",
                    agent=agent.name,
                    last_beat=last_beat.isoformat(),
                )

            # Update heartbeat if agent is running
            if agent.is_running:
                self._last_heartbeats[agent.name] = now

    def get_health(self) -> dict[str, Any]:
        """Get current health status."""
        now = datetime.now(UTC)
        uptime = (now - self._start_time).total_seconds() if self._start_time else 0

        return {
            "running": self._running,
            "uptime_seconds": uptime,
            "agents": {
                agent.name: {
                    "running": agent.is_running,
                    "restarts": self._restart_counts.get(agent.name, 0),
                    "last_heartbeat": self._last_heartbeats.get(
                        agent.name, now
                    ).isoformat(),
                }
                for agent in self._agents
            },
        }

    async def stop(self) -> None:
        """Signal graceful shutdown."""
        logger.info("pilot_stopping")
        self._running = False
        self._stop_event.set()

        # Stop agents in reverse order
        for agent in reversed(self._agents):
            await agent.stop()

        # Cancel tasks
        for task in self._agent_tasks.values():
            task.cancel()

        # Wait for tasks to complete
        if self._agent_tasks:
            await asyncio.gather(*self._agent_tasks.values(), return_exceptions=True)

    async def _shutdown(self) -> None:
        """Clean shutdown."""
        logger.info("pilot_shutdown_complete")


async def main() -> None:
    """Entry point for running the pilot."""
    orchestrator = PilotOrchestrator()

    # Handle signals (cross-platform)
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(orchestrator.stop())
            )
    else:
        # Windows fallback - just run and rely on KeyboardInterrupt
        pass

    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
