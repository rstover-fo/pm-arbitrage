# Sprint 8: WebSocket Real-Time Updates Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the dashboard's 5-second polling with real-time push updates via WebSocket, eliminating latency in viewing live agent data.

**Architecture:** Add a FastAPI WebSocket server that bridges Redis pub/sub to browser clients. Dashboard connects via WebSocket, receives state updates as they happen. Streamlit uses st_autorefresh with custom WebSocket component.

**Tech Stack:** Python 3.12, FastAPI, WebSockets, Redis pub/sub, Streamlit, uvicorn

**Demo:** Start agents → Start WebSocket server → Open dashboard → Watch metrics update in real-time without page refresh.

---

## Task 8.1: WebSocket Server Foundation

**Files:**
- Create: `src/pm_arb/realtime/__init__.py`
- Create: `src/pm_arb/realtime/server.py`
- Create: `tests/realtime/__init__.py`
- Create: `tests/realtime/test_server.py`

**Step 1: Write the failing test**

Create `tests/realtime/__init__.py` (empty file)

Create `tests/realtime/test_server.py`:

```python
"""Tests for WebSocket server."""

import asyncio

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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/realtime/test_server.py -v`
Expected: FAIL (ModuleNotFoundError: No module named 'pm_arb.realtime')

**Step 3: Create directory structure**

```bash
mkdir -p src/pm_arb/realtime
touch src/pm_arb/realtime/__init__.py
```

**Step 4: Write implementation**

Create `src/pm_arb/realtime/server.py`:

```python
"""WebSocket server for real-time dashboard updates."""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import structlog

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

    async def broadcast(self, message: dict) -> None:
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
    async def health() -> dict:
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
                    await websocket.send_json({
                        "type": "subscribed",
                        "channels": data.get("channels", []),
                    })

        except WebSocketDisconnect:
            manager.disconnect(websocket)

    # Store manager on app for access in other modules
    app.state.manager = manager

    return app
```

**Step 5: Add fastapi to dependencies**

Add to pyproject.toml dependencies:
```
"fastapi>=0.109.0",
"uvicorn>=0.27.0",
```

Run: `pip install -e ".[dev]"`

**Step 6: Run test**

Run: `pytest tests/realtime/test_server.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/pm_arb/realtime/ tests/realtime/
git commit -m "feat: add WebSocket server foundation"
```

---

## Task 8.2: Redis Bridge - Subscribe to Agent Updates

**Files:**
- Create: `src/pm_arb/realtime/redis_bridge.py`
- Create: `tests/realtime/test_redis_bridge.py`

**Step 1: Write the failing test**

Create `tests/realtime/test_redis_bridge.py`:

```python
"""Tests for Redis to WebSocket bridge."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.realtime.redis_bridge import RedisBridge


@pytest.mark.asyncio
async def test_bridge_receives_messages() -> None:
    """Should receive messages from Redis and call handler."""
    received = []

    async def handler(channel: str, data: dict) -> None:
        received.append((channel, data))

    bridge = RedisBridge(redis_url="redis://localhost:6379")
    bridge.on_message = handler

    # Start bridge in background
    task = asyncio.create_task(bridge.run())

    # Give it time to connect
    await asyncio.sleep(0.2)

    # Publish a test message directly to Redis
    import redis.asyncio as redis
    client = redis.from_url("redis://localhost:6379", decode_responses=True)
    await client.publish("agent.updates", '{"test": "data"}')
    await client.aclose()

    # Wait for message to be received
    await asyncio.sleep(0.2)

    # Stop bridge
    await bridge.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(received) == 1
    assert received[0][0] == "agent.updates"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/realtime/test_redis_bridge.py -v`
Expected: FAIL (cannot import name 'RedisBridge')

**Step 3: Write implementation**

Create `src/pm_arb/realtime/redis_bridge.py`:

```python
"""Bridge between Redis pub/sub and WebSocket connections."""

import asyncio
import json
from collections.abc import Awaitable, Callable

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()

# Channels to subscribe to for dashboard updates
DASHBOARD_CHANNELS = [
    "agent.updates",
    "trade.results",
    "risk.state",
    "portfolio.summary",
    "strategy.performance",
]


class RedisBridge:
    """Bridges Redis pub/sub messages to WebSocket clients."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._running = False
        self.on_message: Callable[[str, dict], Awaitable[None]] | None = None

    async def run(self) -> None:
        """Start listening for Redis messages."""
        self._client = redis.from_url(self._redis_url, decode_responses=True)
        self._pubsub = self._client.pubsub()
        self._running = True

        # Subscribe to all dashboard-relevant channels
        await self._pubsub.subscribe(*DASHBOARD_CHANNELS)
        logger.info("redis_bridge_subscribed", channels=DASHBOARD_CHANNELS)

        try:
            while self._running:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )

                if message and message["type"] == "message":
                    channel = message["channel"]
                    try:
                        data = json.loads(message["data"])
                    except json.JSONDecodeError:
                        data = {"raw": message["data"]}

                    if self.on_message:
                        await self.on_message(channel, data)

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            logger.info("redis_bridge_cancelled")
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """Stop the bridge."""
        self._running = False

    async def _cleanup(self) -> None:
        """Clean up connections."""
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.aclose()
        if self._client:
            await self._client.aclose()
        logger.info("redis_bridge_stopped")
```

**Step 4: Run test**

Run: `pytest tests/realtime/test_redis_bridge.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/realtime/redis_bridge.py tests/realtime/test_redis_bridge.py
git commit -m "feat: add Redis pub/sub to WebSocket bridge"
```

---

## Task 8.3: State Publisher - Agents Push State Changes

**Files:**
- Modify: `src/pm_arb/agents/capital_allocator.py`
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `src/pm_arb/agents/paper_executor.py`
- Create: `tests/realtime/test_state_publishing.py`

**Step 1: Write the failing test**

Create `tests/realtime/test_state_publishing.py`:

```python
"""Tests for agent state publishing to Redis pub/sub."""

import asyncio
from decimal import Decimal

import pytest
import redis.asyncio as redis

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent


@pytest.mark.asyncio
async def test_allocator_publishes_state_on_change() -> None:
    """Allocator should publish state to Redis pub/sub when it changes."""
    redis_url = "redis://localhost:6379"

    # Set up listener
    client = redis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe("agent.updates")

    # Create allocator
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")

    # Trigger state publish
    await allocator.publish_state_update()

    # Check for message (with timeout)
    message = None
    for _ in range(10):
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
        if msg and msg["type"] == "message":
            message = msg
            break
        await asyncio.sleep(0.1)

    await pubsub.unsubscribe()
    await pubsub.aclose()
    await client.aclose()

    assert message is not None
    assert message["channel"] == "agent.updates"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/realtime/test_state_publishing.py -v`
Expected: FAIL (AttributeError: 'CapitalAllocatorAgent' has no attribute 'publish_state_update')

**Step 3: Add publish_state_update to CapitalAllocatorAgent**

Add to `src/pm_arb/agents/capital_allocator.py` (at end of class):

```python
    async def publish_state_update(self) -> None:
        """Publish current state to Redis pub/sub for real-time dashboard."""
        import redis.asyncio as aioredis
        import json

        snapshot = self.get_state_snapshot()

        client = aioredis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.publish(
                "agent.updates",
                json.dumps({
                    "agent": self.name,
                    "type": "state_update",
                    "data": {
                        "total_capital": str(snapshot["total_capital"]),
                        "strategies": {
                            k: {
                                "total_pnl": str(v["total_pnl"]),
                                "trades": v["trades"],
                                "wins": v["wins"],
                                "losses": v["losses"],
                                "allocation_pct": str(v["allocation_pct"]),
                            }
                            for k, v in snapshot["strategies"].items()
                        },
                    },
                }),
            )
        finally:
            await client.aclose()
```

**Step 4: Add publish_state_update to RiskGuardianAgent**

Add to `src/pm_arb/agents/risk_guardian.py` (at end of class):

```python
    async def publish_state_update(self) -> None:
        """Publish current state to Redis pub/sub for real-time dashboard."""
        import redis.asyncio as aioredis
        import json

        snapshot = self.get_state_snapshot()

        client = aioredis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.publish(
                "risk.state",
                json.dumps({
                    "agent": self.name,
                    "type": "state_update",
                    "data": {
                        "current_value": str(snapshot["current_value"]),
                        "high_water_mark": str(snapshot["high_water_mark"]),
                        "daily_pnl": str(snapshot["daily_pnl"]),
                        "halted": snapshot["halted"],
                    },
                }),
            )
        finally:
            await client.aclose()
```

**Step 5: Add publish_state_update to PaperExecutorAgent**

Add to `src/pm_arb/agents/paper_executor.py` (at end of class):

```python
    async def publish_state_update(self) -> None:
        """Publish current state to Redis pub/sub for real-time dashboard."""
        import redis.asyncio as aioredis
        import json

        snapshot = self.get_state_snapshot()

        client = aioredis.from_url(self._redis_url, decode_responses=True)
        try:
            await client.publish(
                "trade.results",
                json.dumps({
                    "agent": self.name,
                    "type": "state_update",
                    "data": {
                        "trade_count": snapshot["trade_count"],
                        "recent_trades": snapshot["recent_trades"][:10],
                    },
                }),
            )
        finally:
            await client.aclose()
```

**Step 6: Run test**

Run: `pytest tests/realtime/test_state_publishing.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/pm_arb/agents/capital_allocator.py src/pm_arb/agents/risk_guardian.py src/pm_arb/agents/paper_executor.py tests/realtime/test_state_publishing.py
git commit -m "feat: add state publishing to agents for real-time updates"
```

---

## Task 8.4: Integrated WebSocket Server

**Files:**
- Create: `src/pm_arb/realtime/app.py`
- Create: `scripts/run_websocket.py`

**Step 1: Create integrated app that combines server + bridge**

Create `src/pm_arb/realtime/app.py`:

```python
"""Integrated WebSocket application with Redis bridge."""

import asyncio

from fastapi import FastAPI
import structlog

from pm_arb.realtime.server import create_app, ConnectionManager
from pm_arb.realtime.redis_bridge import RedisBridge

logger = structlog.get_logger()


def create_realtime_app(redis_url: str = "redis://localhost:6379") -> FastAPI:
    """Create the real-time WebSocket app with Redis bridge."""
    app = create_app()
    bridge = RedisBridge(redis_url)

    async def forward_to_websockets(channel: str, data: dict) -> None:
        """Forward Redis messages to all WebSocket clients."""
        manager: ConnectionManager = app.state.manager
        await manager.broadcast({
            "type": "update",
            "channel": channel,
            "data": data,
        })

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
```

**Step 2: Create run script**

Create `scripts/run_websocket.py`:

```python
#!/usr/bin/env python3
"""Script to run the WebSocket real-time server."""

import uvicorn

from pm_arb.realtime.app import create_realtime_app


def main() -> None:
    """Run the WebSocket server."""
    app = create_realtime_app()

    print("🚀 Starting WebSocket Real-Time Server...")
    print("   URL: ws://localhost:8000/ws")
    print("   Health: http://localhost:8000/health")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

**Step 3: Make script executable and verify syntax**

```bash
chmod +x scripts/run_websocket.py
python -m py_compile scripts/run_websocket.py
python -m py_compile src/pm_arb/realtime/app.py
```

**Step 4: Commit**

```bash
git add src/pm_arb/realtime/app.py scripts/run_websocket.py
git commit -m "feat: add integrated WebSocket server with Redis bridge"
```

---

## Task 8.5: Streamlit WebSocket Client Component

**Files:**
- Create: `src/pm_arb/dashboard/websocket_client.py`
- Modify: `src/pm_arb/dashboard/app_live.py`

**Step 1: Create WebSocket client helper**

Create `src/pm_arb/dashboard/websocket_client.py`:

```python
"""WebSocket client for Streamlit dashboard."""

import json
from typing import Any

import streamlit as st
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
            websocket.send(json.dumps({
                "type": "subscribe",
                "channels": ["agent.updates", "risk.state", "trade.results"],
            }))

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
        return response.json()
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
```

**Step 2: Update app_live.py to show WebSocket status**

Add to `src/pm_arb/dashboard/app_live.py` in the `render_system` function, after the "System Status" section:

```python
        st.subheader("Real-Time Connection")
        from pm_arb.dashboard.websocket_client import check_websocket_health

        ws_health = check_websocket_health()
        if ws_health.get("status") == "healthy":
            connections = ws_health.get("connections", 0)
            st.success(f"🟢 WebSocket Server Running ({connections} clients)")
        else:
            st.warning("🟡 WebSocket Server Not Running")
            st.caption("Start with: `python scripts/run_websocket.py`")
```

**Step 3: Verify syntax**

```bash
python -m py_compile src/pm_arb/dashboard/websocket_client.py
python -m py_compile src/pm_arb/dashboard/app_live.py
```

**Step 4: Commit**

```bash
git add src/pm_arb/dashboard/websocket_client.py src/pm_arb/dashboard/app_live.py
git commit -m "feat: add WebSocket client for dashboard real-time status"
```

---

## Task 8.6: Auto-Publish State on Agent Changes

**Files:**
- Modify: `src/pm_arb/agents/capital_allocator.py`
- Modify: `src/pm_arb/agents/paper_executor.py`

**Step 1: Add auto-publish after trade result handling**

In `src/pm_arb/agents/capital_allocator.py`, modify `_handle_trade_result` to publish state after update:

Add at the end of `_handle_trade_result` method (before the rebalance check):

```python
        # Publish state update for real-time dashboard
        await self.publish_state_update()
```

**Step 2: Add auto-publish after trade execution**

In `src/pm_arb/agents/paper_executor.py`, modify `_execute_paper_trade` to publish state after trade:

Add at the end of `_execute_paper_trade` method (after `del self._pending_requests[request_id]`):

```python
        # Publish state update for real-time dashboard
        await self.publish_state_update()
```

**Step 3: Commit**

```bash
git add src/pm_arb/agents/capital_allocator.py src/pm_arb/agents/paper_executor.py
git commit -m "feat: auto-publish agent state on changes for real-time updates"
```

---

## Task 8.7: Sprint 8 Integration Test

**Files:**
- Create: `tests/integration/test_sprint8.py`

**Step 1: Write integration test**

Create `tests/integration/test_sprint8.py`:

```python
"""Integration test for Sprint 8: WebSocket Real-Time Updates."""

import asyncio
import json
from decimal import Decimal

import pytest
import redis.asyncio as redis

from pm_arb.agents.capital_allocator import CapitalAllocatorAgent
from pm_arb.agents.paper_executor import PaperExecutorAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.registry import AgentRegistry
from pm_arb.realtime.redis_bridge import RedisBridge


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Reset registry before and after each test."""
    AgentRegistry.reset_instance()
    yield
    AgentRegistry.reset_instance()


@pytest.mark.asyncio
async def test_realtime_updates_flow() -> None:
    """Agent state changes should flow through Redis pub/sub."""
    redis_url = "redis://localhost:6379"

    # Collect messages from the bridge
    received_messages: list[tuple[str, dict]] = []

    async def collect_message(channel: str, data: dict) -> None:
        received_messages.append((channel, data))

    # Start Redis bridge
    bridge = RedisBridge(redis_url)
    bridge.on_message = collect_message
    bridge_task = asyncio.create_task(bridge.run())

    # Wait for bridge to connect
    await asyncio.sleep(0.3)

    # Create agents
    allocator = CapitalAllocatorAgent(
        redis_url=redis_url,
        total_capital=Decimal("1000"),
    )
    allocator.register_strategy("oracle-sniper")
    allocator._strategy_performance["oracle-sniper"]["total_pnl"] = Decimal("100")

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("1000"),
    )
    guardian._current_value = Decimal("1100")

    executor = PaperExecutorAgent(redis_url=redis_url)

    # Publish state updates
    await allocator.publish_state_update()
    await guardian.publish_state_update()
    await executor.publish_state_update()

    # Wait for messages to be received
    await asyncio.sleep(0.5)

    # Stop bridge
    await bridge.stop()
    bridge_task.cancel()
    try:
        await bridge_task
    except asyncio.CancelledError:
        pass

    # Verify messages were received
    channels = [msg[0] for msg in received_messages]

    print(f"\nReceived {len(received_messages)} messages:")
    for channel, data in received_messages:
        print(f"  {channel}: {data.get('agent', 'unknown')}")

    assert "agent.updates" in channels, "Should receive allocator update"
    assert "risk.state" in channels, "Should receive guardian update"
    assert "trade.results" in channels, "Should receive executor update"
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_sprint8.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/test_sprint8.py
git commit -m "test: add Sprint 8 integration test - real-time WebSocket updates"
```

---

## Task 8.8: Sprint 8 Final Commit

**Step 1: Run all tests**

Run: `pytest tests/ -v --ignore=tests/integration/test_sprint2.py --ignore=tests/integration/test_sprint3.py`
Expected: All pass

**Step 2: Lint and type check**

Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`
Run: `mypy src/`
Expected: Clean

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore: Sprint 8 complete - WebSocket Real-Time Updates

- WebSocket server with FastAPI for real-time connections
- Redis pub/sub bridge for agent state updates
- State publishing methods on all agents
- Auto-publish on agent state changes
- WebSocket health check in dashboard
- Integration test verifying real-time flow

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Sprint 8 Complete

**Demo steps:**
1. Terminal 1: `redis-server` (start Redis)
2. Terminal 2: `python scripts/run_agents.py` (start agents)
3. Terminal 3: `python scripts/run_websocket.py` (start WebSocket server)
4. Terminal 4: `python scripts/run_dashboard.py --live` (start dashboard)
5. Open http://localhost:8501
6. Navigate to System page - see WebSocket status
7. Watch metrics update in real-time as agents process

**What we built:**
- FastAPI WebSocket server for real-time connections
- Redis pub/sub bridge forwarding agent updates
- State publishing on all agents (allocator, guardian, executor)
- Auto-publish when agent state changes
- WebSocket health monitoring in dashboard

**Data flow:**
```
Agent State Change
       ↓
publish_state_update()
       ↓
Redis pub/sub channel
       ↓
RedisBridge (subscribes)
       ↓
WebSocket broadcast
       ↓
Browser receives update
```

**Next: Sprint 9 - True Real-Time Dashboard (Streamlit custom component or switch to React)**
