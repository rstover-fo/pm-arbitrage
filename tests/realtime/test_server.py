"""Tests for WebSocket server."""

import pytest
from fastapi.testclient import TestClient

from pm_arb.realtime.server import create_app


def test_health_endpoint() -> None:
    """Should return healthy status."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_websocket_connection() -> None:
    """Should accept WebSocket connections."""
    app = create_app()

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            # Send a ping
            websocket.send_json({"type": "ping"})
            response = websocket.receive_json()

            assert response["type"] == "pong"
