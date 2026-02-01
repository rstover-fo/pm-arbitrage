"""Integrated WebSocket application with Redis bridge."""

import asyncio
from typing import Any

import structlog
from fastapi import FastAPI

from pm_arb.realtime.redis_bridge import RedisBridge
from pm_arb.realtime.server import ConnectionManager, create_app

logger = structlog.get_logger()


def create_realtime_app(redis_url: str = "redis://localhost:6379") -> FastAPI:
    """Create the real-time WebSocket app with Redis bridge."""
    app = create_app()
    bridge = RedisBridge(redis_url)

    async def forward_to_websockets(channel: str, data: dict[str, Any]) -> None:
        """Forward Redis messages to all WebSocket clients."""
        manager: ConnectionManager = app.state.manager
        await manager.broadcast(
            {
                "type": "update",
                "channel": channel,
                "data": data,
            }
        )

    bridge.on_message = forward_to_websockets

    @app.on_event("startup")
    async def startup() -> None:
        """Start Redis bridge on app startup."""
        app.state.bridge = bridge
        app.state.bridge_task = asyncio.create_task(bridge.run())
        logger.info("realtime_app_started")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        """Stop Redis bridge on app shutdown."""
        await bridge.stop()
        app.state.bridge_task.cancel()
        try:
            await app.state.bridge_task
        except asyncio.CancelledError:
            pass
        logger.info("realtime_app_stopped")

    return app
