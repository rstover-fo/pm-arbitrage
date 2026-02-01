#!/usr/bin/env python3
"""Script to run the WebSocket real-time server."""

import uvicorn

from pm_arb.realtime.app import create_realtime_app


def main() -> None:
    """Run the WebSocket server."""
    app = create_realtime_app()

    print("Starting WebSocket Real-Time Server...")
    print("   URL: ws://localhost:8000/ws")
    print("   Health: http://localhost:8000/health")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
