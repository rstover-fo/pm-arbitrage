# Execution Infrastructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable live trade execution on Polymarket with authentication, order placement, fill tracking, and slippage protection.

**Architecture:** Extend PaperExecutor to LiveExecutor with real API calls. Add wallet authentication, order lifecycle management, and slippage guards using VWAP from order books.

**Tech Stack:** Python 3.12, py-clob-client (Polymarket SDK), eth-account for wallet signing, existing pm-arbitrage infrastructure

---

## Sprint Overview

| Task | Deliverable | Validates |
|------|-------------|-----------|
| 1 | Wallet and authentication models | Secure credential storage |
| 2 | Polymarket CLOB client integration | SDK setup and connection |
| 3 | Order placement methods | Create market/limit orders |
| 4 | Order lifecycle tracking | Fills, cancels, status updates |
| 5 | Slippage guard using VWAP | Pre-trade validation |
| 6 | Live executor agent | Replaces paper executor for live mode |
| 7 | Integration test with mocked API | End-to-end order flow |

---

## Task 1: Wallet and Authentication Models

**Files:**
- Create: `src/pm_arb/core/auth.py`
- Create: `tests/core/test_auth.py`

**Step 1: Write the failing test**

Create `tests/core/test_auth.py`:

```python
"""Tests for wallet authentication models."""

import os
from unittest.mock import patch

import pytest

from pm_arb.core.auth import PolymarketCredentials, load_credentials


def test_credentials_from_env() -> None:
    """Should load credentials from environment variables."""
    with patch.dict(os.environ, {
        "POLYMARKET_API_KEY": "test-api-key",
        "POLYMARKET_SECRET": "test-secret",
        "POLYMARKET_PASSPHRASE": "test-passphrase",
        "POLYMARKET_PRIVATE_KEY": "0x1234567890abcdef",
    }):
        creds = load_credentials("polymarket")

    assert creds.api_key == "test-api-key"
    assert creds.secret == "test-secret"
    assert creds.passphrase == "test-passphrase"
    assert creds.private_key == "0x1234567890abcdef"


def test_credentials_validates_private_key() -> None:
    """Should reject invalid private key format."""
    with pytest.raises(ValueError, match="Invalid private key"):
        PolymarketCredentials(
            api_key="test",
            secret="test",
            passphrase="test",
            private_key="not-a-valid-key",
        )


def test_credentials_masks_secrets() -> None:
    """Should not expose secrets in string representation."""
    creds = PolymarketCredentials(
        api_key="test-api-key",
        secret="test-secret",
        passphrase="test-passphrase",
        private_key="0x" + "a" * 64,
    )

    str_repr = str(creds)
    assert "test-secret" not in str_repr
    assert "test-passphrase" not in str_repr
    assert "aaaa" not in str_repr
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_auth.py -v`
Expected: FAIL with "cannot import name 'PolymarketCredentials'"

**Step 3: Write minimal implementation**

Create `src/pm_arb/core/auth.py`:

```python
"""Authentication and credential management for venue APIs."""

import os
import re
from typing import Any

from pydantic import BaseModel, field_validator


class PolymarketCredentials(BaseModel):
    """Credentials for Polymarket CLOB API."""

    api_key: str
    secret: str
    passphrase: str
    private_key: str  # Ethereum private key for signing

    @field_validator("private_key")
    @classmethod
    def validate_private_key(cls, v: str) -> str:
        """Validate private key format."""
        if not re.match(r"^0x[a-fA-F0-9]{64}$", v):
            raise ValueError("Invalid private key format (expected 0x + 64 hex chars)")
        return v

    def __str__(self) -> str:
        """Mask secrets in string representation."""
        return f"PolymarketCredentials(api_key={self.api_key[:8]}...)"

    def __repr__(self) -> str:
        return self.__str__()

    def to_client_args(self) -> dict[str, Any]:
        """Return dict suitable for py-clob-client initialization."""
        return {
            "key": self.api_key,
            "secret": self.secret,
            "passphrase": self.passphrase,
            "private_key": self.private_key,
        }


def load_credentials(venue: str) -> PolymarketCredentials:
    """Load credentials from environment variables.

    Args:
        venue: Venue name (e.g., "polymarket")

    Returns:
        Credentials object for the venue

    Raises:
        ValueError: If required environment variables are missing
    """
    prefix = venue.upper()

    api_key = os.environ.get(f"{prefix}_API_KEY")
    secret = os.environ.get(f"{prefix}_SECRET")
    passphrase = os.environ.get(f"{prefix}_PASSPHRASE")
    private_key = os.environ.get(f"{prefix}_PRIVATE_KEY")

    missing = []
    if not api_key:
        missing.append(f"{prefix}_API_KEY")
    if not secret:
        missing.append(f"{prefix}_SECRET")
    if not passphrase:
        missing.append(f"{prefix}_PASSPHRASE")
    if not private_key:
        missing.append(f"{prefix}_PRIVATE_KEY")

    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    return PolymarketCredentials(
        api_key=api_key,
        secret=secret,
        passphrase=passphrase,
        private_key=private_key,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_auth.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/core/auth.py tests/core/test_auth.py
git commit -m "feat: add wallet and authentication models for Polymarket"
```

---

## Task 2: Polymarket CLOB Client Integration

**Files:**
- Modify: `src/pm_arb/adapters/venues/polymarket.py`
- Create: `tests/adapters/venues/test_polymarket_clob.py`

**Step 1: Write the failing test**

Create `tests/adapters/venues/test_polymarket_clob.py`:

```python
"""Tests for Polymarket CLOB client integration."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    """Create mock credentials for testing."""
    return PolymarketCredentials(
        api_key="test-api-key",
        secret="test-secret",
        passphrase="test-passphrase",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_adapter_connects_with_credentials(mock_credentials: PolymarketCredentials) -> None:
    """Should initialize CLOB client with credentials."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_clob.return_value = mock_instance

        await adapter.connect()

        mock_clob.assert_called_once()
        assert adapter.is_authenticated


@pytest.mark.asyncio
async def test_adapter_get_balance(mock_credentials: PolymarketCredentials) -> None:
    """Should fetch USDC balance from wallet."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_instance.get_balance.return_value = {"USDC": "100.50"}
        mock_clob.return_value = mock_instance

        await adapter.connect()
        balance = await adapter.get_balance()

        assert balance == Decimal("100.50")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/venues/test_polymarket_clob.py -v`
Expected: FAIL (ClobClient not imported, is_authenticated not defined)

**Step 3: Write implementation**

Modify `src/pm_arb/adapters/venues/polymarket.py`:

```python
"""Polymarket venue adapter."""

from decimal import Decimal
from typing import Any

import httpx
import structlog

from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import Market, OrderBook, OrderBookLevel

logger = structlog.get_logger()

# Polymarket API endpoints
GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Optional: Import CLOB client if available
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    HAS_CLOB_CLIENT = True
except ImportError:
    HAS_CLOB_CLIENT = False
    ClobClient = None  # type: ignore[misc, assignment]
    ApiCreds = None  # type: ignore[misc, assignment]


class PolymarketAdapter(VenueAdapter):
    """Adapter for Polymarket prediction market."""

    name = "polymarket"

    def __init__(
        self,
        credentials: PolymarketCredentials | None = None,
        api_key: str = "",
        private_key: str = "",
    ) -> None:
        super().__init__()
        self._credentials = credentials
        self._api_key = api_key
        self._private_key = private_key
        self._client: httpx.AsyncClient | None = None
        self._clob_client: Any = None  # ClobClient instance
        self._is_authenticated = False

    @property
    def is_authenticated(self) -> bool:
        """Whether authenticated for trading."""
        return self._is_authenticated

    async def connect(self) -> None:
        """Initialize HTTP client and optionally CLOB client."""
        self._client = httpx.AsyncClient(timeout=30.0)
        self._connected = True

        # Initialize CLOB client if credentials provided
        if self._credentials and HAS_CLOB_CLIENT:
            try:
                creds = ApiCreds(
                    api_key=self._credentials.api_key,
                    api_secret=self._credentials.secret,
                    api_passphrase=self._credentials.passphrase,
                )
                self._clob_client = ClobClient(
                    host=CLOB_API,
                    chain_id=137,  # Polygon mainnet
                    key=self._credentials.private_key,
                    creds=creds,
                )
                self._is_authenticated = True
                logger.info("polymarket_authenticated")
            except Exception as e:
                logger.error("polymarket_auth_failed", error=str(e))
                self._is_authenticated = False

        logger.info("polymarket_connected", authenticated=self._is_authenticated)

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
        self._clob_client = None
        self._is_authenticated = False
        self._connected = False
        logger.info("polymarket_disconnected")

    async def get_balance(self) -> Decimal:
        """Fetch USDC balance from wallet."""
        if not self._clob_client:
            raise RuntimeError("Not authenticated - credentials required")

        balance_data = self._clob_client.get_balance()
        usdc_balance = balance_data.get("USDC", "0")
        return Decimal(str(usdc_balance))

    # ... rest of existing methods unchanged ...
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/venues/test_polymarket_clob.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/adapters/venues/polymarket.py tests/adapters/venues/test_polymarket_clob.py
git commit -m "feat: add Polymarket CLOB client integration for authenticated trading"
```

---

## Task 3: Order Placement Methods

**Files:**
- Modify: `src/pm_arb/adapters/venues/polymarket.py`
- Modify: `src/pm_arb/core/models.py`
- Create: `tests/adapters/venues/test_order_placement.py`

**Step 1: Write the failing test**

Create `tests/adapters/venues/test_order_placement.py`:

```python
"""Tests for order placement on Polymarket."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import Order, OrderStatus, OrderType, Side


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_place_market_order(mock_credentials: PolymarketCredentials) -> None:
    """Should place market buy order."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-123",
        "status": "MATCHED",
        "filledAmount": "10.0",
        "averagePrice": "0.52",
    }

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_instance.create_and_post_order.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.place_order(
            token_id="token-abc",
            side=Side.BUY,
            amount=Decimal("10"),
            order_type=OrderType.MARKET,
        )

        assert order.external_id == "order-123"
        assert order.status == OrderStatus.FILLED
        assert order.filled_amount == Decimal("10.0")
        assert order.average_price == Decimal("0.52")


@pytest.mark.asyncio
async def test_place_limit_order(mock_credentials: PolymarketCredentials) -> None:
    """Should place limit order at specified price."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-456",
        "status": "LIVE",
        "filledAmount": "0",
    }

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_instance.create_and_post_order.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.place_order(
            token_id="token-abc",
            side=Side.BUY,
            amount=Decimal("10"),
            order_type=OrderType.LIMIT,
            price=Decimal("0.50"),
        )

        assert order.external_id == "order-456"
        assert order.status == OrderStatus.OPEN
        assert order.price == Decimal("0.50")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/venues/test_order_placement.py -v`
Expected: FAIL (Order model not defined, place_order not implemented)

**Step 3: Add Order model**

Add to `src/pm_arb/core/models.py`:

```python
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
```

**Step 4: Add place_order to adapter**

Add to `PolymarketAdapter` in `src/pm_arb/adapters/venues/polymarket.py`:

```python
from pm_arb.core.models import Order, OrderStatus, OrderType, Side

async def place_order(
    self,
    token_id: str,
    side: Side,
    amount: Decimal,
    order_type: OrderType,
    price: Decimal | None = None,
) -> Order:
    """Place an order on Polymarket.

    Args:
        token_id: The condition token ID to trade
        side: BUY or SELL
        amount: Number of tokens
        order_type: MARKET or LIMIT
        price: Required for limit orders

    Returns:
        Order object with status
    """
    if not self._clob_client:
        raise RuntimeError("Not authenticated - credentials required")

    if order_type == OrderType.LIMIT and price is None:
        raise ValueError("Price required for limit orders")

    from uuid import uuid4
    order_id = f"order-{uuid4().hex[:8]}"

    try:
        # Build order params for py-clob-client
        order_args = {
            "token_id": token_id,
            "side": "BUY" if side == Side.BUY else "SELL",
            "size": float(amount),
        }

        if order_type == OrderType.LIMIT:
            order_args["price"] = float(price)  # type: ignore[arg-type]

        # Place order via CLOB client
        response = self._clob_client.create_and_post_order(order_args)

        # Map status
        status_map = {
            "MATCHED": OrderStatus.FILLED,
            "LIVE": OrderStatus.OPEN,
            "PENDING": OrderStatus.PENDING,
            "CANCELLED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
        }

        status = status_map.get(response.get("status", ""), OrderStatus.PENDING)

        return Order(
            id=order_id,
            external_id=response.get("orderID", ""),
            venue=self.name,
            token_id=token_id,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            filled_amount=Decimal(str(response.get("filledAmount", "0"))),
            average_price=Decimal(str(response.get("averagePrice", "0"))) if response.get("averagePrice") else None,
            status=status,
        )

    except Exception as e:
        logger.error("order_placement_failed", error=str(e), token=token_id)
        return Order(
            id=order_id,
            external_id="",
            venue=self.name,
            token_id=token_id,
            side=side,
            order_type=order_type,
            amount=amount,
            price=price,
            status=OrderStatus.REJECTED,
            error_message=str(e),
        )
```

**Step 5: Run test to verify it passes**

Run: `pytest tests/adapters/venues/test_order_placement.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/pm_arb/core/models.py src/pm_arb/adapters/venues/polymarket.py tests/adapters/venues/test_order_placement.py
git commit -m "feat: add order placement methods for Polymarket"
```

---

## Task 4: Order Lifecycle Tracking

**Files:**
- Modify: `src/pm_arb/adapters/venues/polymarket.py`
- Create: `tests/adapters/venues/test_order_lifecycle.py`

**Step 1: Write the failing test**

Create `tests/adapters/venues/test_order_lifecycle.py`:

```python
"""Tests for order lifecycle tracking."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_get_order_status(mock_credentials: PolymarketCredentials) -> None:
    """Should fetch current order status."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = {
        "orderID": "order-123",
        "status": "MATCHED",
        "filledAmount": "8.5",
        "averagePrice": "0.51",
    }

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_instance.get_order.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        order = await adapter.get_order_status("order-123")

        assert order.status == OrderStatus.FILLED
        assert order.filled_amount == Decimal("8.5")


@pytest.mark.asyncio
async def test_cancel_order(mock_credentials: PolymarketCredentials) -> None:
    """Should cancel an open order."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_instance.cancel.return_value = {"success": True}
        mock_clob.return_value = mock_instance

        await adapter.connect()
        success = await adapter.cancel_order("order-123")

        assert success is True
        mock_instance.cancel.assert_called_once_with("order-123")


@pytest.mark.asyncio
async def test_get_open_orders(mock_credentials: PolymarketCredentials) -> None:
    """Should list all open orders."""
    adapter = PolymarketAdapter(credentials=mock_credentials)

    mock_response = [
        {"orderID": "order-1", "status": "LIVE", "filledAmount": "0"},
        {"orderID": "order-2", "status": "LIVE", "filledAmount": "5"},
    ]

    with patch("pm_arb.adapters.venues.polymarket.ClobClient") as mock_clob:
        mock_instance = MagicMock()
        mock_instance.get_orders.return_value = mock_response
        mock_clob.return_value = mock_instance

        await adapter.connect()
        orders = await adapter.get_open_orders()

        assert len(orders) == 2
        assert all(o.status == OrderStatus.OPEN for o in orders)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/venues/test_order_lifecycle.py -v`
Expected: FAIL (methods not implemented)

**Step 3: Add lifecycle methods**

Add to `PolymarketAdapter`:

```python
async def get_order_status(self, order_id: str) -> Order:
    """Fetch current status of an order.

    Args:
        order_id: The venue's order ID

    Returns:
        Order with updated status
    """
    if not self._clob_client:
        raise RuntimeError("Not authenticated")

    response = self._clob_client.get_order(order_id)

    status_map = {
        "MATCHED": OrderStatus.FILLED,
        "LIVE": OrderStatus.OPEN,
        "PENDING": OrderStatus.PENDING,
        "CANCELLED": OrderStatus.CANCELLED,
    }

    return Order(
        id=order_id,
        external_id=response.get("orderID", order_id),
        venue=self.name,
        token_id=response.get("tokenID", ""),
        side=Side.BUY if response.get("side") == "BUY" else Side.SELL,
        order_type=OrderType.LIMIT,  # Assume limit for now
        amount=Decimal(str(response.get("size", "0"))),
        price=Decimal(str(response.get("price", "0"))) if response.get("price") else None,
        filled_amount=Decimal(str(response.get("filledAmount", "0"))),
        average_price=Decimal(str(response.get("averagePrice", "0"))) if response.get("averagePrice") else None,
        status=status_map.get(response.get("status", ""), OrderStatus.PENDING),
    )


async def cancel_order(self, order_id: str) -> bool:
    """Cancel an open order.

    Args:
        order_id: The venue's order ID

    Returns:
        True if cancellation succeeded
    """
    if not self._clob_client:
        raise RuntimeError("Not authenticated")

    try:
        result = self._clob_client.cancel(order_id)
        return result.get("success", False)
    except Exception as e:
        logger.error("order_cancel_failed", order_id=order_id, error=str(e))
        return False


async def get_open_orders(self) -> list[Order]:
    """Get all open orders.

    Returns:
        List of open orders
    """
    if not self._clob_client:
        raise RuntimeError("Not authenticated")

    response = self._clob_client.get_orders()

    orders = []
    for data in response:
        orders.append(Order(
            id=data.get("orderID", ""),
            external_id=data.get("orderID", ""),
            venue=self.name,
            token_id=data.get("tokenID", ""),
            side=Side.BUY if data.get("side") == "BUY" else Side.SELL,
            order_type=OrderType.LIMIT,
            amount=Decimal(str(data.get("size", "0"))),
            price=Decimal(str(data.get("price", "0"))) if data.get("price") else None,
            filled_amount=Decimal(str(data.get("filledAmount", "0"))),
            status=OrderStatus.OPEN,
        ))

    return orders
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/adapters/venues/test_order_lifecycle.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/adapters/venues/polymarket.py tests/adapters/venues/test_order_lifecycle.py
git commit -m "feat: add order lifecycle tracking (status, cancel, list)"
```

---

## Task 5: Slippage Guard Using VWAP

**Files:**
- Modify: `src/pm_arb/agents/risk_guardian.py`
- Modify: `tests/agents/test_risk_guardian.py`

**Step 1: Write the failing test**

Add to `tests/agents/test_risk_guardian.py`:

```python
@pytest.mark.asyncio
async def test_rejects_high_slippage_trade() -> None:
    """Should reject trades where slippage exceeds 50% of edge."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("500"),
    )

    # Create order book with thin liquidity
    order_book = OrderBook(
        market_id="polymarket:test",
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("5")),
            OrderBookLevel(price=Decimal("0.70"), size=Decimal("100")),  # Big price jump
        ],
    )

    # Request to buy 20 tokens with 10% edge
    request = TradeRequest(
        id="req-001",
        opportunity_id="opp-001",
        strategy="test",
        market_id="polymarket:test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("20"),  # Need to go into 2nd level
        max_price=Decimal("0.55"),  # Willing to pay up to 0.55
        expected_edge=Decimal("0.10"),
    )

    decision = await guardian._check_slippage(request, order_book)

    # VWAP = (5*0.50 + 15*0.70) / 20 = 13 / 20 = 0.65
    # Slippage = 0.65 - 0.55 = 0.10 (100% of edge)
    assert decision.approved is False
    assert decision.rule_triggered == "slippage_guard"


@pytest.mark.asyncio
async def test_approves_low_slippage_trade() -> None:
    """Should approve trades with acceptable slippage."""
    guardian = RiskGuardianAgent(
        redis_url="redis://localhost:6379",
        initial_bankroll=Decimal("500"),
    )

    # Deep order book with tight spreads
    order_book = OrderBook(
        market_id="polymarket:test",
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("100")),
            OrderBookLevel(price=Decimal("0.51"), size=Decimal("100")),
        ],
    )

    request = TradeRequest(
        id="req-002",
        opportunity_id="opp-002",
        strategy="test",
        market_id="polymarket:test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("20"),  # Easily fills at first level
        max_price=Decimal("0.55"),
        expected_edge=Decimal("0.10"),
    )

    decision = await guardian._check_slippage(request, order_book)

    # VWAP = 0.50 (all fills at first level)
    # Slippage = 0.50 - 0.55 = -0.05 (negative = better than expected)
    assert decision.approved is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_high_slippage_trade -v`
Expected: FAIL (_check_slippage not defined)

**Step 3: Add slippage check**

Add to `RiskGuardianAgent` in `src/pm_arb/agents/risk_guardian.py`:

```python
from pm_arb.core.models import OrderBook

async def _check_slippage(
    self,
    request: TradeRequest,
    order_book: OrderBook,
) -> RiskDecision:
    """Check if estimated slippage exceeds edge threshold.

    Rejects if slippage > 50% of expected edge.

    Args:
        request: The trade request
        order_book: Current order book for the market

    Returns:
        RiskDecision approving or rejecting the trade
    """
    if request.side == Side.BUY:
        vwap = order_book.calculate_buy_vwap(request.amount)
    else:
        vwap = order_book.calculate_sell_vwap(request.amount)

    if vwap is None:
        return RiskDecision(
            request_id=request.id,
            approved=False,
            reason="Insufficient liquidity for requested amount",
            rule_triggered="slippage_guard",
        )

    # Calculate slippage vs expected price
    slippage = vwap - request.max_price

    # Allow negative slippage (better than expected)
    if slippage <= 0:
        return RiskDecision(
            request_id=request.id,
            approved=True,
            reason="Slippage acceptable (better than expected)",
        )

    # Check if slippage exceeds 50% of edge
    max_allowed_slippage = request.expected_edge * Decimal("0.5")

    if slippage > max_allowed_slippage:
        return RiskDecision(
            request_id=request.id,
            approved=False,
            reason=f"Slippage {slippage} exceeds 50% of edge ({max_allowed_slippage})",
            rule_triggered="slippage_guard",
        )

    return RiskDecision(
        request_id=request.id,
        approved=True,
        reason=f"Slippage {slippage} within acceptable range",
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_risk_guardian.py::test_rejects_high_slippage_trade tests/agents/test_risk_guardian.py::test_approves_low_slippage_trade -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/risk_guardian.py tests/agents/test_risk_guardian.py
git commit -m "feat: add slippage guard using VWAP calculation"
```

---

## Task 6: Live Executor Agent

**Files:**
- Create: `src/pm_arb/agents/live_executor.py`
- Create: `tests/agents/test_live_executor.py`

**Step 1: Write the failing test**

Create `tests/agents/test_live_executor.py`:

```python
"""Tests for Live Executor agent."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus, Side


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_executor_processes_approved_trade(mock_credentials: PolymarketCredentials) -> None:
    """Should execute approved trade via venue adapter."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    # Track published results
    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    # Mock the adapter's place_order
    mock_order_response = MagicMock()
    mock_order_response.external_id = "ext-123"
    mock_order_response.status = OrderStatus.FILLED
    mock_order_response.filled_amount = Decimal("10")
    mock_order_response.average_price = Decimal("0.50")

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.place_order.return_value = mock_order_response
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade({
            "request_id": "req-001",
            "market_id": "polymarket:test-market",
            "token_id": "token-abc",
            "side": "buy",
            "amount": "10",
            "max_price": "0.55",
        })

    # Should publish trade result
    assert len(results) == 1
    assert results[0][0] == "trade.results"
    assert results[0][1]["request_id"] == "req-001"
    assert results[0][1]["status"] == "filled"


@pytest.mark.asyncio
async def test_executor_reports_failure(mock_credentials: PolymarketCredentials) -> None:
    """Should report when trade execution fails."""
    executor = LiveExecutorAgent(
        redis_url="redis://localhost:6379",
        credentials={"polymarket": mock_credentials},
    )

    results: list[tuple[str, dict[str, Any]]] = []

    async def capture_publish(channel: str, data: dict[str, Any]) -> str:
        results.append((channel, data))
        return "msg-id"

    executor.publish = capture_publish  # type: ignore[method-assign]

    mock_order_response = MagicMock()
    mock_order_response.status = OrderStatus.REJECTED
    mock_order_response.error_message = "Insufficient balance"

    with patch.object(executor, "_get_adapter") as mock_get_adapter:
        mock_adapter = AsyncMock()
        mock_adapter.place_order.return_value = mock_order_response
        mock_get_adapter.return_value = mock_adapter

        await executor._execute_trade({
            "request_id": "req-002",
            "market_id": "polymarket:test",
            "token_id": "token-xyz",
            "side": "buy",
            "amount": "100",
            "max_price": "0.50",
        })

    assert len(results) == 1
    assert results[0][1]["status"] == "rejected"
    assert "Insufficient balance" in results[0][1]["error"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/agents/test_live_executor.py -v`
Expected: FAIL (LiveExecutorAgent not defined)

**Step 3: Write implementation**

Create `src/pm_arb/agents/live_executor.py`:

```python
"""Live Executor Agent - executes real trades on venues."""

from decimal import Decimal
from typing import Any

import structlog

from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.agents.base import BaseAgent
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus, OrderType, Side

logger = structlog.get_logger()


class LiveExecutorAgent(BaseAgent):
    """Executes real trades via venue adapters."""

    def __init__(
        self,
        redis_url: str,
        credentials: dict[str, PolymarketCredentials],
    ) -> None:
        self.name = "live-executor"
        super().__init__(redis_url)
        self._credentials = credentials
        self._adapters: dict[str, PolymarketAdapter] = {}

    def get_subscriptions(self) -> list[str]:
        """Subscribe to approved trade decisions."""
        return ["trade.approved"]

    async def handle_message(self, channel: str, data: dict[str, Any]) -> None:
        """Execute approved trades."""
        if channel == "trade.approved":
            await self._execute_trade(data)

    def _get_adapter(self, venue: str) -> PolymarketAdapter:
        """Get or create adapter for venue."""
        if venue not in self._adapters:
            if venue not in self._credentials:
                raise ValueError(f"No credentials for venue: {venue}")
            self._adapters[venue] = PolymarketAdapter(
                credentials=self._credentials[venue]
            )
        return self._adapters[venue]

    async def _execute_trade(self, data: dict[str, Any]) -> None:
        """Execute a single trade.

        Args:
            data: Trade request data including market_id, side, amount, etc.
        """
        request_id = data.get("request_id", "unknown")
        market_id = data.get("market_id", "")

        # Extract venue from market_id (format: "venue:external_id")
        venue = market_id.split(":")[0] if ":" in market_id else "polymarket"

        logger.info(
            "executing_trade",
            request_id=request_id,
            market_id=market_id,
            venue=venue,
        )

        try:
            adapter = self._get_adapter(venue)

            if not adapter.is_connected:
                await adapter.connect()

            # Place the order
            side = Side.BUY if data.get("side", "").lower() == "buy" else Side.SELL
            amount = Decimal(str(data.get("amount", "0")))
            max_price = Decimal(str(data.get("max_price", "1")))
            token_id = data.get("token_id", "")

            order = await adapter.place_order(
                token_id=token_id,
                side=side,
                amount=amount,
                order_type=OrderType.MARKET,  # Market orders for now
            )

            # Publish result
            await self._publish_result(
                request_id=request_id,
                order=order,
            )

        except Exception as e:
            logger.error(
                "trade_execution_failed",
                request_id=request_id,
                error=str(e),
            )
            await self._publish_failure(request_id, str(e))

    async def _publish_result(
        self,
        request_id: str,
        order: Any,
    ) -> None:
        """Publish trade execution result."""
        status_map = {
            OrderStatus.FILLED: "filled",
            OrderStatus.PARTIALLY_FILLED: "partial",
            OrderStatus.OPEN: "open",
            OrderStatus.REJECTED: "rejected",
            OrderStatus.CANCELLED: "cancelled",
        }

        result = {
            "request_id": request_id,
            "order_id": order.external_id,
            "status": status_map.get(order.status, "unknown"),
            "filled_amount": str(order.filled_amount),
            "average_price": str(order.average_price) if order.average_price else None,
            "error": order.error_message,
        }

        await self.publish("trade.results", result)

        logger.info(
            "trade_result_published",
            request_id=request_id,
            status=result["status"],
        )

    async def _publish_failure(self, request_id: str, error: str) -> None:
        """Publish trade execution failure."""
        await self.publish(
            "trade.results",
            {
                "request_id": request_id,
                "status": "rejected",
                "error": error,
            },
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/agents/test_live_executor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/pm_arb/agents/live_executor.py tests/agents/test_live_executor.py
git commit -m "feat: add LiveExecutor agent for real trade execution"
```

---

## Task 7: Integration Test with Mocked API

**Files:**
- Create: `tests/integration/test_execution_flow.py`

**Step 1: Write integration test**

Create `tests/integration/test_execution_flow.py`:

```python
"""Integration test for execution flow."""

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.live_executor import LiveExecutorAgent
from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.agents.risk_guardian import RiskGuardianAgent
from pm_arb.core.auth import PolymarketCredentials
from pm_arb.core.models import OrderStatus, Side


@pytest.fixture
def mock_credentials() -> PolymarketCredentials:
    return PolymarketCredentials(
        api_key="test",
        secret="test",
        passphrase="test",
        private_key="0x" + "a" * 64,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_execution_flow(mock_credentials: PolymarketCredentials) -> None:
    """Full flow: detect opportunity → risk check → execute trade."""
    redis_url = "redis://localhost:6379"

    # Create agents
    scanner = OpportunityScannerAgent(
        redis_url=redis_url,
        venue_channels=["venue.test.prices"],
        oracle_channels=[],
        min_edge_pct=Decimal("0.05"),
        min_signal_strength=Decimal("0.01"),
    )

    guardian = RiskGuardianAgent(
        redis_url=redis_url,
        initial_bankroll=Decimal("500"),
        min_profit_threshold=Decimal("0.05"),
    )

    executor = LiveExecutorAgent(
        redis_url=redis_url,
        credentials={"polymarket": mock_credentials},
    )

    # Track messages through the system
    opportunities: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    async def capture_scanner(channel: str, data: dict[str, Any]) -> str:
        if channel == "opportunities.detected":
            opportunities.append(data)
        return "msg-id"

    async def capture_guardian(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.decisions":
            decisions.append(data)
        return "msg-id"

    async def capture_executor(channel: str, data: dict[str, Any]) -> str:
        if channel == "trade.results":
            results.append(data)
        return "msg-id"

    scanner.publish = capture_scanner  # type: ignore[method-assign]
    guardian.publish = capture_guardian  # type: ignore[method-assign]
    executor.publish = capture_executor  # type: ignore[method-assign]

    # Mock order execution
    mock_order = MagicMock()
    mock_order.external_id = "order-123"
    mock_order.status = OrderStatus.FILLED
    mock_order.filled_amount = Decimal("10")
    mock_order.average_price = Decimal("0.45")
    mock_order.error_message = None

    # Step 1: Detect opportunity (mispriced market)
    await scanner._handle_venue_price(
        "venue.test.prices",
        {
            "market_id": "polymarket:arb-test",
            "venue": "polymarket",
            "title": "Test Market",
            "yes_price": "0.40",
            "no_price": "0.50",  # Sum = 0.90, 10% edge
        },
    )

    assert len(opportunities) == 1
    opp = opportunities[0]
    assert opp["type"] == "mispricing"
    assert Decimal(opp["expected_edge"]) == Decimal("0.10")

    # Step 2: Risk check passes
    from pm_arb.core.models import TradeRequest

    trade_request = TradeRequest(
        id="req-001",
        opportunity_id=opp["id"],
        strategy="test",
        market_id="polymarket:arb-test",
        side=Side.BUY,
        outcome="YES",
        amount=Decimal("10"),
        max_price=Decimal("0.45"),
        expected_edge=Decimal("0.10"),
    )

    decision = await guardian._check_rules(trade_request)
    assert decision.approved is True

    # Step 3: Execute trade
    with patch.object(executor, "_get_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.is_connected = True
        mock_adapter.place_order.return_value = mock_order
        mock_get.return_value = mock_adapter

        await executor._execute_trade({
            "request_id": "req-001",
            "market_id": "polymarket:arb-test",
            "token_id": "token-yes",
            "side": "buy",
            "amount": "10",
            "max_price": "0.45",
        })

    # Verify result
    assert len(results) == 1
    assert results[0]["status"] == "filled"
    assert results[0]["filled_amount"] == "10"
```

**Step 2: Run integration test**

Run: `pytest tests/integration/test_execution_flow.py -v -m integration`
Expected: PASS

**Step 3: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/integration`
Run: `ruff check src/ tests/ --fix && ruff format src/ tests/`
Run: `mypy src/`

**Step 4: Commit**

```bash
git add tests/integration/test_execution_flow.py
git commit -m "test: add integration test for execution flow"
```

---

## Summary

**What we built:**
1. Wallet and authentication models for secure credential storage
2. Polymarket CLOB client integration for authenticated trading
3. Order placement methods (market and limit orders)
4. Order lifecycle tracking (status, cancel, list open)
5. Slippage guard using VWAP from order books
6. LiveExecutor agent that replaces PaperExecutor for live mode
7. Integration test covering full detection → risk → execution flow

**Next steps after this sprint:**
- Add Kalshi adapter with similar capabilities
- Implement position synchronization (reconcile local state with venue)
- Add retry logic for transient failures
- Build position unwinding for risk halt scenarios
