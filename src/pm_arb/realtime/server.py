"""WebSocket server for real-time dashboard updates."""

from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = structlog.get_logger()


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track new connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("websocket_connected", total=len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove disconnected client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("websocket_disconnected", total=len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for conn in disconnected:
            self.disconnect(conn)


def create_app() -> FastAPI:
    """Create FastAPI application with WebSocket support."""
    app = FastAPI(title="PM Arbitrage Real-Time API")
    manager = ConnectionManager()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "healthy",
            "connections": len(manager.active_connections),
        }

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_json()

                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif data.get("type") == "subscribe":
                    # Client subscribing to updates
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "channels": data.get("channels", []),
                        }
                    )

        except WebSocketDisconnect:
            manager.disconnect(websocket)

    # Store manager on app for access in other modules
    app.state.manager = manager

    return app
