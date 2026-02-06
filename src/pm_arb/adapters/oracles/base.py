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

    @property
    def supports_streaming(self) -> bool:
        """Whether this oracle supports real-time WebSocket streaming."""
        return False

    async def stream(self) -> AsyncIterator[OracleData]:
        """Stream real-time data. Override for websocket sources."""
        raise NotImplementedError(f"{self.name} does not support streaming")
        yield  # Make this a generator
