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


class StrategyAllocation(BaseModel):
    """Current capital allocation for a strategy."""

    strategy: str
    allocation_pct: Decimal
    total_capital: Decimal
    available_capital: Decimal
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
