"""Tests for Agent Registry."""

import pytest

from pm_arb.core.registry import AgentRegistry


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Reset registry before and after each test."""
    AgentRegistry.reset_instance()
    yield
    AgentRegistry.reset_instance()


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str) -> None:
        self.name = name


def test_register_and_get_agent() -> None:
    """Should register and retrieve an agent by name."""
    registry = AgentRegistry()
    agent = MockAgent("test-agent")

    registry.register(agent)
    retrieved = registry.get("test-agent")

    assert retrieved is agent


def test_get_unknown_agent_returns_none() -> None:
    """Should return None for unknown agent."""
    registry = AgentRegistry()

    result = registry.get("unknown")

    assert result is None


def test_list_agents() -> None:
    """Should list all registered agent names."""
    registry = AgentRegistry()
    registry.register(MockAgent("agent-a"))
    registry.register(MockAgent("agent-b"))

    names = registry.list_agents()

    assert set(names) == {"agent-a", "agent-b"}


def test_clear_registry() -> None:
    """Should clear all registered agents."""
    registry = AgentRegistry()
    registry.register(MockAgent("agent"))

    registry.clear()

    assert registry.get("agent") is None
    assert registry.list_agents() == []
