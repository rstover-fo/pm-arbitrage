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
