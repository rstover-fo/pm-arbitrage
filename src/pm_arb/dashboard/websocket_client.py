"""WebSocket client for Streamlit dashboard."""

import json
from typing import Any

from websockets.sync.client import connect


def get_realtime_data(ws_url: str = "ws://localhost:8000/ws") -> dict[str, Any] | None:
    """
    Connect to WebSocket and get latest state.

    Note: Streamlit reruns the entire script, so we do a quick connect/receive/disconnect.
    For true real-time, consider streamlit-autorefresh or custom components.
    """
    try:
        with connect(ws_url, open_timeout=1, close_timeout=1) as websocket:
            # Subscribe to all updates
            websocket.send(
                json.dumps(
                    {
                        "type": "subscribe",
                        "channels": ["agent.updates", "risk.state", "trade.results"],
                    }
                )
            )

            # Get subscription confirmation
            response = websocket.recv(timeout=1)
            data = json.loads(response)

            if data.get("type") == "subscribed":
                return {"connected": True, "channels": data.get("channels", [])}

            return {"connected": True, "data": data}

    except Exception as e:
        return {"connected": False, "error": str(e)}


def check_websocket_health(base_url: str = "http://localhost:8000") -> dict[str, Any]:
    """Check if WebSocket server is healthy."""
    import httpx

    try:
        response = httpx.get(f"{base_url}/health", timeout=2)
        result: dict[str, Any] = response.json()
        return result
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
