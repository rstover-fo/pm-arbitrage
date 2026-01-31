#!/usr/bin/env python3
"""Script to run all PM Arbitrage agents."""

import asyncio
import signal
import sys
from decimal import Decimal

import structlog

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.agents.strategy_agent import StrategyAgent
from pm_arb.core.registry import AgentRegistry
from pm_arb.strategies.oracle_sniper import OracleSniperStrategy

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


async def main() -> None:
    """Run all agents."""
    redis_url = "redis://localhost:6379"
    registry = AgentRegistry()

    # Create agents
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
    )

    executor = PaperExecutorAgent(redis_url=redis_url)

    scanner = OpportunityScannerAgent(redis_url=redis_url)

    strategy = StrategyAgent(
        redis_url=redis_url,
        strategy=OracleSniperStrategy(),
    )

    # Register agents
    registry.register(allocator)
    registry.register(guardian)
    registry.register(executor)
    registry.register(scanner)
    registry.register(strategy)

    # Start all agents
    agents = [allocator, guardian, executor, scanner, strategy]

    logger.info("starting_agents", count=len(agents))

    # Handle shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(sig: int) -> None:
        logger.info("shutdown_signal_received", signal=sig)
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, lambda s=sig: handle_signal(s))

    # Start agents
    tasks = [asyncio.create_task(agent.run()) for agent in agents]

    logger.info(
        "agents_running",
        agents=[a.name for a in agents],
        registry_agents=registry.list_agents(),
    )

    # Wait for shutdown
    await shutdown_event.wait()

    # Stop agents
    logger.info("stopping_agents")
    for agent in agents:
        await agent.stop()

    # Cancel tasks
    for task in tasks:
        task.cancel()

    logger.info("agents_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
