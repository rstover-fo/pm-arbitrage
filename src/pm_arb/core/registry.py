"""Agent Registry - central registry for agent instances."""

from typing import Any, Protocol


class AgentProtocol(Protocol):
    """Protocol for agent interface."""

    name: str


class AgentRegistry:
    """Central registry for agent instances."""

    _instance: "AgentRegistry | None" = None
    _agents: dict[str, Any]

    def __new__(cls) -> "AgentRegistry":
        """Singleton pattern for global registry access."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._agents = {}
        return cls._instance

    def register(self, agent: AgentProtocol) -> None:
        """Register an agent by its name."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> Any | None:
        """Get an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def clear(self) -> None:
        """Clear all registered agents."""
        self._agents.clear()

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for testing."""
        cls._instance = None
