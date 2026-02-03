"""Core domain models for the arbitrage system."""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

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


class OrderType(str, Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    """Order lifecycle status."""

    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Market(BaseModel):
    """A prediction market on a venue."""

    id: str  # Internal ID: "{venue}:{slug}"
    venue: str  # polymarket, kalshi, etc.
    external_id: str  # Venue's native ID
    title: str
    description: str = ""
    yes_price: Decimal
    no_price: Decimal
    yes_token_id: str = ""  # CLOB token ID for YES outcome (Polymarket)
    no_token_id: str = ""  # CLOB token ID for NO outcome (Polymarket)
    volume_24h: Decimal = Decimal("0")
    liquidity: Decimal = Decimal("0")
    end_date: datetime | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Outcome(BaseModel):
    """Single outcome in a multi-outcome market."""

    name: str
    price: Decimal
    external_id: str = ""


class MultiOutcomeMarket(BaseModel):
    """A multi-outcome prediction market (e.g., 'Who wins election?')."""

    id: str
    venue: str
    external_id: str
    title: str
    description: str = ""
    outcomes: list[Outcome]
    volume_24h: Decimal = Decimal("0")
    liquidity: Decimal = Decimal("0")
    end_date: datetime | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def price_sum(self) -> Decimal:
        """Sum of all outcome prices."""
        return sum((o.price for o in self.outcomes), start=Decimal("0"))

    @property
    def arbitrage_edge(self) -> Decimal:
        """Potential arbitrage if sum < 1.0."""
        edge = Decimal("1.0") - self.price_sum
        return max(Decimal("0"), edge)


class OracleData(BaseModel):
    """Real-world data from an oracle source."""

    source: str  # binance, openweather, etc.
    symbol: str  # BTC, Miami-temp, etc.
    value: Decimal
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    expected_edge: Decimal = Decimal("0")  # Expected profit percentage
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


class Order(BaseModel):
    """An order placed on a venue."""

    id: str  # Internal ID
    external_id: str  # Venue's order ID
    venue: str
    token_id: str
    side: Side
    order_type: OrderType
    amount: Decimal
    price: Decimal | None = None  # For limit orders
    filled_amount: Decimal = Decimal("0")
    average_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None


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


class StrategyAllocation(BaseModel):
    """Current capital allocation for a strategy."""

    strategy: str
    allocation_pct: Decimal
    total_capital: Decimal
    available_capital: Decimal
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OrderBookLevel(BaseModel):
    """Single level in an order book."""

    price: Decimal
    size: Decimal  # Number of tokens available at this price


class OrderBook(BaseModel):
    """Order book for a market with VWAP calculations."""

    market_id: str
    bids: list[OrderBookLevel] = Field(default_factory=list)  # Sorted high to low
    asks: list[OrderBookLevel] = Field(default_factory=list)  # Sorted low to high
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def best_bid(self) -> Decimal | None:
        """Highest bid price."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        """Lowest ask price."""
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        """Bid-ask spread."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def calculate_buy_vwap(self, amount: Decimal) -> Decimal | None:
        """Calculate volume-weighted average price to buy `amount` tokens.

        Returns None if insufficient liquidity.
        """
        if not self.asks:
            return None

        remaining = amount
        total_cost = Decimal("0")
        total_filled = Decimal("0")

        for level in self.asks:
            fill_size = min(remaining, level.size)
            total_cost += fill_size * level.price
            total_filled += fill_size
            remaining -= fill_size

            if remaining <= 0:
                break

        if remaining > 0:
            return None  # Insufficient liquidity

        return total_cost / total_filled

    def calculate_sell_vwap(self, amount: Decimal) -> Decimal | None:
        """Calculate volume-weighted average price to sell `amount` tokens.

        Returns None if insufficient liquidity.
        """
        if not self.bids:
            return None

        remaining = amount
        total_proceeds = Decimal("0")
        total_filled = Decimal("0")

        for level in self.bids:
            fill_size = min(remaining, level.size)
            total_proceeds += fill_size * level.price
            total_filled += fill_size
            remaining -= fill_size

            if remaining <= 0:
                break

        if remaining > 0:
            return None

        return total_proceeds / total_filled

    def available_liquidity_at_price(self, max_price: Decimal, side: str) -> Decimal:
        """Total tokens available up to max_price.

        Args:
            max_price: Maximum price willing to pay (buy) or minimum to receive (sell)
            side: "buy" or "sell"
        """
        total = Decimal("0")

        if side == "buy":
            for level in self.asks:
                if level.price <= max_price:
                    total += level.size
                else:
                    break
        else:
            for level in self.bids:
                if level.price >= max_price:
                    total += level.size
                else:
                    break

        return total
