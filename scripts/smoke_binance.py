"""Smoke test: verify Binance WebSocket streaming.

Usage: python -m scripts.smoke_binance
   or: .venv/bin/python scripts/smoke_binance.py
"""

import asyncio
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime

from pm_arb.adapters.oracles.crypto import BinanceOracle


async def main() -> None:
    symbols = ["BTC", "ETH"]
    oracle = BinanceOracle()

    print(f"[{datetime.now(UTC):%H:%M:%S}] Connecting to Binance...")
    await oracle.connect()

    print(f"[{datetime.now(UTC):%H:%M:%S}] Subscribing to {symbols} via WebSocket...")
    await oracle.subscribe(symbols)

    print(f"[{datetime.now(UTC):%H:%M:%S}] supports_streaming = {oracle.supports_streaming}")
    print(f"[{datetime.now(UTC):%H:%M:%S}] Streaming for 2 minutes...\n")

    counts: dict[str, int] = defaultdict(int)
    start = time.monotonic()
    duration = 120  # 2 minutes

    try:
        async for data in oracle.stream():
            elapsed = time.monotonic() - start
            if elapsed > duration:
                break

            counts[data.symbol] += 1
            total = sum(counts.values())

            # Print every 10th message to avoid flooding
            if total % 10 == 1 or total <= 5:
                print(
                    f"  [{elapsed:6.1f}s] oracle.binance.{data.symbol} "
                    f"= ${data.value:,.2f}  "
                    f"(msg #{total}, {data.symbol} count: {counts[data.symbol]})"
                )

    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.monotonic() - start
        await oracle.disconnect()

        print(f"\n{'='*60}")
        print(f"  Duration: {elapsed:.1f}s")
        for sym, count in sorted(counts.items()):
            rate = count / elapsed if elapsed > 0 else 0
            print(f"  {sym}: {count} messages ({rate:.2f}/s)")
        total = sum(counts.values())
        rate = total / elapsed if elapsed > 0 else 0
        print(f"  Total: {total} messages ({rate:.2f}/s)")
        print(f"{'='*60}")

        if total == 0:
            print("\n  FAIL: No messages received!")
            sys.exit(1)
        else:
            print("\n  PASS: Binance WebSocket streaming verified.")


if __name__ == "__main__":
    asyncio.run(main())
