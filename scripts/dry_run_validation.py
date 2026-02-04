#!/usr/bin/env python3
"""
30-minute dry-run validation script for pm-arbitrage.

Runs the full pipeline with live data and collects metrics to validate:
- System stability (no crashes)
- Data flow (venue + oracle prices)
- Opportunity detection
- Paper trade execution

Usage:
    python scripts/dry_run_validation.py [--duration MINUTES]

Requirements:
    - Redis running locally (docker compose up -d redis)
    - PostgreSQL running locally (for paper trade persistence)
"""

import argparse
import asyncio
import signal
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


class DryRunMetrics:
    """Collects and tracks dry-run metrics."""

    def __init__(self) -> None:
        self.start_time = datetime.now(UTC)
        self.venue_prices = 0
        self.oracle_prices = 0
        self.opportunities_detected = 0
        self.trade_requests = 0
        self.risk_approvals = 0
        self.risk_rejections = 0
        self.paper_trades = 0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "start_time": self.start_time.isoformat(),
            "runtime_seconds": (datetime.now(UTC) - self.start_time).total_seconds(),
            "venue_prices": self.venue_prices,
            "oracle_prices": self.oracle_prices,
            "opportunities_detected": self.opportunities_detected,
            "trade_requests": self.trade_requests,
            "risk_approvals": self.risk_approvals,
            "risk_rejections": self.risk_rejections,
            "paper_trades": self.paper_trades,
            "errors": self.errors,
        }


class MetricCollector:
    """Reads from Redis Streams and collects metrics."""

    # Streams to monitor (agents publish via XADD to these)
    # Note: venue/oracle streams include adapter names
    STREAMS = [
        "venue.polymarket.prices",  # VenueWatcher publishes venue.{adapter}.prices
        "oracle.coingecko.BTC",  # OracleAgent publishes oracle.{source}.{symbol}
        "oracle.coingecko.ETH",
        "opportunities.detected",
        "trade.requests",
        "trade.decisions",
        "trade.results",
    ]

    def __init__(self, redis_url: str, metrics: DryRunMetrics) -> None:
        self._redis_url = redis_url
        self._metrics = metrics
        self._running = False
        # Track last read ID for each stream (start from newest messages)
        self._last_ids: dict[str, str] = {stream: "$" for stream in self.STREAMS}

    async def run(self) -> None:
        """Read from Redis Streams and collect metrics."""
        import redis.asyncio as redis

        client = redis.from_url(self._redis_url, decode_responses=True)

        self._running = True
        logger.info("metric_collector_started", streams=self.STREAMS)

        try:
            while self._running:
                # Build streams dict for XREAD
                streams_to_read = {
                    stream: self._last_ids[stream] for stream in self.STREAMS
                }

                try:
                    # XREAD with 1 second block timeout
                    results = await client.xread(streams_to_read, count=100, block=1000)

                    if not results:
                        continue

                    # Process each stream's messages
                    for stream_name, entries in results:
                        for msg_id, data in entries:
                            self._process_message(stream_name, data)
                            # Update last ID for this stream
                            self._last_ids[stream_name] = msg_id

                except redis.ResponseError as e:
                    # Stream might not exist yet - that's ok
                    if "NOGROUP" not in str(e):
                        logger.warning("redis_read_error", error=str(e))

        except asyncio.CancelledError:
            pass
        finally:
            await client.aclose()
            logger.info("metric_collector_stopped")

    def _process_message(self, stream: str, data: dict[str, Any]) -> None:
        """Process a message and update metrics."""
        if stream.startswith("venue.") and stream.endswith(".prices"):
            self._metrics.venue_prices += 1
        elif stream.startswith("oracle."):
            self._metrics.oracle_prices += 1
        elif stream == "opportunities.detected":
            self._metrics.opportunities_detected += 1
        elif stream == "trade.requests":
            self._metrics.trade_requests += 1
        elif stream == "trade.decisions":
            # Check approval status from data dict
            approved = data.get("approved", "")
            if str(approved).lower() == "true":
                self._metrics.risk_approvals += 1
            else:
                self._metrics.risk_rejections += 1
        elif stream == "trade.results":
            self._metrics.paper_trades += 1

    def stop(self) -> None:
        """Signal to stop collecting."""
        self._running = False


async def run_dry_run(duration_minutes: int = 30) -> DryRunMetrics:
    """Run the full pipeline for specified duration and collect metrics."""
    from pm_arb.pilot import PilotOrchestrator

    metrics = DryRunMetrics()
    redis_url = "redis://localhost:6379"

    # Create metric collector
    collector = MetricCollector(redis_url, metrics)

    # Create orchestrator (paper trading mode - no live execution)
    orchestrator = PilotOrchestrator(redis_url=redis_url)

    end_time = datetime.now(UTC) + timedelta(minutes=duration_minutes)

    logger.info(
        "dry_run_starting",
        duration_minutes=duration_minutes,
        end_time=end_time.isoformat(),
    )

    # Handle graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal(signum: int, frame: Any) -> None:
        logger.info("shutdown_signal_received", signal=signum)
        shutdown_event.set()

    if sys.platform != "win32":
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        # Start metric collector
        collector_task = asyncio.create_task(collector.run())

        # Start orchestrator
        orchestrator_task = asyncio.create_task(orchestrator.run())

        # Monitor loop
        while datetime.now(UTC) < end_time and not shutdown_event.is_set():
            await asyncio.sleep(60)  # Log progress every minute

            elapsed = (datetime.now(UTC) - metrics.start_time).total_seconds() / 60
            remaining = (end_time - datetime.now(UTC)).total_seconds() / 60

            logger.info(
                "dry_run_progress",
                elapsed_minutes=round(elapsed, 1),
                remaining_minutes=round(remaining, 1),
                venue_prices=metrics.venue_prices,
                oracle_prices=metrics.oracle_prices,
                opportunities=metrics.opportunities_detected,
                paper_trades=metrics.paper_trades,
            )

        # Shutdown
        logger.info("dry_run_stopping")
        collector.stop()
        await orchestrator.stop()

        # Wait for tasks to complete
        await asyncio.gather(orchestrator_task, return_exceptions=True)
        collector_task.cancel()
        try:
            await collector_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        metrics.errors.append(f"Fatal error: {str(e)}")
        logger.error("dry_run_error", error=str(e))

    return metrics


def validate_metrics(metrics: DryRunMetrics) -> bool:
    """Check if dry-run meets success criteria."""
    checks = [
        ("No fatal errors", len(metrics.errors) == 0),
        ("Venue prices flowing", metrics.venue_prices > 0),
        ("Oracle prices flowing", metrics.oracle_prices > 0),
        ("Opportunities detected", metrics.opportunities_detected > 0),
        ("Paper trades executed", metrics.paper_trades > 0),
    ]

    print("\n" + "=" * 60)
    print("DRY-RUN VALIDATION RESULTS")
    print("=" * 60)

    all_passed = True
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"[{symbol}] {status}: {name}")
        if not passed:
            all_passed = False

    print("=" * 60)
    print("\nMetrics Summary:")
    print(f"  Runtime: {metrics.to_dict()['runtime_seconds']:.1f} seconds")
    print(f"  Venue prices received: {metrics.venue_prices}")
    print(f"  Oracle prices received: {metrics.oracle_prices}")
    print(f"  Opportunities detected: {metrics.opportunities_detected}")
    print(f"  Trade requests: {metrics.trade_requests}")
    print(f"  Risk approvals: {metrics.risk_approvals}")
    print(f"  Risk rejections: {metrics.risk_rejections}")
    print(f"  Paper trades executed: {metrics.paper_trades}")

    if metrics.errors:
        print("\nErrors:")
        for error in metrics.errors:
            print(f"  - {error}")

    print("\n" + "=" * 60)
    overall = "PASSED" if all_passed else "FAILED"
    print(f"Overall: {overall}")
    print("=" * 60)

    return all_passed


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Run 30-minute dry-run validation for pm-arbitrage"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Duration in minutes (default: 30)",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick 2-minute test run",
    )
    args = parser.parse_args()

    duration = 2 if args.quick else args.duration

    print(f"\nStarting dry-run validation ({duration} minutes)...")
    print("Press Ctrl+C to stop early\n")

    metrics = asyncio.run(run_dry_run(duration))
    success = validate_metrics(metrics)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
