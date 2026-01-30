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
