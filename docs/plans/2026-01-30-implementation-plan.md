# PM Arbitrage Bot - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an agent-based prediction market arbitrage system that detects and executes opportunities automatically with human-controlled risk.

**Architecture:** 8 autonomous Python agents communicating via Redis Streams. Agents are independent async processes. PostgreSQL for persistence. Streamlit for dashboard.

**Tech Stack:** Python 3.12, asyncio, Redis Streams, PostgreSQL, Streamlit, Anthropic API

---

## Sprint Overview

| Sprint | Deliverable | Demo |
|--------|-------------|------|
| 1 | Foundation | Agents start, connect to bus, send/receive messages |
| 2 | First Venue + Oracle | Stream live Polymarket + Binance prices |
| 3 | Opportunity Scanner | Detect crypto lag opportunities |
| 4 | Risk Guardian + Paper Executor | Paper trades with risk checks |
| 5 | Strategy + Allocator | End-to-end paper trading |
| 6 | Dashboard | Visual monitoring |
| 7 | Go Live | Real trading with alerts |

---

## Sprint 1: Foundation

**Goal:** Project skeleton with working message bus and base agent framework.

**Demo:** Run `docker-compose up`, start two test agents, see them exchange messages.

---

### Task 1.1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.env.example`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "pm-arbitrage"
version = "0.1.0"
description = "Prediction market arbitrage bot"
requires-python = ">=3.12"
dependencies = [
    "redis>=5.0.0",
    "asyncpg>=0.29.0",
    "sqlalchemy>=2.0.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "httpx>=0.26.0",
    "websockets>=12.0",
    "anthropic>=0.18.0",
    "python-dotenv>=1.0.0",
    "structlog>=24.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.2.0",
    "mypy>=1.8.0",
]
dashboard = [
    "streamlit>=1.31.0",
    "plotly>=5.18.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
```

**Step 2: Create .python-version**

```
3.12
```

**Step 3: Create .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
env/
.eggs/
*.egg-info/
dist/
build/

# Environment
.env
.env.local

# IDE
.idea/
.vscode/
*.swp
*.swo

# Testing
.coverage
htmlcov/
.pytest_cache/

# Logs
*.log
logs/

# Data
*.parquet
data/

# OS
.DS_Store
Thumbs.db
```

**Step 4: Create .env.example**

```bash
# Redis
REDIS_URL=redis://localhost:6379

# PostgreSQL
DATABASE_URL=postgresql://pm_arb:pm_arb@localhost:5432/pm_arb

# Anthropic (for market matching)
ANTHROPIC_API_KEY=sk-ant-xxx

# Polymarket
POLYMARKET_API_KEY=
POLYMARKET_PRIVATE_KEY=

# Kalshi
KALSHI_EMAIL=
KALSHI_PASSWORD=

# Binance (no auth needed for public websocket)

# Alerts (optional)
PUSHOVER_USER_KEY=
PUSHOVER_API_TOKEN=

# Risk Settings
INITIAL_BANKROLL=500
DRAWDOWN_LIMIT_PCT=20
DAILY_LOSS_LIMIT_PCT=10
POSITION_LIMIT_PCT=10
PLATFORM_LIMIT_PCT=50

# Mode
PAPER_TRADING=true
```

**Step 5: Commit**

```bash
git add pyproject.toml .python-version .gitignore .env.example
git commit -m "chore: initialize project with pyproject.toml and config"
```

---

### Task 1.2: Docker Compose Setup

**Files:**
- Create: `docker-compose.yml`
- Create: `docker-compose.override.yml`

**Step 1: Create docker-compose.yml**

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: pm_arb
      POSTGRES_PASSWORD: pm_arb
      POSTGRES_DB: pm_arb
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pm_arb"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  redis_data:
  postgres_data:
```

**Step 2: Create docker-compose.override.yml (for local dev)**

```yaml
# Local development overrides
services:
  redis:
    ports:
      - "6379:6379"

  postgres:
    ports:
      - "5432:5432"
```

**Step 3: Test it works**

Run: `docker-compose up -d`
Expected: Both containers start healthy

Run: `docker-compose ps`
Expected: redis and postgres show "healthy"

**Step 4: Commit**

```bash
git add docker-compose.yml docker-compose.override.yml
git commit -m "infra: add docker-compose for Redis and PostgreSQL"
```

---

### Task 1.3: Directory Structure

**Files:**
- Create: `src/pm_arb/__init__.py`
- Create: `src/pm_arb/core/__init__.py`
- Create: `src/pm_arb/agents/__init__.py`
- Create: `src/pm_arb/adapters/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create directory structure**

```bash
mkdir -p src/pm_arb/{core,agents,adapters/venues,adapters/oracles}
mkdir -p tests
touch src/pm_arb/__init__.py
touch src/pm_arb/core/__init__.py
touch src/pm_arb/agents/__init__.py
touch src/pm_arb/adapters/__init__.py
touch src/pm_arb/adapters/venues/__init__.py
touch src/pm_arb/adapters/oracles/__init__.py
touch tests/__init__.py
```

**Step 2: Create tests/conftest.py**

```python
"""Shared pytest fixtures."""

import asyncio
from collections.abc import AsyncGenerator, Generator

import pytest
import redis.asyncio as redis


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def redis_client() -> AsyncGenerator[redis.Redis, None]:
    """Provide Redis client for tests."""
    client = redis.from_url("redis://localhost:6379", decode_responses=True)
    yield client
    await client.flushdb()
    await client.aclose()
```

**Step 3: Commit**

```bash
git add src/ tests/
git commit -m "chore: create directory structure"
```

---

### Task 1.4: Configuration Module

**Files:**
- Create: `src/pm_arb/core/config.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/test_config.py`

**Step 1: Write the failing test**

Create `tests/core/__init__.py` (empty file)

Create `tests/core/test_config.py`:

```python
"""Tests for configuration module."""

import os

import pytest


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings should load values from environment variables."""
    monkeypatch.setenv("REDIS_URL", "redis://testhost:6379")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("INITIAL_BANKROLL", "1000")
    monkeypatch.setenv("PAPER_TRADING", "false")

    # Import fresh to pick up env vars
    from pm_arb.core.config import Settings

    settings = Settings()

    assert settings.redis_url == "redis://testhost:6379"
    assert settings.initial_bankroll == 1000
    assert settings.paper_trading is False


def test_settings_has_defaults() -> None:
    """Settings should have sensible defaults."""
    from pm_arb.core.config import Settings

    settings = Settings()

    assert settings.drawdown_limit_pct == 20
    assert settings.daily_loss_limit_pct == 10
    assert settings.paper_trading is True  # Default to safe mode
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_config.py -v`
Expected: FAIL with "ModuleNotFoundError" or "cannot import name 'Settings'"

**Step 3: Write minimal implementation**

Create `src/pm_arb/core/config.py`:

```python
"""Application configuration using pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Infrastructure
    redis_url: str = "redis://localhost:6379"
    database_url: str = "postgresql://pm_arb:pm_arb@localhost:5432/pm_arb"

    # API Keys (optional for paper trading)
    anthropic_api_key: str = ""
    polymarket_api_key: str = ""
    polymarket_private_key: str = ""
    kalshi_email: str = ""
    kalshi_password: str = ""

    # Alerts (optional)
    pushover_user_key: str = ""
    pushover_api_token: str = ""

    # Risk Settings
    initial_bankroll: float = 500.0
    drawdown_limit_pct: float = 20.0
    daily_loss_limit_pct: float = 10.0
    position_limit_pct: float = 10.0
    platform_limit_pct: float = 50.0

    # Mode
    paper_trading: bool = True
    log_level: str = "INFO"


# Singleton instance
settings = Settings()
```

**Step 4: Install dependencies and run test**

Run: `pip install -e ".[dev]"`
Run: `pytest tests/core/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/core/config.py tests/core/
git commit -m "feat: add configuration module with pydantic-settings"
```

---

### Task 1.5: Message Bus Module

**Files:**
- Create: `src/pm_arb/core/message_bus.py`
- Create: `tests/core/test_message_bus.py`

**Step 1: Write the failing test**

Create `tests/core/test_message_bus.py`:

```python
"""Tests for Redis Streams message bus."""

import pytest

from pm_arb.core.message_bus import MessageBus


@pytest.mark.asyncio
async def test_publish_and_consume(redis_client) -> None:
    """Should publish message and consume it from stream."""
    bus = MessageBus(redis_client)
    channel = "test.channel"

    # Publish a message
    message_id = await bus.publish(channel, {"type": "test", "value": 42})
    assert message_id is not None

    # Consume the message
    messages = await bus.consume(channel, count=1)
    assert len(messages) == 1
    assert messages[0]["type"] == "test"
    assert messages[0]["value"] == "42"  # Redis returns strings


@pytest.mark.asyncio
async def test_consumer_group(redis_client) -> None:
    """Should support consumer groups for competing consumers."""
    bus = MessageBus(redis_client)
    channel = "test.group.channel"
    group = "test-group"

    # Create consumer group
    await bus.create_consumer_group(channel, group)

    # Publish messages
    await bus.publish(channel, {"msg": "one"})
    await bus.publish(channel, {"msg": "two"})

    # Consume as group member
    messages = await bus.consume_group(channel, group, "consumer-1", count=2)
    assert len(messages) == 2

    # Acknowledge them
    for msg_id, _ in messages:
        await bus.ack(channel, group, msg_id)


@pytest.mark.asyncio
async def test_publish_command(redis_client) -> None:
    """Should publish system commands that all agents receive."""
    bus = MessageBus(redis_client)

    # Publish halt command
    await bus.publish_command("HALT_ALL")

    # Check command was published
    messages = await bus.consume("system.commands", count=1)
    assert messages[0]["command"] == "HALT_ALL"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_message_bus.py -v`
Expected: FAIL with "cannot import name 'MessageBus'"

**Step 3: Write minimal implementation**

Create `src/pm_arb/core/message_bus.py`:

```python
"""Redis Streams message bus for agent communication."""

import json
from typing import Any

import redis.asyncio as redis


class MessageBus:
    """Wrapper around Redis Streams for pub/sub messaging."""

    def __init__(self, client: redis.Redis) -> None:
        """Initialize with Redis client."""
        self._client = client

    async def publish(self, channel: str, data: dict[str, Any]) -> str:
        """Publish message to a stream. Returns message ID."""
        # Serialize nested objects as JSON strings
        flat_data = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in data.items()}
        message_id = await self._client.xadd(channel, flat_data)
        return message_id

    async def consume(
        self,
        channel: str,
        count: int = 10,
        last_id: str = "0",
    ) -> list[dict[str, Any]]:
        """Read messages from stream (simple read, not consumer group)."""
        results = await self._client.xread({channel: last_id}, count=count, block=1000)

        messages = []
        for _, entries in results:
            for _, data in entries:
                messages.append(data)
        return messages

    async def create_consumer_group(
        self,
        channel: str,
        group: str,
        start_id: str = "0",
    ) -> None:
        """Create consumer group for competing consumers."""
        try:
            await self._client.xgroup_create(channel, group, id=start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def consume_group(
        self,
        channel: str,
        group: str,
        consumer: str,
        count: int = 10,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Read messages as part of consumer group. Returns (id, data) tuples."""
        results = await self._client.xreadgroup(
            group,
            consumer,
            {channel: ">"},
            count=count,
            block=1000,
        )

        messages = []
        for _, entries in results:
            for msg_id, data in entries:
                messages.append((msg_id, data))
        return messages

    async def ack(self, channel: str, group: str, message_id: str) -> None:
        """Acknowledge message processing in consumer group."""
        await self._client.xack(channel, group, message_id)

    async def publish_command(self, command: str, **kwargs: Any) -> str:
        """Publish system command (halt, pause, resume)."""
        data = {"command": command, **kwargs}
        return await self.publish("system.commands", data)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_message_bus.py -v`
Expected: PASS (assuming Redis is running via docker-compose)

**Step 5: Commit**

```bash
git add src/pm_arb/core/message_bus.py tests/core/test_message_bus.py
git commit -m "feat: add Redis Streams message bus wrapper"
```

---

### Task 1.6: Base Agent Class

**Files:**
- Create: `src/pm_arb/agents/base.py`
- Create: `tests/agents/__init__.py`
- Create: `tests/agents/test_base.py`

**Step 1: Write the failing test**

Create `tests/agents/__init__.py` (empty)

Create `tests/agents/test_base.py`:

```python
"""Tests for base agent class."""

import asyncio

import pytest

from pm_arb.agents.base import BaseAgent


class TestAgent(BaseAgent):
    """Concrete test implementation."""

    name = "test-agent"

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url)
        self.messages_processed: list[dict] = []

    async def handle_message(self, channel: str, data: dict) -> None:
        """Record received messages."""
        self.messages_processed.append({"channel": channel, "data": data})

    def get_subscriptions(self) -> list[str]:
        """Subscribe to test channel."""
        return ["test.input"]


@pytest.mark.asyncio
async def test_agent_starts_and_stops() -> None:
    """Agent should start, run, and stop cleanly."""
    agent = TestAgent("redis://localhost:6379")

    # Start agent in background
    task = asyncio.create_task(agent.run())

    # Give it time to start
    await asyncio.sleep(0.1)
    assert agent.is_running

    # Stop it
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert not agent.is_running


@pytest.mark.asyncio
async def test_agent_responds_to_halt_command() -> None:
    """Agent should stop when HALT_ALL command received."""
    agent = TestAgent("redis://localhost:6379")

    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.1)

    # Send halt command
    await agent._bus.publish_command("HALT_ALL")

    # Agent should stop
    await asyncio.wait_for(task, timeout=2.0)
    assert not agent.is_running
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_base.py -v`
Expected: FAIL with "cannot import name 'BaseAgent'"

**Step 3: Write minimal implementation**

Create `src/pm_arb/agents/base.py`:

```python
"""Base agent class for all system agents."""

import asyncio
from abc import ABC, abstractmethod

import redis.asyncio as redis
import structlog

from pm_arb.core.message_bus import MessageBus

logger = structlog.get_logger()


class BaseAgent(ABC):
    """Abstract base class for all agents."""

    name: str = "base-agent"

    def __init__(self, redis_url: str) -> None:
        """Initialize agent with Redis connection."""
        self._redis_url = redis_url
        self._client: redis.Redis | None = None
        self._bus: MessageBus | None = None
        self._running = False
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        """Check if agent is currently running."""
        return self._running

    @abstractmethod
    async def handle_message(self, channel: str, data: dict) -> None:
        """Process a message from subscribed channel. Implement in subclass."""
        ...

    @abstractmethod
    def get_subscriptions(self) -> list[str]:
        """Return list of channels this agent subscribes to. Implement in subclass."""
        ...

    async def run(self) -> None:
        """Main agent loop. Start processing messages."""
        self._client = redis.from_url(self._redis_url, decode_responses=True)
        self._bus = MessageBus(self._client)
        self._running = True
        self._stop_event.clear()

        log = logger.bind(agent=self.name)
        log.info("agent_started")

        try:
            # Create consumer group for this agent's subscriptions
            subscriptions = self.get_subscriptions()
            for channel in subscriptions:
                await self._bus.create_consumer_group(channel, f"{self.name}-group")

            # Also listen for system commands
            await self._bus.create_consumer_group("system.commands", f"{self.name}-group")

            while self._running:
                # Check for stop signal
                if self._stop_event.is_set():
                    break

                # Check system commands first
                await self._check_system_commands()

                # Process subscribed channels
                for channel in subscriptions:
                    await self._process_channel(channel)

                # Small delay to prevent tight loop
                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            log.info("agent_cancelled")
        finally:
            self._running = False
            if self._client:
                await self._client.aclose()
            log.info("agent_stopped")

    async def stop(self) -> None:
        """Signal agent to stop."""
        self._stop_event.set()
        self._running = False

    async def _check_system_commands(self) -> None:
        """Check for system-wide commands (halt, pause, etc.)."""
        messages = await self._bus.consume_group(
            "system.commands",
            f"{self.name}-group",
            self.name,
            count=10,
        )

        for msg_id, data in messages:
            command = data.get("command", "")
            if command == "HALT_ALL":
                logger.info("halt_command_received", agent=self.name)
                await self.stop()
            await self._bus.ack("system.commands", f"{self.name}-group", msg_id)

    async def _process_channel(self, channel: str) -> None:
        """Process messages from a single channel."""
        messages = await self._bus.consume_group(
            channel,
            f"{self.name}-group",
            self.name,
            count=10,
        )

        for msg_id, data in messages:
            try:
                await self.handle_message(channel, data)
            except Exception as e:
                logger.error("message_processing_error", agent=self.name, error=str(e))
            finally:
                await self._bus.ack(channel, f"{self.name}-group", msg_id)

    async def publish(self, channel: str, data: dict) -> str:
        """Publish message to a channel."""
        return await self._bus.publish(channel, data)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/base.py tests/agents/
git commit -m "feat: add base agent class with message handling"
```

---

### Task 1.7: Pydantic Models for Core Entities

**Files:**
- Create: `src/pm_arb/core/models.py`
- Create: `tests/core/test_models.py`

**Step 1: Write the failing test**

Create `tests/core/test_models.py`:

```python
"""Tests for core domain models."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from pm_arb.core.models import (
    Market,
    Opportunity,
    OpportunityType,
    Position,
    Side,
    Trade,
    TradeRequest,
    TradeStatus,
)


def test_market_creation() -> None:
    """Should create Market with required fields."""
    market = Market(
        id="polymarket:btc-up-15m",
        venue="polymarket",
        external_id="abc123",
        title="BTC up in next 15 minutes",
        yes_price=Decimal("0.45"),
        no_price=Decimal("0.55"),
    )

    assert market.venue == "polymarket"
    assert market.yes_price == Decimal("0.45")


def test_opportunity_creation() -> None:
    """Should create Opportunity with classification."""
    opp = Opportunity(
        id="opp-001",
        type=OpportunityType.ORACLE_LAG,
        markets=["polymarket:btc-up-15m"],
        oracle_value=Decimal("65000"),
        signal_strength=Decimal("0.85"),
        detected_at=datetime.now(UTC),
    )

    assert opp.type == OpportunityType.ORACLE_LAG
    assert opp.signal_strength == Decimal("0.85")


def test_trade_request_creation() -> None:
    """Should create TradeRequest for risk evaluation."""
    request = TradeRequest(
        id="req-001",
        opportunity_id="opp-001",
        strategy="oracle-sniper",
        market_id="polymarket:btc-up-15m",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("10.00"),
        max_price=Decimal("0.50"),
    )

    assert request.strategy == "oracle-sniper"
    assert request.side == Side.BUY
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_models.py -v`
Expected: FAIL with "cannot import name 'Market'"

**Step 3: Write minimal implementation**

Create `src/pm_arb/core/models.py`:

```python
"""Core domain models for the arbitrage system."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class Side(str, Enum):
    """Trade side."""

    BUY = "buy"
    SELL = "sell"


class OpportunityType(str, Enum):
    """Classification of arbitrage opportunity."""

    CROSS_PLATFORM = "cross_platform"  # Same event, different prices
    ORACLE_LAG = "oracle_lag"  # PM lags real-world data
    TEMPORAL = "temporal"  # One platform reacts slower
    MISPRICING = "mispricing"  # Internal inconsistency


class TradeStatus(str, Enum):
    """Status of a trade through its lifecycle."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Market(BaseModel):
    """A prediction market on a venue."""

    id: str  # Internal ID: "{venue}:{slug}"
    venue: str  # polymarket, kalshi, etc.
    external_id: str  # Venue's native ID
    title: str
    description: str = ""
    yes_price: Decimal
    no_price: Decimal
    volume_24h: Decimal = Decimal("0")
    liquidity: Decimal = Decimal("0")
    end_date: datetime | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OracleData(BaseModel):
    """Real-world data from an oracle source."""

    source: str  # binance, openweather, etc.
    symbol: str  # BTC, Miami-temp, etc.
    value: Decimal
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = Field(default_factory=dict)


class Opportunity(BaseModel):
    """A detected arbitrage opportunity."""

    id: str
    type: OpportunityType
    markets: list[str]  # Market IDs involved
    oracle_source: str | None = None
    oracle_value: Decimal | None = None
    expected_edge: Decimal = Decimal("0")  # Expected profit %
    signal_strength: Decimal  # Confidence 0-1
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    metadata: dict = Field(default_factory=dict)


class TradeRequest(BaseModel):
    """Request from strategy to execute a trade."""

    id: str
    opportunity_id: str
    strategy: str  # Strategy name that generated this
    market_id: str
    side: Side
    outcome: str  # YES or NO
    amount: Decimal  # In dollars
    max_price: Decimal  # Max price willing to pay
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RiskDecision(BaseModel):
    """Risk Guardian's decision on a trade request."""

    request_id: str
    approved: bool
    reason: str
    rule_triggered: str | None = None  # Which rule caused rejection
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Trade(BaseModel):
    """An executed trade."""

    id: str
    request_id: str
    market_id: str
    venue: str
    side: Side
    outcome: str
    amount: Decimal
    price: Decimal
    fees: Decimal = Decimal("0")
    status: TradeStatus
    external_id: str | None = None  # Venue's trade ID
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    filled_at: datetime | None = None


class Position(BaseModel):
    """Current position in a market."""

    id: str
    market_id: str
    venue: str
    outcome: str  # YES or NO
    quantity: Decimal
    avg_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StrategyPerformance(BaseModel):
    """Performance metrics for a strategy."""

    strategy: str
    period_start: datetime
    period_end: datetime
    trades: int
    wins: int
    losses: int
    total_pnl: Decimal
    sharpe_ratio: Decimal | None = None
    max_drawdown: Decimal | None = None
    allocation_pct: Decimal  # Current capital allocation
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/core/models.py tests/core/test_models.py
git commit -m "feat: add core domain models (Market, Opportunity, Trade, etc.)"
```

---

### Task 1.8: Sprint 1 Integration Test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_sprint1.py`

**Step 1: Write integration test**

Create `tests/integration/__init__.py` (empty)

Create `tests/integration/test_sprint1.py`:

```python
"""Integration test for Sprint 1: Foundation."""

import asyncio

import pytest

from pm_arb.agents.base import BaseAgent
from pm_arb.core.message_bus import MessageBus


class EchoAgent(BaseAgent):
    """Test agent that echoes messages to output channel."""

    name = "echo-agent"

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url)
        self.received: list[dict] = []

    async def handle_message(self, channel: str, data: dict) -> None:
        """Echo message to output channel."""
        self.received.append(data)
        await self.publish("test.output", {"echoed": data.get("value", "")})

    def get_subscriptions(self) -> list[str]:
        return ["test.input"]


class CollectorAgent(BaseAgent):
    """Test agent that collects messages."""

    name = "collector-agent"

    def __init__(self, redis_url: str) -> None:
        super().__init__(redis_url)
        self.collected: list[dict] = []

    async def handle_message(self, channel: str, data: dict) -> None:
        """Collect message."""
        self.collected.append(data)

    def get_subscriptions(self) -> list[str]:
        return ["test.output"]


@pytest.mark.asyncio
async def test_two_agents_communicate() -> None:
    """Two agents should communicate via message bus."""
    redis_url = "redis://localhost:6379"

    echo = EchoAgent(redis_url)
    collector = CollectorAgent(redis_url)

    # Start both agents
    echo_task = asyncio.create_task(echo.run())
    collector_task = asyncio.create_task(collector.run())

    # Wait for agents to initialize
    await asyncio.sleep(0.2)

    # Publish test message
    await echo.publish("test.input", {"value": "hello"})

    # Wait for message to flow through
    await asyncio.sleep(0.5)

    # Verify echo agent received input
    assert len(echo.received) == 1
    assert echo.received[0]["value"] == "hello"

    # Verify collector received echoed output
    assert len(collector.collected) == 1
    assert collector.collected[0]["echoed"] == "hello"

    # Clean shutdown
    await echo.stop()
    await collector.stop()
    await asyncio.wait_for(echo_task, timeout=2.0)
    await asyncio.wait_for(collector_task, timeout=2.0)
```

**Step 2: Run integration test**

Run: `docker-compose up -d`  (ensure Redis is running)
Run: `pytest tests/integration/test_sprint1.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/integration/
git commit -m "test: add Sprint 1 integration test - two agents communicate"
```

---

### Task 1.9: Run All Tests & Lint

**Step 1: Run full test suite**

Run: `pytest tests/ -v --cov=src/pm_arb`
Expected: All tests pass

**Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: No errors (or fix any issues)

Run: `ruff format src/ tests/`
Expected: Files formatted

**Step 3: Run type checker**

Run: `mypy src/`
Expected: No errors (or fix any issues)

**Step 4: Final commit for Sprint 1**

```bash
git add -A
git commit -m "chore: Sprint 1 complete - foundation with tests passing"
```

---

## Sprint 1 Complete

**Demo steps:**
1. `docker-compose up -d`
2. `pip install -e ".[dev]"`
3. `pytest tests/ -v`
4. All tests pass - agents can communicate via Redis Streams

**What we built:**
- Project structure with pyproject.toml
- Docker Compose for Redis + PostgreSQL
- Configuration module (pydantic-settings)
- Redis Streams message bus wrapper
- Base agent class with pub/sub
- Core domain models
- Integration test proving agent communication

---

## Sprint 2: First Venue + Oracle

**Goal:** Stream live prices from Polymarket and Binance.

**Demo:** Run system, see real BTC prices and Polymarket crypto market odds in logs.

---

### Task 2.1: Venue Adapter Base Class

**Files:**
- Create: `src/pm_arb/adapters/venues/base.py`
- Create: `tests/adapters/__init__.py`
- Create: `tests/adapters/venues/__init__.py`
- Create: `tests/adapters/venues/test_base.py`

**Step 1: Write the failing test**

```python
"""Tests for venue adapter base class."""

import pytest

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import Market


class MockVenueAdapter(VenueAdapter):
    """Mock implementation for testing."""

    name = "mock-venue"

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_markets(self) -> list[Market]:
        return []

    async def subscribe_prices(self, market_ids: list[str]) -> None:
        pass


@pytest.mark.asyncio
async def test_adapter_connects() -> None:
    """Adapter should track connection state."""
    adapter = MockVenueAdapter()

    assert not adapter.is_connected
    await adapter.connect()
    assert adapter.is_connected
    await adapter.disconnect()
    assert not adapter.is_connected
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/venues/test_base.py -v`
Expected: FAIL

**Step 3: Write implementation**

Create `src/pm_arb/adapters/venues/base.py`:

```python
"""Base class for venue adapters."""

from abc import ABC, abstractmethod
from decimal import Decimal

from pm_arb.core.models import Market, Trade, TradeRequest


class VenueAdapter(ABC):
    """Abstract base for prediction market venue adapters."""

    name: str = "base-venue"

    def __init__(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to venue."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to venue."""
        ...

    @abstractmethod
    async def get_markets(self) -> list[Market]:
        """Fetch all active markets."""
        ...

    @abstractmethod
    async def subscribe_prices(self, market_ids: list[str]) -> None:
        """Subscribe to price updates for markets."""
        ...

    async def place_order(
        self,
        request: TradeRequest,
    ) -> Trade:
        """Place an order. Override in subclass for live trading."""
        raise NotImplementedError(f"{self.name} does not support order placement")

    async def get_balance(self) -> Decimal:
        """Get account balance. Override in subclass."""
        raise NotImplementedError(f"{self.name} does not support balance queries")
```

**Step 4: Run test**

Run: `pytest tests/adapters/venues/test_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/adapters/venues/base.py tests/adapters/
git commit -m "feat: add venue adapter base class"
```

---

### Task 2.2: Polymarket Adapter

**Files:**
- Create: `src/pm_arb/adapters/venues/polymarket.py`
- Create: `tests/adapters/venues/test_polymarket.py`

**Step 1: Write the failing test**

```python
"""Tests for Polymarket adapter."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter


@pytest.mark.asyncio
async def test_get_markets_parses_response() -> None:
    """Should parse Polymarket API response into Market objects."""
    mock_response = {
        "data": [
            {
                "id": "0x123",
                "question": "Will BTC be above $70k?",
                "description": "Resolves YES if...",
                "outcomes": ["Yes", "No"],
                "outcomePrices": ["0.45", "0.55"],
                "volume24hr": "10000",
                "liquidity": "50000",
            }
        ]
    }

    adapter = PolymarketAdapter()

    with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response["data"]
        markets = await adapter.get_markets()

    assert len(markets) == 1
    assert markets[0].venue == "polymarket"
    assert markets[0].yes_price == Decimal("0.45")
    assert markets[0].title == "Will BTC be above $70k?"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/venues/test_polymarket.py -v`
Expected: FAIL

**Step 3: Write implementation**

Create `src/pm_arb/adapters/venues/polymarket.py`:

```python
"""Polymarket venue adapter."""

from decimal import Decimal

import httpx
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import Market

logger = structlog.get_logger()

# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class PolymarketAdapter(VenueAdapter):
    """Adapter for Polymarket prediction market."""

    name = "polymarket"

    def __init__(self, api_key: str = "", private_key: str = "") -> None:
        super().__init__()
        self._api_key = api_key
        self._private_key = private_key
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._connected = True
        logger.info("polymarket_connected")

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("polymarket_disconnected")

    async def get_markets(self) -> list[Market]:
        """Fetch active markets from Polymarket."""
        raw_markets = await self._fetch_markets()
        return [self._parse_market(m) for m in raw_markets]

    async def _fetch_markets(self) -> list[dict]:
        """Fetch raw market data from API."""
        if not self._client:
            raise RuntimeError("Not connected")

        # Fetch active markets
        response = await self._client.get(
            f"{GAMMA_API}/markets",
            params={"active": "true", "limit": 100},
        )
        response.raise_for_status()
        return response.json()

    def _parse_market(self, data: dict) -> Market:
        """Parse API response into Market model."""
        prices = data.get("outcomePrices", ["0.5", "0.5"])
        yes_price = Decimal(str(prices[0])) if prices else Decimal("0.5")
        no_price = Decimal(str(prices[1])) if len(prices) > 1 else Decimal("0.5")

        return Market(
            id=f"polymarket:{data['id']}",
            venue="polymarket",
            external_id=data["id"],
            title=data.get("question", ""),
            description=data.get("description", ""),
            yes_price=yes_price,
            no_price=no_price,
            volume_24h=Decimal(str(data.get("volume24hr", 0))),
            liquidity=Decimal(str(data.get("liquidity", 0))),
        )

    async def subscribe_prices(self, market_ids: list[str]) -> None:
        """Subscribe to price updates (polling for now)."""
        # TODO: Implement WebSocket subscription when available
        logger.info("polymarket_price_subscription", markets=len(market_ids))

    async def get_crypto_markets(self) -> list[Market]:
        """Fetch specifically crypto-related markets (BTC up/down, etc.)."""
        markets = await self.get_markets()
        crypto_keywords = ["btc", "bitcoin", "eth", "ethereum", "sol", "solana", "crypto"]
        return [
            m for m in markets
            if any(kw in m.title.lower() for kw in crypto_keywords)
        ]
```

**Step 4: Run test**

Run: `pytest tests/adapters/venues/test_polymarket.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/adapters/venues/polymarket.py tests/adapters/venues/test_polymarket.py
git commit -m "feat: add Polymarket venue adapter"
```

---

### Task 2.3: Oracle Adapter Base Class

**Files:**
- Create: `src/pm_arb/adapters/oracles/base.py`
- Create: `tests/adapters/oracles/__init__.py`
- Create: `tests/adapters/oracles/test_base.py`

**Step 1: Write the failing test**

```python
"""Tests for oracle adapter base class."""

import pytest

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData


class MockOracle(OracleAdapter):
    """Mock oracle for testing."""

    name = "mock-oracle"

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def subscribe(self, symbols: list[str]) -> None:
        pass

    async def get_current(self, symbol: str) -> OracleData | None:
        return None


@pytest.mark.asyncio
async def test_oracle_connection_tracking() -> None:
    """Oracle should track connection state."""
    oracle = MockOracle()

    assert not oracle.is_connected
    await oracle.connect()
    assert oracle.is_connected
```

**Step 2: Write implementation**

Create `src/pm_arb/adapters/oracles/base.py`:

```python
"""Base class for oracle adapters (real-world data sources)."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pm_arb.core.models import OracleData


class OracleAdapter(ABC):
    """Abstract base for real-world data oracles."""

    name: str = "base-oracle"

    def __init__(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to data source."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""
        ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to real-time updates for symbols."""
        ...

    @abstractmethod
    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current value for a symbol."""
        ...

    async def stream(self) -> AsyncIterator[OracleData]:
        """Stream real-time data. Override for websocket sources."""
        raise NotImplementedError(f"{self.name} does not support streaming")
        yield  # Make this a generator
```

**Step 3: Run test and commit**

```bash
pytest tests/adapters/oracles/test_base.py -v
git add src/pm_arb/adapters/oracles/base.py tests/adapters/oracles/
git commit -m "feat: add oracle adapter base class"
```

---

### Task 2.4: Binance Crypto Oracle

**Files:**
- Create: `src/pm_arb/adapters/oracles/crypto.py`
- Create: `tests/adapters/oracles/test_crypto.py`

**Step 1: Write the failing test**

```python
"""Tests for crypto oracle adapter."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from pm_arb.adapters.oracles.crypto import BinanceOracle


@pytest.mark.asyncio
async def test_get_current_price() -> None:
    """Should fetch current BTC price."""
    oracle = BinanceOracle()

    mock_response = {"symbol": "BTCUSDT", "price": "65432.10"}

    with patch.object(oracle, "_fetch_price", new_callable=AsyncMock) as mock:
        mock.return_value = mock_response
        await oracle.connect()
        data = await oracle.get_current("BTC")

    assert data is not None
    assert data.symbol == "BTC"
    assert data.value == Decimal("65432.10")
    assert data.source == "binance"
```

**Step 2: Write implementation**

Create `src/pm_arb/adapters/oracles/crypto.py`:

```python
"""Binance crypto price oracle."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import structlog
import websockets

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData

logger = structlog.get_logger()

BINANCE_REST = "https://api.binance.com/api/v3"
BINANCE_WS = "wss://stream.binance.com:9443/ws"


class BinanceOracle(OracleAdapter):
    """Real-time crypto prices from Binance."""

    name = "binance"

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscribed_symbols: list[str] = []

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)
        self._connected = True
        logger.info("binance_connected")

    async def disconnect(self) -> None:
        """Close connections."""
        if self._client:
            await self._client.aclose()
        if self._ws:
            await self._ws.close()
        self._connected = False
        logger.info("binance_disconnected")

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current price for symbol (e.g., BTC, ETH)."""
        data = await self._fetch_price(symbol)
        if not data:
            return None

        return OracleData(
            source="binance",
            symbol=symbol.upper(),
            value=Decimal(str(data["price"])),
            timestamp=datetime.now(UTC),
        )

    async def _fetch_price(self, symbol: str) -> dict | None:
        """Fetch price from REST API."""
        if not self._client:
            raise RuntimeError("Not connected")

        ticker = f"{symbol.upper()}USDT"
        try:
            response = await self._client.get(
                f"{BINANCE_REST}/ticker/price",
                params={"symbol": ticker},
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error("binance_fetch_error", symbol=symbol, error=str(e))
            return None

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to real-time price updates via WebSocket."""
        self._subscribed_symbols = symbols
        streams = [f"{s.lower()}usdt@ticker" for s in symbols]
        stream_url = f"{BINANCE_WS}/{'/'.join(streams)}"

        self._ws = await websockets.connect(stream_url)
        logger.info("binance_ws_subscribed", symbols=symbols)

    async def stream(self) -> AsyncIterator[OracleData]:
        """Stream real-time price updates."""
        if not self._ws:
            raise RuntimeError("Not subscribed to any symbols")

        async for message in self._ws:
            data = json.loads(message)

            # Extract symbol from stream name (e.g., "btcusdt" -> "BTC")
            symbol = data.get("s", "").replace("USDT", "")

            yield OracleData(
                source="binance",
                symbol=symbol,
                value=Decimal(str(data.get("c", 0))),  # "c" is current price
                timestamp=datetime.now(UTC),
                metadata={
                    "high_24h": data.get("h"),
                    "low_24h": data.get("l"),
                    "volume_24h": data.get("v"),
                },
            )
```

**Step 3: Run test and commit**

```bash
pytest tests/adapters/oracles/test_crypto.py -v
git add src/pm_arb/adapters/oracles/crypto.py tests/adapters/oracles/test_crypto.py
git commit -m "feat: add Binance crypto oracle adapter"
```

---

### Task 2.5: Venue Watcher Agent

**Files:**
- Create: `src/pm_arb/agents/venue_watcher.py`
- Create: `tests/agents/test_venue_watcher.py`

**Step 1: Write the failing test**

```python
"""Tests for Venue Watcher agent."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.agents.venue_watcher import VenueWatcherAgent
from pm_arb.core.models import Market


@pytest.mark.asyncio
async def test_venue_watcher_publishes_prices() -> None:
    """Venue watcher should publish market prices to message bus."""
    mock_adapter = MagicMock()
    mock_adapter.name = "test-venue"
    mock_adapter.connect = AsyncMock()
    mock_adapter.disconnect = AsyncMock()
    mock_adapter.get_markets = AsyncMock(return_value=[
        Market(
            id="test:market1",
            venue="test",
            external_id="m1",
            title="Test Market",
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
        )
    ])

    agent = VenueWatcherAgent(
        redis_url="redis://localhost:6379",
        adapter=mock_adapter,
        poll_interval=0.1,
    )

    # Capture published messages
    published = []
    original_publish = agent.publish
    async def capture_publish(channel, data):
        published.append((channel, data))
        return await original_publish(channel, data)
    agent.publish = capture_publish

    # Run agent briefly
    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.3)
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # Verify prices were published
    price_messages = [p for p in published if "prices" in p[0]]
    assert len(price_messages) > 0
    assert price_messages[0][0] == "venue.test-venue.prices"
```

**Step 2: Write implementation**

Create `src/pm_arb/agents/venue_watcher.py`:

```python
"""Venue Watcher Agent - streams prices from a prediction market venue."""

import asyncio

import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import Market

logger = structlog.get_logger()


class VenueWatcherAgent(BaseAgent):
    """Watches a single venue and publishes price updates."""

    def __init__(
        self,
        redis_url: str,
        adapter: VenueAdapter,
        poll_interval: float = 5.0,
    ) -> None:
        self.name = f"venue-watcher-{adapter.name}"
        super().__init__(redis_url)
        self._adapter = adapter
        self._poll_interval = poll_interval
        self._markets: dict[str, Market] = {}

    def get_subscriptions(self) -> list[str]:
        """No subscriptions - this agent only publishes."""
        return []

    async def handle_message(self, channel: str, data: dict) -> None:
        """No incoming messages to handle."""
        pass

    async def run(self) -> None:
        """Override run to add venue connection."""
        await self._adapter.connect()
        try:
            await super().run()
        finally:
            await self._adapter.disconnect()

    async def _process_channel(self, channel: str) -> None:
        """Override to add polling logic."""
        await self._poll_and_publish()
        await asyncio.sleep(self._poll_interval)

    async def _poll_and_publish(self) -> None:
        """Fetch markets and publish updates."""
        try:
            markets = await self._adapter.get_markets()
            log = logger.bind(agent=self.name, market_count=len(markets))

            for market in markets:
                # Check if price changed
                old = self._markets.get(market.id)
                if old is None or old.yes_price != market.yes_price:
                    await self._publish_price(market)

                self._markets[market.id] = market

            # Also publish market discovery for matcher
            await self._publish_markets(markets)

            log.debug("venue_poll_complete")

        except Exception as e:
            logger.error("venue_poll_error", agent=self.name, error=str(e))

    async def _publish_price(self, market: Market) -> None:
        """Publish price update."""
        await self.publish(
            f"venue.{self._adapter.name}.prices",
            {
                "market_id": market.id,
                "venue": market.venue,
                "title": market.title,
                "yes_price": str(market.yes_price),
                "no_price": str(market.no_price),
                "timestamp": market.last_updated.isoformat(),
            },
        )

    async def _publish_markets(self, markets: list[Market]) -> None:
        """Publish market list for matcher."""
        await self.publish(
            f"venue.{self._adapter.name}.markets",
            {
                "venue": self._adapter.name,
                "market_count": len(markets),
                "markets": [
                    {
                        "id": m.id,
                        "external_id": m.external_id,
                        "title": m.title,
                        "description": m.description,
                    }
                    for m in markets[:50]  # Limit to avoid huge messages
                ],
            },
        )
```

**Step 3: Run test and commit**

```bash
pytest tests/agents/test_venue_watcher.py -v
git add src/pm_arb/agents/venue_watcher.py tests/agents/test_venue_watcher.py
git commit -m "feat: add Venue Watcher agent"
```

---

### Task 2.6: Oracle Agent

**Files:**
- Create: `src/pm_arb/agents/oracle_agent.py`
- Create: `tests/agents/test_oracle_agent.py`

**Step 1: Write the failing test**

```python
"""Tests for Oracle Agent."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.core.models import OracleData


@pytest.mark.asyncio
async def test_oracle_agent_publishes_prices() -> None:
    """Oracle agent should publish real-world data to message bus."""
    mock_oracle = MagicMock()
    mock_oracle.name = "test-oracle"
    mock_oracle.connect = AsyncMock()
    mock_oracle.disconnect = AsyncMock()
    mock_oracle.get_current = AsyncMock(return_value=OracleData(
        source="test",
        symbol="BTC",
        value=Decimal("65000"),
    ))

    agent = OracleAgent(
        redis_url="redis://localhost:6379",
        oracle=mock_oracle,
        symbols=["BTC"],
        poll_interval=0.1,
    )

    published = []
    original_publish = agent.publish
    async def capture_publish(channel, data):
        published.append((channel, data))
        return await original_publish(channel, data)
    agent.publish = capture_publish

    task = asyncio.create_task(agent.run())
    await asyncio.sleep(0.3)
    await agent.stop()
    await asyncio.wait_for(task, timeout=2.0)

    oracle_messages = [p for p in published if "oracle" in p[0]]
    assert len(oracle_messages) > 0
    assert "BTC" in oracle_messages[0][0]
```

**Step 2: Write implementation**

Create `src/pm_arb/agents/oracle_agent.py`:

```python
"""Oracle Agent - streams real-world data from external sources."""

import asyncio

import structlog

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.models import OracleData

logger = structlog.get_logger()


class OracleAgent(BaseAgent):
    """Publishes real-world data from oracle sources."""

    def __init__(
        self,
        redis_url: str,
        oracle: OracleAdapter,
        symbols: list[str],
        poll_interval: float = 1.0,
    ) -> None:
        self.name = f"oracle-{oracle.name}"
        super().__init__(redis_url)
        self._oracle = oracle
        self._symbols = symbols
        self._poll_interval = poll_interval
        self._last_values: dict[str, OracleData] = {}

    def get_subscriptions(self) -> list[str]:
        """No subscriptions - this agent only publishes."""
        return []

    async def handle_message(self, channel: str, data: dict) -> None:
        """No incoming messages to handle."""
        pass

    async def run(self) -> None:
        """Override run to add oracle connection."""
        await self._oracle.connect()
        try:
            await super().run()
        finally:
            await self._oracle.disconnect()

    async def _process_channel(self, channel: str) -> None:
        """Override to add polling logic."""
        await self._poll_and_publish()
        await asyncio.sleep(self._poll_interval)

    async def _poll_and_publish(self) -> None:
        """Fetch current values and publish updates."""
        for symbol in self._symbols:
            try:
                data = await self._oracle.get_current(symbol)
                if data:
                    await self._publish_value(data)
                    self._last_values[symbol] = data
            except Exception as e:
                logger.error(
                    "oracle_poll_error",
                    agent=self.name,
                    symbol=symbol,
                    error=str(e),
                )

    async def _publish_value(self, data: OracleData) -> None:
        """Publish oracle data update."""
        await self.publish(
            f"oracle.{data.source}.{data.symbol}",
            {
                "source": data.source,
                "symbol": data.symbol,
                "value": str(data.value),
                "timestamp": data.timestamp.isoformat(),
                "metadata": data.metadata,
            },
        )
        logger.debug(
            "oracle_published",
            source=data.source,
            symbol=data.symbol,
            value=str(data.value),
        )
```

**Step 3: Run test and commit**

```bash
pytest tests/agents/test_oracle_agent.py -v
git add src/pm_arb/agents/oracle_agent.py tests/agents/test_oracle_agent.py
git commit -m "feat: add Oracle Agent for real-world data streaming"
```

---

### Task 2.7: Sprint 2 Integration Test

**Files:**
- Create: `tests/integration/test_sprint2.py`

**Step 1: Write integration test**

```python
"""Integration test for Sprint 2: Live data streaming."""

import asyncio

import pytest

from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.oracle_agent import OracleAgent
from pm_arb.agents.venue_watcher import VenueWatcherAgent


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_data_streaming() -> None:
    """Stream live data from Polymarket and Binance."""
    redis_url = "redis://localhost:6379"

    # Create adapters
    polymarket = PolymarketAdapter()
    binance = BinanceOracle()

    # Create agents
    venue_agent = VenueWatcherAgent(redis_url, polymarket, poll_interval=2.0)
    oracle_agent = OracleAgent(redis_url, binance, symbols=["BTC", "ETH"], poll_interval=1.0)

    # Capture messages
    venue_messages = []
    oracle_messages = []

    original_venue_publish = venue_agent.publish
    async def capture_venue(channel, data):
        venue_messages.append((channel, data))
        return await original_venue_publish(channel, data)
    venue_agent.publish = capture_venue

    original_oracle_publish = oracle_agent.publish
    async def capture_oracle(channel, data):
        oracle_messages.append((channel, data))
        return await original_oracle_publish(channel, data)
    oracle_agent.publish = capture_oracle

    # Run agents
    venue_task = asyncio.create_task(venue_agent.run())
    oracle_task = asyncio.create_task(oracle_agent.run())

    # Let them run for a few seconds
    await asyncio.sleep(5)

    # Stop agents
    await venue_agent.stop()
    await oracle_agent.stop()
    await asyncio.gather(venue_task, oracle_task, return_exceptions=True)

    # Verify we got data
    print(f"\nVenue messages: {len(venue_messages)}")
    print(f"Oracle messages: {len(oracle_messages)}")

    assert len(oracle_messages) > 0, "Should receive crypto prices"
    # Note: Polymarket may have rate limits, so venue messages are optional in CI
```

**Step 2: Run integration test (requires internet)**

Run: `pytest tests/integration/test_sprint2.py -v -m integration`
Expected: PASS with live data printed

**Step 3: Commit**

```bash
git add tests/integration/test_sprint2.py
git commit -m "test: add Sprint 2 integration test - live data streaming"
```

---

### Task 2.8: Sprint 2 Final Commit

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 2: Lint and format**

Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: Sprint 2 complete - live data from Polymarket and Binance"
```

---

## Sprint 2 Complete

**Demo steps:**
1. `docker-compose up -d`
2. `pytest tests/integration/test_sprint2.py -v -m integration`
3. See live BTC/ETH prices and Polymarket markets in output

**What we built:**
- Venue adapter base class + Polymarket implementation
- Oracle adapter base class + Binance implementation
- Venue Watcher agent (publishes market prices)
- Oracle agent (publishes real-world data)
- Live data streaming integration test

---

## Sprints 3-7: Summary

Due to length constraints, here's the outline for remaining sprints. Each follows the same TDD pattern with bite-sized tasks.

### Sprint 3: Opportunity Scanner
- Task 3.1: Opportunity Scanner agent skeleton
- Task 3.2: Oracle-based opportunity detection (compare PM price to oracle)
- Task 3.3: Cross-platform opportunity detection (compare matched markets)
- Task 3.4: Signal strength calculation
- Task 3.5: Integration test - detect crypto lag opportunity

### Sprint 4: Risk Guardian + Paper Executor
- Task 4.1: Risk Guardian agent with rule engine
- Task 4.2: Position limit rule
- Task 4.3: Drawdown tracking and ratcheting stop
- Task 4.4: Daily loss limit rule
- Task 4.5: Paper Executor agent (logs trades, doesn't execute)
- Task 4.6: Integration test - opportunity → risk check → paper trade

### Sprint 5: Strategy + Capital Allocator
- Task 5.1: Strategy agent base class
- Task 5.2: Oracle Sniper strategy implementation
- Task 5.3: Capital Allocator agent
- Task 5.4: Tournament scoring logic
- Task 5.5: Strategy performance tracking
- Task 5.6: Integration test - end-to-end paper trading flow

### Sprint 6: Dashboard
- Task 6.1: Streamlit app skeleton
- Task 6.2: Portfolio overview page
- Task 6.3: Live positions page
- Task 6.4: Strategy leaderboard
- Task 6.5: Risk monitor page
- Task 6.6: Alert configuration

### Sprint 7: Go Live
- Task 7.1: Real Polymarket order execution
- Task 7.2: Kill switch implementation (CLI + dashboard)
- Task 7.3: Pushover alert integration
- Task 7.4: Railway deployment configuration
- Task 7.5: Production checklist and smoke tests
- Task 7.6: Documentation and runbook

---

## Next Steps

Plan complete and saved to `docs/plans/2026-01-30-implementation-plan.md`.

**Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**
