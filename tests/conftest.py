"""Shared pytest fixtures."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as redis

from pm_arb.core.config import settings


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: requires external services")
    config.addinivalue_line("markers", "slow: takes >5 seconds")


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


@pytest.fixture
def redis_url() -> str:
    """Provide Redis URL for tests."""
    return "redis://localhost:6379"


@pytest_asyncio.fixture
async def test_db_pool() -> AsyncGenerator[asyncpg.Pool, None]:
    """Create a test database pool with clean state."""
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=5,
    )

    # Initialize schema
    schema_path = Path(__file__).parent.parent / "src/pm_arb/db/schema.sql"
    schema_sql = schema_path.read_text()
    async with pool.acquire() as conn:
        await conn.execute(schema_sql)

    yield pool

    # Clean up test data
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM paper_trades")

    await pool.close()
