"""Pilot Orchestrator - runs all agents with health monitoring."""

import asyncio
import os
import signal
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import asyncpg
import structlog

from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent
from pm_arb.core.alerts import AlertService
from pm_arb.core.auth import load_credentials
from pm_arb.core.config import settings
from pm_arb.core.market_matcher import MarketMatcher
from pm_arb.db import get_pool, init_db
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy

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
        self._alerts = AlertService()

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

        # Validate live mode before starting
        await self._validate_live_mode()

        logger.info("pilot_starting", paper_trading=settings.paper_trading)

        # Create agents in startup order
        self._agents = await self._create_agents()

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

    async def _validate_live_mode(self) -> None:
        """Validate system is ready for live trading.

        Raises:
            RuntimeError: If credentials missing, auth fails, or balance insufficient.
        """
        if settings.paper_trading:
            return  # Skip validation for paper mode

        logger.info("validating_live_mode")

        # 1. Check credentials exist
        try:
            creds = load_credentials("polymarket")
        except ValueError as e:
            raise RuntimeError(f"Live mode requires Polymarket credentials: {e}")

        # 2. Test API connection
        adapter = PolymarketAdapter(credentials=creds)
        await adapter.connect()

        if not adapter.is_authenticated:
            await adapter.disconnect()
            raise RuntimeError(
                "Failed to authenticate with Polymarket. "
                "Check your API credentials (POLYMARKET_API_KEY, POLYMARKET_SECRET, "
                "POLYMARKET_PASSPHRASE, POLYMARKET_PRIVATE_KEY)."
            )

        # 3. Check wallet balance
        try:
            balance = await adapter.get_balance()
            min_balance = Decimal(str(settings.initial_bankroll))

            if balance < min_balance:
                await adapter.disconnect()
                raise RuntimeError(
                    f"Insufficient wallet balance: ${balance:.2f} < ${min_balance:.2f} required. "
                    "Fund your Polymarket wallet with USDC on Polygon."
                )

            logger.info(
                "live_mode_validated",
                balance=str(balance),
                bankroll=str(min_balance),
            )
        except Exception as e:
            if "balance" not in str(e).lower():
                # Don't wrap our own RuntimeError
                if isinstance(e, RuntimeError):
                    raise
                raise RuntimeError(f"Failed to check wallet balance: {e}")
            raise

        await adapter.disconnect()

    async def _create_agents(self) -> list[BaseAgent]:
        """Create all agents in startup order."""
        # Create adapters
        polymarket_adapter = PolymarketAdapter()
        await polymarket_adapter.connect()
        binance_oracle = BinanceOracle()

        symbols = ["BTC", "ETH"]

        # Define channels for scanner
        # OracleAgent publishes to oracle.{source}.{SYMBOL} (e.g., oracle.binance.BTC)
        venue_channels = ["venue.polymarket.prices"]
        oracle_channels = [f"oracle.binance.{sym}" for sym in symbols]

        # Create scanner first so we can register mappings
        scanner = OpportunityScannerAgent(
            self._redis_url,
            venue_channels=venue_channels,
            oracle_channels=oracle_channels,
        )

        # Match markets to oracles before scanning starts
        matcher = MarketMatcher(scanner, anthropic_api_key=settings.anthropic_api_key)
        markets = await polymarket_adapter.get_markets()
        await matcher.match_markets(markets)

        # Choose executor based on paper_trading config
        if settings.paper_trading:
            executor: BaseAgent = PaperExecutorAgent(
                self._redis_url,
                db_pool=self._db_pool,
            )
            logger.info("executor_mode", mode="paper")
        else:
            # Live trading mode - load credentials
            credentials = {"polymarket": load_credentials("polymarket")}
            executor = LiveExecutorAgent(
                self._redis_url,
                credentials=credentials,
                db_pool=self._db_pool,
            )
            logger.info("executor_mode", mode="live")

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
                symbols=symbols,
                poll_interval=5.0,  # Only used for reconnect timing in streaming mode
            ),
            # Detection layer
            scanner,
            # Risk & execution
            RiskGuardianAgent(self._redis_url),
            executor,
            # Strategy & capital
            OracleSniperStrategy(self._redis_url),
            CapitalAllocatorAgent(self._redis_url),
        ]

    async def _start_agent(self, agent: BaseAgent) -> None:
        """Start a single agent with error handling and auto-restart."""
        alerts = self._alerts  # Capture reference for closure

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
                    self._restart_counts[agent.name] = self._restart_counts.get(agent.name, 0) + 1
                    logger.error(
                        "agent_crashed",
                        agent=agent.name,
                        error=str(e),
                        failures=failures,
                        backoff=backoff,
                    )

                    # Send alert on crash
                    await alerts.agent_crash(
                        agent_name=agent.name,
                        error=str(e),
                    )

                    if failures < max_failures:
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, max_backoff)
                    else:
                        logger.error("agent_max_failures", agent=agent.name)
                        # Send critical alert when agent is dead
                        await alerts.agent_dead(
                            agent_name=agent.name,
                            max_restarts=max_failures,
                        )

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
                    "last_heartbeat": self._last_heartbeats.get(agent.name, now).isoformat(),
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


def get_pid_file() -> Path:
    """Get path to PID file."""
    pid_dir = Path.home() / ".pm-arb"
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir / "pilot.pid"


async def main() -> None:
    """Entry point for running the pilot."""
    pid_file = get_pid_file()

    # Write PID file for kill switch
    pid_file.write_text(str(os.getpid()))
    logger.info("pid_file_written", pid=os.getpid(), path=str(pid_file))

    orchestrator = PilotOrchestrator()

    # Handle signals (cross-platform)
    if sys.platform != "win32":
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(orchestrator.stop()))
    else:
        # Windows fallback - just run and rely on KeyboardInterrupt
        pass

    try:
        await orchestrator.run()
    except KeyboardInterrupt:
        await orchestrator.stop()
    finally:
        # Clean up PID file
        pid_file.unlink(missing_ok=True)
        logger.info("pid_file_cleaned")


if __name__ == "__main__":
    asyncio.run(main())
