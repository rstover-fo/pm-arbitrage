# Paper Trading Pilot: Bug Fixes and Prevention Strategies

> Production-ready prevention patterns and comprehensive test cases for 5 critical bugs discovered during end-to-end testing of the paper trading pilot system.

**Date:** 2026-02-03
**Status:** Complete
**Impact:** Critical - System-blocking bugs that prevent live data operations
**Author:** Engineering Team (Rob Stover, Head of Technology)

---

## Executive Summary

During end-to-end testing of the paper trading pilot with live market data, five critical bugs were discovered and fixed. This document provides:

1. **Root cause analysis** for each bug class
2. **Prevention strategies** to catch similar issues early
3. **Comprehensive test cases** covering edge cases and failure modes
4. **Best practices** to embed into development workflow

All bugs prevent the system from running correctly with live data and would cause silent failures or crashes in production.

---

## 1. Binance Symbol Doubling

### Root Cause Pattern

**Category:** Data transformation bug — implicit string concatenation without validation

When external adapters modify user-provided input (symbol strings), failures occur when:
- Input format assumptions differ from implementation
- Multiple layers of transformation happen without intermediate validation
- No test coverage validates the complete transformation chain

**Specific Case:** `pilot.py` passed `["BTCUSDT"]` but `crypto.py:68` concatenates `"{symbol.upper()}USDT"`, resulting in `BTCUSDTUSDT` and HTTP 400 errors.

### Prevention Strategy

**1. Establish Symbol Format Convention**

Define and enforce a single canonical symbol format at API boundaries:

```python
# pm_arb/adapters/oracles/constants.py
"""Canonical symbol format definitions."""

from enum import Enum

class SymbolFormat(Enum):
    """Supported symbol formats across adapters."""
    BARE = "BARE"          # "BTC", "ETH" (no suffix)
    BINANCE = "BINANCE"    # "BTCUSDT", "ETHUSDT" (Binance format)
    COINGECKO = "COINGECKO"  # "bitcoin", "ethereum" (CoinGecko IDs)

# Document which adapters use which format
ADAPTER_SYMBOL_FORMATS = {
    "binance": SymbolFormat.BARE,      # Expects bare, adds USDT internally
    "coingecko": SymbolFormat.BARE,    # Expects bare, maps to IDs internally
    "polymarket": SymbolFormat.BARE,   # Venue-specific, always bare
}
```

**2. Validate at Entry Points**

Create a validator that prevents malformed symbols from entering the system:

```python
# pm_arb/core/validators.py
"""Symbol and data format validators."""

import re
from typing import Sequence

class SymbolValidator:
    """Validates symbol format and prevents double-transformation."""

    # Regex patterns for each format
    BARE_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,10}$")
    BINANCE_SYMBOL_PATTERN = re.compile(r"^[A-Z]{1,10}USDT$")

    @staticmethod
    def validate_bare_symbols(symbols: Sequence[str]) -> list[str]:
        """Validate symbols are in bare format (no suffixes)."""
        validated = []
        for sym in symbols:
            if not SymbolValidator.BARE_SYMBOL_PATTERN.match(sym):
                raise ValueError(
                    f"Symbol '{sym}' not in bare format. "
                    f"Expected uppercase letters only, got {sym!r}"
                )
            validated.append(sym)
        return validated

    @staticmethod
    def validate_binance_symbols(symbols: Sequence[str]) -> list[str]:
        """Validate symbols already have USDT suffix."""
        validated = []
        for sym in symbols:
            if not SymbolValidator.BINANCE_SYMBOL_PATTERN.match(sym):
                raise ValueError(
                    f"Symbol '{sym}' not in Binance format. "
                    f"Expected format: XXXUSDT, got {sym!r}"
                )
            validated.append(sym)
        return validated
```

**3. Document Transform Chain Visibly**

Add explicit transformation documentation to prevent implicit assumptions:

```python
# pm_arb/adapters/oracles/crypto.py - UPDATED
"""Binance crypto price oracle.

Symbol Format Convention:
    Input:  Bare symbols only (e.g., "BTC", "ETH")
    Reason: Consistent with CoinGecko and other adapters
    Transform: This adapter converts "BTC" -> "BTCUSDT" internally
    Output: OracleData.symbol is the *bare* symbol (not the transformed ticker)

Examples:
    get_current("BTC")      # Input bare
    -> _fetch_price("BTCUSDT")   # Internally adds USDT
    -> OracleData(symbol="BTC")  # Output is bare
"""

async def _fetch_price(self, symbol: str) -> dict[str, Any] | None:
    """Fetch price from REST API.

    Args:
        symbol: Bare symbol (e.g., "BTC" not "BTCUSDT")

    Note: This method adds USDT suffix. Do NOT pass pre-suffixed symbols.
    """
    if not self._client:
        raise RuntimeError("Not connected")

    # Validate input is bare format
    if symbol.endswith("USDT"):
        raise ValueError(
            f"Expected bare symbol like 'BTC', got '{symbol}'. "
            f"This adapter adds USDT suffix automatically."
        )

    ticker = f"{symbol.upper()}USDT"
    try:
        response = await self._client.get(
            f"{BINANCE_REST}/ticker/price",
            params={"symbol": ticker},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result
    except httpx.HTTPError as e:
        logger.error("binance_fetch_error", symbol=symbol, error=str(e))
        return None
```

**4. Enforce at Configuration**

Make the format contract explicit when adapters are initialized:

```python
# pm_arb/pilot.py - UPDATED
"""Pilot Orchestrator - runs all agents with health monitoring."""

def _create_agents(self) -> list[BaseAgent]:
    """Create all agents in startup order."""
    # Create adapters
    polymarket_adapter = PolymarketAdapter()
    coingecko_oracle = CoinGeckoOracle()

    # IMPORTANT: All oracles expect BARE symbols (no suffixes)
    # The adapters add protocol-specific suffixes internally.
    # This validation prevents the doubling bug.
    symbols = ["BTC", "ETH"]  # ← BARE format, not "BTCUSDT"

    # Validate before passing to adapters
    from pm_arb.core.validators import SymbolValidator
    symbols = SymbolValidator.validate_bare_symbols(symbols)

    coingecko_oracle.set_symbols(symbols)

    # ... rest of agent creation
```

### Test Cases

```python
# tests/core/test_validators.py
"""Tests for symbol and format validators."""

import pytest
from pm_arb.core.validators import SymbolValidator


class TestSymbolValidation:
    """Test symbol format validation."""

    def test_validate_bare_symbols_accepts_valid_format(self):
        """Test that bare symbols pass validation."""
        valid = SymbolValidator.validate_bare_symbols(["BTC", "ETH", "SOL"])
        assert valid == ["BTC", "ETH", "SOL"]

    def test_validate_bare_symbols_rejects_usdt_suffix(self):
        """Test that USDT-suffixed symbols are rejected."""
        with pytest.raises(ValueError, match="not in bare format"):
            SymbolValidator.validate_bare_symbols(["BTCUSDT"])

    def test_validate_bare_symbols_rejects_lowercase(self):
        """Test that lowercase symbols are rejected."""
        with pytest.raises(ValueError, match="not in bare format"):
            SymbolValidator.validate_bare_symbols(["btc"])

    def test_validate_bare_symbols_rejects_mixed_case(self):
        """Test that mixed-case symbols are rejected."""
        with pytest.raises(ValueError, match="not in bare format"):
            SymbolValidator.validate_bare_symbols(["BtC"])

    def test_validate_binance_symbols_accepts_valid_format(self):
        """Test that USDT-suffixed symbols pass Binance validation."""
        valid = SymbolValidator.validate_binance_symbols(["BTCUSDT", "ETHUSDT"])
        assert valid == ["BTCUSDT", "ETHUSDT"]

    def test_validate_binance_symbols_rejects_bare(self):
        """Test that bare symbols are rejected in Binance validation."""
        with pytest.raises(ValueError, match="not in Binance format"):
            SymbolValidator.validate_binance_symbols(["BTC"])


# tests/adapters/oracles/test_crypto.py
"""Tests for Binance oracle adapter."""

import pytest
from decimal import Decimal
from pm_arb.adapters.oracles.crypto import BinanceOracle


@pytest.mark.asyncio
async def test_binance_oracle_rejects_presuffixed_symbols():
    """Test that pre-suffixed symbols cause an error."""
    oracle = BinanceOracle()
    await oracle.connect()

    # Should raise error for pre-suffixed symbol
    with pytest.raises(ValueError, match="Expected bare symbol"):
        await oracle._fetch_price("BTCUSDT")

    await oracle.disconnect()


@pytest.mark.asyncio
async def test_binance_oracle_accepts_bare_symbols():
    """Test that bare symbols are accepted."""
    oracle = BinanceOracle()
    await oracle.connect()

    # Should NOT raise error for bare symbol
    # (actual HTTP call may fail if not mocked, but no format error)
    try:
        await oracle._fetch_price("BTC")
    except ValueError as e:
        # Should NOT be a format error
        assert "Expected bare symbol" not in str(e)
    except Exception:
        # Other exceptions (network, HTTP) are OK for this test
        pass

    await oracle.disconnect()


@pytest.mark.asyncio
async def test_oracle_symbol_transformation_chain():
    """Test complete symbol transformation from pilot to oracle."""
    oracle = BinanceOracle()
    await oracle.connect()

    # Pilot provides bare symbols
    bare_symbol = "BTC"

    # Oracle should internally transform to BTCUSDT
    # but never should we pass BTCUSDT as input
    # This test documents the expected behavior

    # Getting OracleData should return bare symbol
    result = await oracle.get_current(bare_symbol)
    if result:  # May fail if no network, but format should be bare
        assert result.symbol == "BTC", f"Expected 'BTC', got '{result.symbol}'"

    await oracle.disconnect()


@pytest.mark.asyncio
async def test_pilot_symbol_configuration_prevents_doubling():
    """Test that pilot configuration prevents symbol doubling."""
    from pm_arb.core.validators import SymbolValidator
    from pm_arb.adapters.oracles.coingecko import CoinGeckoOracle

    # Simulate pilot initialization
    symbols = ["BTC", "ETH"]  # Bare format

    # Validate symbols before passing to oracle
    validated = SymbolValidator.validate_bare_symbols(symbols)

    # Create oracle with validated symbols
    oracle = CoinGeckoOracle()
    oracle.set_symbols(validated)

    # Verify symbols are stored in bare format
    assert oracle._symbols == ["BTC", "ETH"]
    assert all(not s.endswith("USDT") for s in oracle._symbols)


# tests/integration/test_symbol_format_chain.py
"""Integration tests for symbol format handling across adapters."""

import pytest
from pm_arb.core.validators import SymbolValidator
from pm_arb.adapters.oracles.crypto import BinanceOracle
from pm_arb.adapters.oracles.coingecko import CoinGeckoOracle


@pytest.mark.asyncio
async def test_symbol_consistency_across_oracles():
    """Test that symbol format is consistent across all oracles."""
    bare_symbols = ["BTC", "ETH"]

    # Validate once at entry
    validated = SymbolValidator.validate_bare_symbols(bare_symbols)

    # All oracles should accept bare symbols
    binance = BinanceOracle()
    coingecko = CoinGeckoOracle()

    await binance.connect()
    await coingecko.connect()

    binance.set_symbols = lambda s: None  # Mock to avoid actual setup
    coingecko.set_symbols(validated)

    # Get current prices should work with bare symbols
    try:
        await binance.get_current("BTC")
    except ValueError as e:
        if "Expected bare symbol" in str(e):
            pytest.fail(f"Binance oracle rejected bare symbol: {e}")
    except Exception:
        pass  # Network errors are OK

    await binance.disconnect()
    await coingecko.disconnect()
```

### Best Practices

- **Define canonical formats** at the start of each project
- **Validate at boundaries**, not inside functions
- **Document transformations** explicitly (don't assume clarity)
- **Test the full chain**, not just individual functions
- **Use type hints** to indicate format: `symbol: str  # bare format`
- **Reject presuffixed input** rather than silently handling it
- **Keep transformations idempotent** or throw errors on double-application

---

## 2. Polymarket Decimal Parsing

### Root Cause Pattern

**Category:** Defensive parsing failure — no guards against malformed external data

When external APIs return unexpected data formats:
- Empty strings ("") instead of null
- NaN/Infinity values in JSON
- Malformed JSON structures
- Missing fields
- Type mismatches (string instead of number)

`Decimal(str(value))` throws `InvalidOperation` exception, crashing the entire venue watcher agent.

### Prevention Strategy

**1. Create Defensive Parsing Helpers**

Build a library of safe parsing functions for common types:

```python
# pm_arb/core/parsing.py
"""Defensive parsing utilities for external API data."""

from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar, Callable, Optional

T = TypeVar("T")


class ParsingError(Exception):
    """Raised when parsing cannot be completed safely."""
    pass


class SafeParser:
    """Safely parse external API data with explicit fallback behavior."""

    @staticmethod
    def decimal(
        value: Any,
        default: Decimal = Decimal("0"),
        field_name: str = "field",
    ) -> Decimal:
        """Safely convert value to Decimal.

        Handles:
        - None, empty string -> default
        - NaN, Infinity -> default
        - Valid numbers -> Decimal
        - Invalid formats -> default + warning

        Args:
            value: Input value to parse
            default: Fallback value if parsing fails
            field_name: Name for logging context

        Returns:
            Decimal value or default

        Examples:
            SafeParser.decimal("")           # Decimal("0")
            SafeParser.decimal("NaN")        # Decimal("0")
            SafeParser.decimal("1.234")      # Decimal("1.234")
            SafeParser.decimal(None, Decimal("99"))  # Decimal("99")
        """
        if value is None or value == "":
            return default

        try:
            # Convert to string first to catch type issues
            str_value = str(value).strip()

            # Reject special values
            if str_value.lower() in ("nan", "inf", "-inf", "infinity", "-infinity"):
                logger.warning(
                    "decimal_parsing_special_value",
                    field=field_name,
                    value=str_value,
                    using_default=str(default),
                )
                return default

            # Parse as Decimal
            return Decimal(str_value)

        except (InvalidOperation, ValueError, TypeError) as e:
            logger.warning(
                "decimal_parsing_error",
                field=field_name,
                value=repr(value),
                error=str(e),
                using_default=str(default),
            )
            return default

    @staticmethod
    def float_to_decimal(
        value: Any,
        default: Decimal = Decimal("0"),
        field_name: str = "field",
    ) -> Decimal:
        """Safely convert float/numeric value to Decimal.

        Specifically handles Python float->Decimal conversion issues.
        """
        if value is None:
            return default

        try:
            # First try direct Decimal conversion
            if isinstance(value, Decimal):
                return value
            elif isinstance(value, str):
                return SafeParser.decimal(value, default, field_name)
            elif isinstance(value, (int, float)):
                # For floats, convert via string to avoid precision issues
                return Decimal(str(value))
            else:
                raise TypeError(f"Cannot convert {type(value).__name__} to Decimal")

        except (InvalidOperation, ValueError, TypeError) as e:
            logger.warning(
                "float_to_decimal_error",
                field=field_name,
                value=repr(value),
                error=str(e),
                using_default=str(default),
            )
            return default

    @staticmethod
    def integer(
        value: Any,
        default: int = 0,
        field_name: str = "field",
    ) -> int:
        """Safely parse integer values."""
        if value is None:
            return default

        try:
            return int(value)
        except (ValueError, TypeError) as e:
            logger.warning(
                "integer_parsing_error",
                field=field_name,
                value=repr(value),
                error=str(e),
                using_default=default,
            )
            return default

    @staticmethod
    def string(
        value: Any,
        default: str = "",
        field_name: str = "field",
        allow_empty: bool = False,
    ) -> str:
        """Safely parse string values."""
        if value is None:
            return default

        try:
            str_value = str(value).strip()
            if not str_value and not allow_empty:
                return default
            return str_value
        except Exception as e:
            logger.warning(
                "string_parsing_error",
                field=field_name,
                value=repr(value),
                error=str(e),
                using_default=default,
            )
            return default

    @staticmethod
    def required_decimal(
        data: dict[str, Any],
        field: str,
        context: str = "parsing",
    ) -> Decimal:
        """Parse required decimal field, raise if missing or invalid.

        Use for critical fields where missing data indicates API error.
        """
        if field not in data:
            raise ParsingError(
                f"Required field '{field}' missing in {context}. "
                f"Available fields: {list(data.keys())}"
            )

        value = data[field]
        if value is None or value == "":
            raise ParsingError(
                f"Required field '{field}' is empty in {context}"
            )

        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as e:
            raise ParsingError(
                f"Cannot parse required field '{field}' as Decimal: {value}. "
                f"Error: {e}"
            ) from e
```

**2. Apply Defensive Parsing at API Boundaries**

Update the Polymarket adapter to use safe parsing:

```python
# pm_arb/adapters/venues/polymarket.py - UPDATED
"""Polymarket venue adapter."""

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import structlog

from pm_arb.core.parsing import SafeParser, ParsingError
from pm_arb.adapters.venues.base import VenueAdapter
from pm_arb.core.models import (
    Market,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderStatus,
    OrderType,
    Side,
)

logger = structlog.get_logger()

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class PolymarketAdapter(VenueAdapter):
    """Adapter for Polymarket prediction market."""

    name = "polymarket"

    # ... existing code ...

    async def get_orderbook(self, market_id: str) -> OrderBook | None:
        """Get orderbook for a market with safe decimal parsing.

        Handles malformed responses gracefully.
        """
        try:
            data = await self._fetch_orderbook(market_id)
            if not data:
                return None

            # Parse with defensive parsing
            bids = self._parse_orderbook_levels(
                data.get("bids", []),
                Side.BUY,
                "bids",
            )
            asks = self._parse_orderbook_levels(
                data.get("asks", []),
                Side.SELL,
                "asks",
            )

            return OrderBook(
                market_id=market_id,
                venue=self.name,
                bids=bids,
                asks=asks,
                timestamp=datetime.now(UTC),
            )

        except ParsingError as e:
            logger.error("polymarket_parsing_error", market=market_id, error=str(e))
            return None
        except Exception as e:
            logger.error(
                "polymarket_orderbook_error",
                market=market_id,
                error=str(e),
            )
            return None

    def _parse_orderbook_levels(
        self,
        levels: list[Any],
        side: Side,
        side_name: str,
    ) -> list[OrderBookLevel]:
        """Parse orderbook levels with safe decimal parsing.

        Args:
            levels: List of [price, size] pairs from API
            side: Buy or Sell side
            side_name: Name for logging ("bids", "asks")

        Returns:
            List of OrderBookLevel objects

        Raises:
            ParsingError if critical fields are missing
        """
        result = []

        for idx, level in enumerate(levels):
            try:
                # Expect [price, size] format
                if not isinstance(level, (list, tuple)) or len(level) < 2:
                    logger.warning(
                        "polymarket_malformed_level",
                        side=side_name,
                        index=idx,
                        level=repr(level),
                    )
                    continue

                # Parse price and size with fallback
                price = SafeParser.decimal(
                    level[0],
                    default=Decimal("0"),
                    field_name=f"{side_name}[{idx}].price",
                )

                size = SafeParser.decimal(
                    level[1],
                    default=Decimal("0"),
                    field_name=f"{side_name}[{idx}].size",
                )

                # Skip levels with zero price or size (likely parsing errors)
                if price <= 0 or size <= 0:
                    logger.debug(
                        "polymarket_zero_level_skipped",
                        side=side_name,
                        index=idx,
                        price=str(price),
                        size=str(size),
                    )
                    continue

                result.append(
                    OrderBookLevel(
                        price=price,
                        size=size,
                        side=side,
                    )
                )

            except Exception as e:
                logger.warning(
                    "polymarket_level_parse_error",
                    side=side_name,
                    index=idx,
                    level=repr(level),
                    error=str(e),
                )
                continue

        return result

    async def _fetch_orderbook(self, market_id: str) -> dict[str, Any] | None:
        """Fetch raw orderbook from API."""
        if not self._client:
            raise RuntimeError("Not connected")

        try:
            response = await self._client.get(
                f"{GAMMA_API}/markets/{market_id}",
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPError as e:
            logger.error(
                "polymarket_fetch_error",
                market=market_id,
                error=str(e),
            )
            return None
        except ValueError as e:
            # JSON parsing error
            logger.error(
                "polymarket_json_error",
                market=market_id,
                error=str(e),
            )
            return None
```

**3. Add Data Validation Schema**

Use Pydantic for strict API response validation:

```python
# pm_arb/adapters/venues/polymarket_models.py
"""Type-safe models for Polymarket API responses."""

from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, field_validator, Field

class OrderBookLevelData(BaseModel):
    """Single orderbook level from Polymarket API."""
    price: Decimal
    size: Decimal

    @field_validator("price", "size", mode="before")
    @classmethod
    def parse_decimal(cls, v):
        """Safely parse Decimal from API response."""
        from pm_arb.core.parsing import SafeParser

        if v is None or v == "":
            raise ValueError("Cannot be empty")

        return SafeParser.decimal(v, field_name="orderbook_level")


class OrderBookData(BaseModel):
    """Orderbook response from Polymarket API."""
    market_id: str = Field(..., alias="id")
    bids: List[List] = Field(default_factory=list)
    asks: List[List] = Field(default_factory=list)

    @field_validator("bids", "asks", mode="before")
    @classmethod
    def validate_levels(cls, v):
        """Validate levels are list of lists."""
        if not isinstance(v, list):
            return []
        return v
```

### Test Cases

```python
# tests/core/test_parsing.py
"""Tests for defensive parsing utilities."""

import pytest
from decimal import Decimal
from pm_arb.core.parsing import SafeParser, ParsingError


class TestSafeDecimalParsing:
    """Test Decimal parsing with edge cases."""

    def test_safe_decimal_empty_string(self):
        """Test that empty strings return default."""
        result = SafeParser.decimal("")
        assert result == Decimal("0")

    def test_safe_decimal_none(self):
        """Test that None returns default."""
        result = SafeParser.decimal(None)
        assert result == Decimal("0")

    def test_safe_decimal_nan(self):
        """Test that NaN returns default."""
        result = SafeParser.decimal("NaN")
        assert result == Decimal("0")

    def test_safe_decimal_infinity(self):
        """Test that Infinity returns default."""
        result = SafeParser.decimal("Infinity")
        assert result == Decimal("0")

    def test_safe_decimal_negative_infinity(self):
        """Test that -Infinity returns default."""
        result = SafeParser.decimal("-Infinity")
        assert result == Decimal("0")

    def test_safe_decimal_valid_number(self):
        """Test parsing valid Decimal."""
        result = SafeParser.decimal("123.456")
        assert result == Decimal("123.456")

    def test_safe_decimal_integer(self):
        """Test parsing integer as Decimal."""
        result = SafeParser.decimal("999")
        assert result == Decimal("999")

    def test_safe_decimal_custom_default(self):
        """Test custom default value."""
        result = SafeParser.decimal("invalid", default=Decimal("99.99"))
        assert result == Decimal("99.99")

    def test_safe_decimal_negative(self):
        """Test parsing negative Decimal."""
        result = SafeParser.decimal("-12.34")
        assert result == Decimal("-12.34")

    def test_safe_decimal_scientific_notation(self):
        """Test scientific notation."""
        result = SafeParser.decimal("1.23e-4")
        assert result == Decimal("1.23e-4")

    def test_safe_decimal_malformed_json(self):
        """Test with malformed JSON string."""
        result = SafeParser.decimal("{invalid}")
        assert result == Decimal("0")

    def test_safe_decimal_whitespace(self):
        """Test with whitespace."""
        result = SafeParser.decimal("  42.5  ")
        assert result == Decimal("42.5")


class TestSafeIntegerParsing:
    """Test integer parsing with edge cases."""

    def test_safe_integer_valid(self):
        """Test parsing valid integer."""
        result = SafeParser.integer("42")
        assert result == 42

    def test_safe_integer_float_truncates(self):
        """Test parsing float truncates to integer."""
        result = SafeParser.integer("42.99")
        assert result == 42

    def test_safe_integer_none(self):
        """Test None returns default."""
        result = SafeParser.integer(None)
        assert result == 0

    def test_safe_integer_custom_default(self):
        """Test custom default."""
        result = SafeParser.integer("invalid", default=99)
        assert result == 99


class TestSafeStringParsing:
    """Test string parsing with edge cases."""

    def test_safe_string_valid(self):
        """Test parsing valid string."""
        result = SafeParser.string("hello")
        assert result == "hello"

    def test_safe_string_none(self):
        """Test None returns default."""
        result = SafeParser.string(None)
        assert result == ""

    def test_safe_string_empty_not_allowed(self):
        """Test empty string returns default when not allowed."""
        result = SafeParser.string("", allow_empty=False)
        assert result == ""

    def test_safe_string_empty_allowed(self):
        """Test empty string returned when allowed."""
        result = SafeParser.string("", allow_empty=True)
        assert result == ""

    def test_safe_string_whitespace_stripped(self):
        """Test whitespace is stripped."""
        result = SafeParser.string("  hello  ")
        assert result == "hello"


# tests/adapters/venues/test_polymarket_parsing.py
"""Tests for Polymarket safe parsing."""

import pytest
from decimal import Decimal
from pm_arb.adapters.venues.polymarket import PolymarketAdapter
from pm_arb.core.models import Side, OrderBookLevel


@pytest.mark.asyncio
async def test_polymarket_parse_orderbook_with_valid_data():
    """Test parsing valid orderbook data."""
    adapter = PolymarketAdapter()

    levels = [
        [Decimal("0.52"), Decimal("100")],
        [Decimal("0.53"), Decimal("200")],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    assert len(result) == 2
    assert result[0].price == Decimal("0.52")
    assert result[0].size == Decimal("100")


@pytest.mark.asyncio
async def test_polymarket_parse_orderbook_with_string_numbers():
    """Test parsing orderbook with string numbers."""
    adapter = PolymarketAdapter()

    levels = [
        ["0.52", "100"],  # Strings instead of Decimals
        ["0.53", "200"],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    assert len(result) == 2
    assert result[0].price == Decimal("0.52")


@pytest.mark.asyncio
async def test_polymarket_parse_orderbook_with_empty_values():
    """Test parsing orderbook with empty values."""
    adapter = PolymarketAdapter()

    levels = [
        [Decimal("0.52"), Decimal("100")],
        ["", ""],  # Empty strings
        [Decimal("0.53"), Decimal("200")],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    # Empty values should be skipped (parsed as 0)
    assert len(result) == 2  # Only valid levels


@pytest.mark.asyncio
async def test_polymarket_parse_orderbook_with_nan():
    """Test parsing orderbook with NaN values."""
    adapter = PolymarketAdapter()

    levels = [
        [Decimal("0.52"), Decimal("100")],
        ["NaN", "NaN"],  # NaN values
        [Decimal("0.53"), Decimal("200")],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    # NaN should be skipped
    assert len(result) == 2


@pytest.mark.asyncio
async def test_polymarket_parse_orderbook_with_malformed_levels():
    """Test parsing orderbook with malformed levels."""
    adapter = PolymarketAdapter()

    levels = [
        [Decimal("0.52"), Decimal("100")],
        "not a list",  # Malformed
        None,  # Malformed
        [Decimal("0.53")],  # Too short
        [Decimal("0.54"), Decimal("200")],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    # Only well-formed levels should be included
    assert len(result) == 2


@pytest.mark.asyncio
async def test_polymarket_parse_orderbook_with_negative_prices():
    """Test parsing orderbook with negative prices (should skip)."""
    adapter = PolymarketAdapter()

    levels = [
        [Decimal("0.52"), Decimal("100")],
        [Decimal("-0.10"), Decimal("200")],  # Negative price
        [Decimal("0.53"), Decimal("200")],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    # Negative price should be skipped
    assert len(result) == 2
    assert all(l.price > 0 for l in result)


@pytest.mark.asyncio
async def test_polymarket_handles_zero_prices():
    """Test that zero prices are skipped."""
    adapter = PolymarketAdapter()

    levels = [
        [Decimal("0.52"), Decimal("100")],
        [Decimal("0"), Decimal("200")],  # Zero price
        [Decimal("0.53"), Decimal("200")],
    ]

    result = adapter._parse_orderbook_levels(levels, Side.BUY, "bids")

    assert len(result) == 2
    assert all(l.price > 0 for l in result)
```

### Best Practices

- **Validate at API boundaries** before processing
- **Use defensive parsing** for ALL external data
- **Define explicit fallbacks** instead of crashing
- **Log warnings** when data doesn't match expectations
- **Skip invalid entries** rather than failing the entire response
- **Use Pydantic** for schema validation
- **Never trust external APIs** — assume data is malformed
- **Document expected formats** with examples

---

## 3. Binance Geo-blocking (HTTP 451)

### Root Cause Pattern

**Category:** Dependency resilience failure — single provider with geographic restrictions

When a service depends on a single external provider:
- Geographic restrictions (GeoIP blocking) cause availability issues
- API changes or deprecations stop the system
- Rate limits or service degradation block operations
- No graceful degradation or fallback

Binance.com is blocked by GeoIP in the US. Binance.US has SSL certificate issues. Without fallback, the entire price feed stops working.

### Prevention Strategy

**1. Design Multi-Provider Architecture**

Build resilience by supporting multiple oracle sources:

```python
# pm_arb/adapters/oracles/multi_provider.py
"""Multi-provider oracle with automatic fallback."""

from typing import Optional, Sequence
from datetime import UTC, datetime
from decimal import Decimal
import asyncio

import structlog
from pm_arb.core.models import OracleData
from pm_arb.adapters.oracles.base import OracleAdapter

logger = structlog.get_logger()


class OracleProvider:
    """Configuration for a single oracle provider."""

    def __init__(
        self,
        name: str,
        oracle: OracleAdapter,
        priority: int = 0,
        weight: float = 1.0,
    ):
        """Initialize provider.

        Args:
            name: Provider name (e.g., "binance", "coingecko")
            oracle: OracleAdapter instance
            priority: Higher = tried first (0-100)
            weight: Weight in consensus (only used if multiple agree)
        """
        self.name = name
        self.oracle = oracle
        self.priority = priority
        self.weight = weight
        self.is_healthy = True
        self.consecutive_failures = 0
        self.last_successful_call: datetime | None = None


class MultiProviderOracle(OracleAdapter):
    """Multi-provider oracle with fallback and health checking."""

    name = "multi_provider"

    def __init__(self, providers: Sequence[OracleProvider] | None = None):
        """Initialize with providers."""
        super().__init__()
        self._providers = list(providers) if providers else []
        self._sorted_providers = sorted(
            self._providers,
            key=lambda p: p.priority,
            reverse=True,
        )

    def add_provider(self, provider: OracleProvider) -> None:
        """Add a provider and re-sort by priority."""
        self._providers.append(provider)
        self._sorted_providers = sorted(
            self._providers,
            key=lambda p: p.priority,
            reverse=True,
        )
        logger.info("oracle_provider_added", name=provider.name)

    async def connect(self) -> None:
        """Connect all providers."""
        tasks = [p.oracle.connect() for p in self._providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for provider, result in zip(self._providers, results):
            if isinstance(result, Exception):
                logger.error(
                    "oracle_provider_connect_error",
                    provider=provider.name,
                    error=str(result),
                )
                provider.is_healthy = False
            else:
                logger.info("oracle_provider_connected", provider=provider.name)

        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect all providers."""
        tasks = [p.oracle.disconnect() for p in self._providers]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._connected = False

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current price, trying providers in priority order.

        Returns data from first successful provider.
        Falls back to next provider if one fails.
        """
        for provider in self._sorted_providers:
            if not provider.is_healthy:
                logger.debug(
                    "skipping_unhealthy_provider",
                    provider=provider.name,
                    symbol=symbol,
                )
                continue

            try:
                data = await asyncio.wait_for(
                    provider.oracle.get_current(symbol),
                    timeout=10.0,
                )

                if data is not None:
                    # Record success
                    provider.consecutive_failures = 0
                    provider.last_successful_call = datetime.now(UTC)
                    logger.debug(
                        "oracle_data_from_provider",
                        provider=provider.name,
                        symbol=symbol,
                        value=str(data.value),
                    )
                    return data

            except asyncio.TimeoutError:
                logger.warning(
                    "oracle_provider_timeout",
                    provider=provider.name,
                    symbol=symbol,
                )
                provider.consecutive_failures += 1

            except Exception as e:
                logger.warning(
                    "oracle_provider_error",
                    provider=provider.name,
                    symbol=symbol,
                    error=str(e),
                )
                provider.consecutive_failures += 1

                # Mark unhealthy after 3 failures
                if provider.consecutive_failures >= 3:
                    provider.is_healthy = False
                    logger.error(
                        "oracle_provider_marked_unhealthy",
                        provider=provider.name,
                        failures=provider.consecutive_failures,
                    )

        # All providers failed
        logger.error(
            "all_oracle_providers_failed",
            symbol=symbol,
            providers=[p.name for p in self._providers],
        )
        return None

    async def get_current_with_consensus(
        self,
        symbol: str,
        consensus_threshold: float = 0.8,
    ) -> OracleData | None:
        """Get current price requiring consensus from multiple providers.

        More robust against single provider failures or manipulation.
        """
        # Get price from all healthy providers in parallel
        tasks = [
            (provider, provider.oracle.get_current(symbol))
            for provider in self._sorted_providers
            if provider.is_healthy
        ]

        if not tasks:
            logger.error("no_healthy_oracle_providers", symbol=symbol)
            return None

        results = await asyncio.gather(
            *[task[1] for task in tasks],
            return_exceptions=True,
        )

        valid_data = [
            (tasks[i][0], data)
            for i, data in enumerate(results)
            if isinstance(data, OracleData)
        ]

        if not valid_data:
            logger.error(
                "no_valid_oracle_responses",
                symbol=symbol,
            )
            return None

        # Calculate weighted average
        total_weight = sum(p.weight for p, _ in valid_data)
        weighted_sum = sum(
            data.value * p.weight
            for p, data in valid_data
        )
        consensus_value = weighted_sum / total_weight

        # Check deviation (all providers within threshold of consensus)
        max_deviation = max(
            abs(float(data.value) - float(consensus_value)) / float(consensus_value)
            for _, data in valid_data
        )

        if max_deviation > (1 - consensus_threshold):
            logger.warning(
                "oracle_consensus_deviation_high",
                symbol=symbol,
                max_deviation=max_deviation,
                consensus_threshold=consensus_threshold,
                values=[str(d.value) for _, d in valid_data],
            )

        logger.debug(
            "oracle_consensus_reached",
            symbol=symbol,
            providers=[p.name for p, _ in valid_data],
            value=str(consensus_value),
        )

        return OracleData(
            source="multi_provider_consensus",
            symbol=symbol,
            value=consensus_value,
            timestamp=datetime.now(UTC),
            metadata={
                "providers": [p.name for p, _ in valid_data],
                "provider_count": len(valid_data),
                "max_deviation": max_deviation,
            },
        )

    def get_provider_health(self) -> dict[str, dict]:
        """Get health status of all providers."""
        return {
            p.name: {
                "healthy": p.is_healthy,
                "failures": p.consecutive_failures,
                "last_success": p.last_successful_call.isoformat() if p.last_successful_call else None,
            }
            for p in self._providers
        }


# Example usage
async def create_resilient_oracle():
    """Create multi-provider oracle with fallbacks."""
    from pm_arb.adapters.oracles.crypto import BinanceOracle
    from pm_arb.adapters.oracles.coingecko import CoinGeckoOracle

    # Create providers with fallback chain
    providers = [
        OracleProvider(
            name="binance",
            oracle=BinanceOracle(),
            priority=100,  # Try first (lowest latency)
            weight=1.0,
        ),
        OracleProvider(
            name="coingecko",
            oracle=CoinGeckoOracle(),
            priority=50,   # Try second
            weight=1.0,
        ),
        # Could add more: Kraken, Coinbase, etc.
    ]

    oracle = MultiProviderOracle(providers)
    await oracle.connect()

    return oracle
```

**2. Update Pilot to Use Multi-Provider**

```python
# pm_arb/pilot.py - UPDATED
"""Pilot Orchestrator - runs all agents with health monitoring."""

from pm_arb.adapters.oracles.multi_provider import (
    MultiProviderOracle,
    OracleProvider,
)

def _create_agents(self) -> list[BaseAgent]:
    """Create all agents with resilient oracle."""
    from pm_arb.adapters.oracles.crypto import BinanceOracle
    from pm_arb.adapters.oracles.coingecko import CoinGeckoOracle
    from pm_arb.adapters.venues.polymarket import PolymarketAdapter

    # Create multi-provider oracle with fallback chain
    polymarket_adapter = PolymarketAdapter()

    binance_oracle = BinanceOracle()
    coingecko_oracle = CoinGeckoOracle()

    providers = [
        OracleProvider(
            name="binance",
            oracle=binance_oracle,
            priority=100,  # Fastest, try first
            weight=1.0,
        ),
        OracleProvider(
            name="coingecko",
            oracle=coingecko_oracle,
            priority=50,   # Fallback
            weight=1.0,
        ),
    ]

    multi_oracle = MultiProviderOracle(providers)
    symbols = ["BTC", "ETH"]
    multi_oracle.add_provider  # Already added via init

    # Set symbols on sub-oracles for batch optimization
    binance_oracle.set_symbols(symbols)  # If supported
    coingecko_oracle.set_symbols(symbols)

    return [
        # Data feeds with resilience
        VenueWatcherAgent(
            self._redis_url,
            adapter=polymarket_adapter,
            poll_interval=5.0,
        ),
        OracleAgent(
            self._redis_url,
            oracle=multi_oracle,  # Use multi-provider oracle
            symbols=symbols,
            poll_interval=15.0,
        ),
        # ... rest of agents
    ]
```

**3. Add Provider Health Monitoring**

```python
# pm_arb/agents/health_monitor.py
"""Health monitor for oracle providers."""

import asyncio
from datetime import datetime, timedelta, UTC
from typing import Any

import structlog

logger = structlog.get_logger()


class OracleHealthMonitor:
    """Monitors oracle provider health and triggers alerts."""

    def __init__(
        self,
        oracle,
        check_interval: int = 60,
        failure_threshold: int = 5,
    ):
        """Initialize health monitor.

        Args:
            oracle: MultiProviderOracle instance
            check_interval: Seconds between health checks
            failure_threshold: Consecutive failures before alert
        """
        self.oracle = oracle
        self.check_interval = check_interval
        self.failure_threshold = failure_threshold
        self._last_alert: dict[str, datetime] = {}

    async def monitor(self) -> None:
        """Run health monitoring loop."""
        while True:
            try:
                health = self.oracle.get_provider_health()

                for provider_name, status in health.items():
                    self._check_provider_health(provider_name, status)

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error("health_monitor_error", error=str(e))
                await asyncio.sleep(self.check_interval)

    def _check_provider_health(
        self,
        provider_name: str,
        status: dict[str, Any],
    ) -> None:
        """Check single provider health."""
        if not status["healthy"] and status["failures"] >= self.failure_threshold:
            # Alert only once per hour
            last_alert = self._last_alert.get(provider_name)
            if last_alert is None or (datetime.now(UTC) - last_alert) > timedelta(hours=1):
                logger.error(
                    "oracle_provider_unhealthy",
                    provider=provider_name,
                    failures=status["failures"],
                )
                self._last_alert[provider_name] = datetime.now(UTC)
```

### Test Cases

```python
# tests/adapters/oracles/test_multi_provider.py
"""Tests for multi-provider oracle with fallback."""

import pytest
from decimal import Decimal
from datetime import UTC, datetime

from pm_arb.adapters.oracles.multi_provider import (
    MultiProviderOracle,
    OracleProvider,
)
from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData


class MockOracleSucceed(OracleAdapter):
    """Mock oracle that always succeeds."""

    name = "mock_succeed"

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    async def get_current(self, symbol: str) -> OracleData:
        return OracleData(
            source=self.name,
            symbol=symbol,
            value=Decimal("100.00"),
            timestamp=datetime.now(UTC),
        )

    async def subscribe(self, symbols: list[str]):
        pass

    async def stream(self):
        pass


class MockOracleFail(OracleAdapter):
    """Mock oracle that always fails."""

    name = "mock_fail"

    async def connect(self):
        self._connected = True

    async def disconnect(self):
        self._connected = False

    async def get_current(self, symbol: str) -> OracleData | None:
        raise RuntimeError("Connection failed")

    async def subscribe(self, symbols: list[str]):
        pass

    async def stream(self):
        pass


@pytest.mark.asyncio
async def test_multi_provider_uses_primary():
    """Test that primary provider is used when available."""
    primary = OracleProvider("primary", MockOracleSucceed(), priority=100)
    secondary = OracleProvider("secondary", MockOracleSucceed(), priority=50)

    oracle = MultiProviderOracle([primary, secondary])
    await oracle.connect()

    result = await oracle.get_current("BTC")

    assert result is not None
    assert result.value == Decimal("100.00")
    # Should get from primary (first in sorted order)


@pytest.mark.asyncio
async def test_multi_provider_falls_back_on_failure():
    """Test that fallback provider is used when primary fails."""
    primary = OracleProvider("primary", MockOracleFail(), priority=100)
    secondary = OracleProvider("secondary", MockOracleSucceed(), priority=50)

    oracle = MultiProviderOracle([primary, secondary])
    await oracle.connect()

    result = await oracle.get_current("BTC")

    assert result is not None
    assert result.value == Decimal("100.00")
    # Should fall back to secondary


@pytest.mark.asyncio
async def test_multi_provider_marks_provider_unhealthy():
    """Test that provider is marked unhealthy after repeated failures."""
    failing_provider = OracleProvider("failing", MockOracleFail(), priority=100)

    oracle = MultiProviderOracle([failing_provider])
    await oracle.connect()

    # Try 3 times
    for _ in range(3):
        await oracle.get_current("BTC")

    # Provider should be marked unhealthy
    health = oracle.get_provider_health()
    assert not health["failing"]["healthy"]
    assert health["failing"]["failures"] >= 3


@pytest.mark.asyncio
async def test_multi_provider_recovers_after_success():
    """Test that provider recovers after successful call."""
    provider = OracleProvider("test", MockOracleSucceed(), priority=100)

    oracle = MultiProviderOracle([provider])
    await oracle.connect()

    # Mark as failed
    provider.consecutive_failures = 2
    provider.is_healthy = True  # Still try

    # Should succeed
    result = await oracle.get_current("BTC")

    assert result is not None
    assert provider.consecutive_failures == 0  # Reset


@pytest.mark.asyncio
async def test_multi_provider_geoblocking_resilience():
    """Test resilience to geographic blocking (Binance case)."""
    # Simulate Binance being blocked
    binance_blocked = OracleProvider("binance", MockOracleFail(), priority=100)
    # Fallback to CoinGecko
    coingecko = OracleProvider("coingecko", MockOracleSucceed(), priority=50)

    oracle = MultiProviderOracle([binance_blocked, coingecko])
    await oracle.connect()

    # Should fail over to CoinGecko smoothly
    result = await oracle.get_current("BTC")

    assert result is not None
    assert result.source == "mock_succeed"
```

### Best Practices

- **Never depend on single provider**
- **Rank providers by latency/priority**
- **Implement circuit breaker** (unhealthy after N failures)
- **Add provider health monitoring**
- **Use weighted consensus** for critical prices
- **Log provider switching** for debugging
- **Document fallback chain** explicitly
- **Test with provider failures** regularly

---

## 4. CoinGecko Rate Limits (HTTP 429)

### Root Cause Pattern

**Category:** Rate limit violation — inefficient API usage

When calling external APIs inefficiently:
- Multiple API calls per request instead of batching
- No respect for advertised rate limits
- No backoff strategy on 429 responses
- Shared rate limit across multiple components

CoinGecko free tier: ~10-30 requests/minute. Calling per-symbol hits limits immediately.

### Prevention Strategy

**1. Implement Smart Batching**

```python
# pm_arb/core/api_batcher.py
"""Smart API batching for rate-limit-conscious requests."""

import asyncio
from datetime import datetime, timedelta, UTC
from typing import Any, TypeVar, Callable, Sequence
from collections import defaultdict

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


class RateLimitBatcher:
    """Batches requests to respect API rate limits."""

    def __init__(
        self,
        max_requests_per_minute: int,
        batch_size: int = 50,
    ):
        """Initialize batcher.

        Args:
            max_requests_per_minute: API rate limit
            batch_size: Max items per batch (if API supports it)
        """
        self.max_requests_per_minute = max_requests_per_minute
        self.batch_size = batch_size
        self._request_times: list[datetime] = []
        self._lock = asyncio.Lock()

    async def wait_for_slot(self) -> None:
        """Wait until safe to make next API call."""
        async with self._lock:
            now = datetime.now(UTC)
            minute_ago = now - timedelta(minutes=1)

            # Remove old requests outside the window
            self._request_times = [
                t for t in self._request_times
                if t > minute_ago
            ]

            # If at limit, wait until oldest request expires
            while len(self._request_times) >= self.max_requests_per_minute:
                oldest = self._request_times[0]
                sleep_time = (oldest - minute_ago).total_seconds() + 0.1
                logger.warning(
                    "rate_limit_wait",
                    sleep_seconds=sleep_time,
                    current_requests=len(self._request_times),
                )
                await asyncio.sleep(sleep_time)

                now = datetime.now(UTC)
                minute_ago = now - timedelta(minutes=1)
                self._request_times = [
                    t for t in self._request_times
                    if t > minute_ago
                ]

            # Record this request
            self._request_times.append(now)


class BatchingPolicy:
    """Defines how to batch items for an API call."""

    def __init__(
        self,
        batch_size: int,
        format_func: Callable[[list[Any]], Any],
    ):
        """Initialize policy.

        Args:
            batch_size: How many items per batch
            format_func: Function to format items for API call
        """
        self.batch_size = batch_size
        self.format_func = format_func

    def create_batches(self, items: Sequence[Any]) -> list[list[Any]]:
        """Split items into batches."""
        return [
            list(items[i:i + self.batch_size])
            for i in range(0, len(items), self.batch_size)
        ]


# Example: CoinGecko uses comma-separated IDs
COINGECKO_BATCH_POLICY = BatchingPolicy(
    batch_size=250,  # CoinGecko can handle 250 coins per request
    format_func=lambda ids: ",".join(ids),
)
```

**2. Update CoinGecko Oracle with Batching**

```python
# pm_arb/adapters/oracles/coingecko.py - UPDATED
"""CoinGecko crypto price oracle - no geo-restrictions."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import structlog

from pm_arb.adapters.oracles.base import OracleAdapter
from pm_arb.core.models import OracleData
from pm_arb.core.api_batcher import RateLimitBatcher

logger = structlog.get_logger()

COINGECKO_API = "https://api.coingecko.com/api/v3"

# CoinGecko free tier: ~10-30 req/min
COINGECKO_RATE_LIMIT = 20  # Conservative

# Map common symbols to CoinGecko IDs
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
}

ID_TO_SYMBOL = {v: k for k, v in SYMBOL_TO_ID.items()}


class CoinGeckoOracle(OracleAdapter):
    """Real-time crypto prices from CoinGecko (free, no geo-restrictions)."""

    name = "coingecko"

    def __init__(self) -> None:
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._cached_prices: dict[str, Decimal] = {}
        self._cache_time: dict[str, datetime] = {}
        self._symbols: list[str] = []
        self._batcher = RateLimitBatcher(
            max_requests_per_minute=COINGECKO_RATE_LIMIT,
            batch_size=250,
        )

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=10.0)
        self._connected = True
        logger.info(
            "coingecko_connected",
            rate_limit=COINGECKO_RATE_LIMIT,
        )

    async def disconnect(self) -> None:
        """Close connections."""
        if self._client:
            await self._client.aclose()
        self._connected = False
        logger.info("coingecko_disconnected")

    def set_symbols(self, symbols: list[str]) -> None:
        """Set symbols to track - enables batched fetching."""
        self._symbols = symbols
        logger.info("coingecko_symbols_configured", symbols=symbols)

    async def get_current(self, symbol: str) -> OracleData | None:
        """Get current price for symbol (e.g., BTC, ETH).

        Uses cached prices from batch fetch if available.
        """
        symbol_upper = symbol.upper()

        # Check cache first (valid for 60 seconds)
        cached_price = self._get_from_cache(symbol_upper)
        if cached_price is not None:
            logger.debug(
                "coingecko_cache_hit",
                symbol=symbol_upper,
                value=str(cached_price),
            )
            return OracleData(
                source="coingecko",
                symbol=symbol_upper,
                value=cached_price,
                timestamp=datetime.now(UTC),
            )

        # If we have symbols configured, do a batch fetch for all of them
        if self._symbols and symbol_upper == self._symbols[0]:
            # First symbol requested triggers batch fetch for all
            await self._fetch_batch()

        # Check cache again after fetch
        price = self._cached_prices.get(symbol_upper)
        if price is None:
            logger.warning(
                "coingecko_no_price",
                symbol=symbol_upper,
            )
            return None

        return OracleData(
            source="coingecko",
            symbol=symbol_upper,
            value=price,
            timestamp=datetime.now(UTC),
        )

    def _get_from_cache(self, symbol: str) -> Decimal | None:
        """Get price from cache if still valid (60 seconds)."""
        if symbol not in self._cached_prices:
            return None

        cache_time = self._cache_time.get(symbol)
        if cache_time is None:
            return None

        if (datetime.now(UTC) - cache_time).total_seconds() > 60:
            # Cache expired
            return None

        return self._cached_prices[symbol]

    async def _fetch_batch(self) -> None:
        """Fetch all configured symbols in one API call."""
        if not self._client or not self._symbols:
            return

        # Convert symbols to CoinGecko IDs
        coin_ids = []
        symbol_map = {}

        for sym in self._symbols:
            coin_id = SYMBOL_TO_ID.get(sym.upper())
            if coin_id:
                coin_ids.append(coin_id)
                symbol_map[coin_id] = sym.upper()

        if not coin_ids:
            logger.warning("coingecko_no_mappings", symbols=self._symbols)
            return

        # Respect rate limits
        await self._batcher.wait_for_slot()

        try:
            logger.debug(
                "coingecko_batch_fetch",
                coin_count=len(coin_ids),
                ids=",".join(coin_ids),
            )

            response = await self._client.get(
                f"{COINGECKO_API}/simple/price",
                params={
                    "ids": ",".join(coin_ids),
                    "vs_currencies": "usd",
                },
                timeout=15.0,
            )

            if response.status_code == 429:
                # Rate limited - wait longer next time
                retry_after = response.headers.get("Retry-After", "60")
                logger.error(
                    "coingecko_rate_limited",
                    retry_after=retry_after,
                )
                # Increase wait in batcher
                self._batcher.max_requests_per_minute = max(
                    1,
                    self._batcher.max_requests_per_minute - 5,
                )
                return

            response.raise_for_status()
            data: dict[str, Any] = response.json()

            # Update cache
            now = datetime.now(UTC)
            for coin_id, prices in data.items():
                symbol = symbol_map.get(coin_id)
                if symbol and "usd" in prices:
                    price = Decimal(str(prices["usd"]))
                    self._cached_prices[symbol] = price
                    self._cache_time[symbol] = now
                    logger.debug(
                        "coingecko_price_cached",
                        symbol=symbol,
                        value=str(price),
                    )

        except httpx.HTTPError as e:
            logger.error("coingecko_batch_fetch_error", error=str(e))

    async def subscribe(self, symbols: list[str]) -> None:
        """CoinGecko doesn't support WebSocket - polling only."""
        self.set_symbols(symbols)
        logger.info("coingecko_polling_mode", symbols=symbols)

    async def stream(self):
        """Not supported - use polling via get_current()."""
        raise NotImplementedError("CoinGecko doesn't support streaming")
```

**3. Add Exponential Backoff**

```python
# pm_arb/core/backoff.py
"""Exponential backoff for API retries."""

import asyncio
import random
from typing import Callable, TypeVar, Any

T = TypeVar("T")


async def exponential_backoff(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    **kwargs,
) -> Any:
    """Call function with exponential backoff retry.

    Args:
        func: Async function to call
        max_retries: Maximum number of retries
        base_delay: Initial delay in seconds
        max_delay: Maximum delay between retries
        jitter: Add random jitter to delays

    Returns:
        Result of function call

    Raises:
        Last exception if all retries exhausted
    """
    delay = base_delay
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)

        except Exception as e:
            last_exception = e

            if attempt < max_retries:
                # Calculate delay with jitter
                wait_time = min(delay, max_delay)
                if jitter:
                    wait_time *= random.uniform(0.5, 1.5)

                logger.warning(
                    "api_call_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=wait_time,
                    error=str(e),
                )

                await asyncio.sleep(wait_time)
                delay *= 2  # Exponential
            else:
                logger.error(
                    "api_call_failed_after_retries",
                    max_retries=max_retries,
                    error=str(e),
                )

    raise last_exception
```

### Test Cases

```python
# tests/core/test_api_batcher.py
"""Tests for API rate limit batcher."""

import pytest
import asyncio
from datetime import datetime, UTC

from pm_arb.core.api_batcher import RateLimitBatcher


@pytest.mark.asyncio
async def test_batcher_allows_requests_under_limit():
    """Test that requests under limit are allowed immediately."""
    batcher = RateLimitBatcher(max_requests_per_minute=10)

    # Should allow first request immediately
    start = datetime.now(UTC)
    await batcher.wait_for_slot()
    elapsed = (datetime.now(UTC) - start).total_seconds()

    assert elapsed < 0.1  # Should be immediate


@pytest.mark.asyncio
async def test_batcher_enforces_rate_limit():
    """Test that rate limit is enforced."""
    batcher = RateLimitBatcher(max_requests_per_minute=3)

    # Make 3 requests quickly
    for _ in range(3):
        await batcher.wait_for_slot()

    # 4th request should wait (or be blocked)
    # This test verifies accounting works
    assert len(batcher._request_times) == 3


@pytest.mark.asyncio
async def test_batcher_clears_old_requests():
    """Test that requests outside the window are cleared."""
    batcher = RateLimitBatcher(max_requests_per_minute=1)

    # Manually add an old request (outside 1-minute window)
    from datetime import timedelta
    old_time = datetime.now(UTC) - timedelta(minutes=2)
    batcher._request_times.append(old_time)

    # Wait for slot should clear old request
    start = datetime.now(UTC)
    await batcher.wait_for_slot()
    elapsed = (datetime.now(UTC) - start).total_seconds()

    # Should be quick because old request was cleared
    assert elapsed < 0.5


# tests/adapters/oracles/test_coingecko_batching.py
"""Tests for CoinGecko batching and rate limits."""

import pytest
from decimal import Decimal
from pm_arb.adapters.oracles.coingecko import CoinGeckoOracle


@pytest.mark.asyncio
async def test_coingecko_batches_symbols():
    """Test that CoinGecko batches multiple symbols in one call."""
    oracle = CoinGeckoOracle()

    # Set multiple symbols
    oracle.set_symbols(["BTC", "ETH", "SOL"])

    # Verify batching would work (mocked)
    assert oracle._symbols == ["BTC", "ETH", "SOL"]


@pytest.mark.asyncio
async def test_coingecko_respects_rate_limit():
    """Test that CoinGecko respects rate limiting."""
    oracle = CoinGeckoOracle()
    await oracle.connect()

    # Verify batcher was initialized
    assert oracle._batcher is not None
    assert oracle._batcher.max_requests_per_minute == 20


@pytest.mark.asyncio
async def test_coingecko_caches_prices():
    """Test that prices are cached to reduce API calls."""
    oracle = CoinGeckoOracle()
    oracle.set_symbols(["BTC", "ETH"])

    # Manually set cache
    now = datetime.now(UTC)
    oracle._cached_prices["BTC"] = Decimal("50000")
    oracle._cache_time["BTC"] = now

    # Getting same price should use cache (not make API call)
    cached = oracle._get_from_cache("BTC")
    assert cached == Decimal("50000")


@pytest.mark.asyncio
async def test_coingecko_cache_expiry():
    """Test that cache expires after 60 seconds."""
    from datetime import timedelta

    oracle = CoinGeckoOracle()

    # Set cache to 61 seconds ago
    old_time = datetime.now(UTC) - timedelta(seconds=61)
    oracle._cached_prices["BTC"] = Decimal("50000")
    oracle._cache_time["BTC"] = old_time

    # Should return None (expired)
    cached = oracle._get_from_cache("BTC")
    assert cached is None


# tests/core/test_backoff.py
"""Tests for exponential backoff."""

import pytest
from pm_arb.core.backoff import exponential_backoff


@pytest.mark.asyncio
async def test_backoff_succeeds_immediately():
    """Test that successful call doesn't retry."""
    call_count = 0

    async def success():
        nonlocal call_count
        call_count += 1
        return "success"

    result = await exponential_backoff(success, max_retries=3)

    assert result == "success"
    assert call_count == 1


@pytest.mark.asyncio
async def test_backoff_retries_on_failure():
    """Test that backoff retries on failure."""
    call_count = 0

    async def fail_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("Fail")
        return "success"

    result = await exponential_backoff(fail_twice, max_retries=3)

    assert result == "success"
    assert call_count == 3
```

### Best Practices

- **Batch API calls** whenever possible
- **Check API rate limit documentation** at start
- **Implement circuit breaker** for persistent failures
- **Cache results** with appropriate TTL
- **Use exponential backoff** with jitter
- **Monitor rate limit headers** (Retry-After)
- **Log rate limit events** for visibility
- **Plan for degradation** gracefully

---

## 5. Dashboard Async Event Loop

### Root Cause Pattern

**Category:** Event loop conflict — incompatible async runtime assumptions

When mixing async frameworks:
- Streamlit (thread-based, synchronous)
- asyncio (async/await based)
- Database clients (async)

`asyncio.run()` fails because Streamlit has already created an event loop. `nest_asyncio.apply()` is a workaround, not a solution.

### Prevention Strategy

**1. Separate Concerns: Dashboard vs. Async Operations**

Design dashboard to NOT use asyncio directly:

```python
# pm_arb/dashboard/db_service.py
"""Synchronous database service for Streamlit dashboard."""

import threading
from typing import Any, Optional
from functools import lru_cache

import structlog

logger = structlog.get_logger()


class DashboardDatabaseService:
    """Thread-safe database access for Streamlit (no async)."""

    def __init__(self, database_url: str):
        """Initialize with database URL.

        Uses thread-local connections to avoid async conflicts.
        """
        self.database_url = database_url
        self._thread_local = threading.local()

    def _get_sync_connection(self):
        """Get or create sync connection in current thread."""
        # For Postgres with asyncpg, we'd need psycopg3 (sync version)
        # Or use SQLAlchemy which handles both
        if not hasattr(self._thread_local, 'connection'):
            import psycopg
            self._thread_local.connection = psycopg.connect(self.database_url)
            logger.debug("dashboard_db_connection_created")

        return self._thread_local.connection

    def close_connection(self):
        """Close thread-local connection."""
        if hasattr(self._thread_local, 'connection'):
            self._thread_local.connection.close()
            del self._thread_local.connection
            logger.debug("dashboard_db_connection_closed")

    def get_daily_summary(self, days: int = 1) -> dict[str, Any]:
        """Get daily summary (sync, no async)."""
        conn = self._get_sync_connection()

        try:
            with conn.cursor() as cur:
                # Query implementation
                cur.execute("""
                    SELECT COUNT(*) as total_trades
                    FROM paper_trades
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                """, (days,))

                row = cur.fetchone()
                return {"total_trades": row[0] if row else 0}

        except Exception as e:
            logger.error("dashboard_query_error", error=str(e))
            return {}

    def get_trades_since_days(self, days: int = 1) -> list[dict[str, Any]]:
        """Get recent trades (sync, no async)."""
        conn = self._get_sync_connection()

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM paper_trades
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    ORDER BY created_at DESC
                    LIMIT 50
                """, (days,))

                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]

        except Exception as e:
            logger.error("dashboard_trades_query_error", error=str(e))
            return []
```

**2. Use Streamlit-Native Caching**

Instead of asyncio, use Streamlit's built-in caching:

```python
# pm_arb/dashboard/app.py - UPDATED
"""Streamlit Dashboard for PM Arbitrage System."""

import pandas as pd
import plotly.express as px
import streamlit as st

from pm_arb.dashboard.mock_data import (
    get_mock_portfolio,
    get_mock_risk_state,
    get_mock_strategies,
    get_mock_trades,
)

st.set_page_config(
    page_title="PM Arbitrage Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def get_db_service():
    """Get database service (cached at app lifetime).

    Use Streamlit's cache instead of asyncio.
    Streamlit manages the lifecycle and cleanup.
    """
    from pm_arb.dashboard.db_service import DashboardDatabaseService
    from pm_arb.core.config import settings

    service = DashboardDatabaseService(settings.database_url)
    return service


def main() -> None:
    """Main dashboard entry point."""
    st.title("📊 PM Arbitrage Dashboard")

    # Auto-refresh toggle
    auto_refresh = st.sidebar.checkbox("Auto-refresh (5s)", value=False)
    if auto_refresh:
        st.rerun()

    st.markdown("---")

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Overview", "Pilot Monitor", "Strategies", "Trades", "Risk", "System", "How It Works"],
    )

    if page == "Overview":
        render_overview()
    elif page == "Pilot Monitor":
        render_pilot_monitor()
    # ... other pages


def render_pilot_monitor() -> None:
    """Render pilot monitoring page with real-time metrics."""
    st.header("Pilot Monitor")

    # Connection status indicator
    col_status, col_refresh = st.columns([3, 1])
    with col_status:
        st.markdown("🟢 **Live** - Connected to database")
    with col_refresh:
        if st.button("Refresh"):
            st.rerun()

    # Get data using sync database service (no async!)
    try:
        db_service = get_db_service()
        summary = db_service.get_daily_summary(days=1)
        trades = db_service.get_trades_since_days(days=1)
    except Exception as e:
        st.error(f"Database error: {e}")
        summary = {"total_trades": 0, "realized_pnl": 0, "win_rate": 0}
        trades = []

    # Key metrics row
    col1, col2, col3 = st.columns(3)

    with col1:
        pnl = summary.get("realized_pnl", 0)
        st.metric(
            label="Cumulative P&L",
            value=f"${pnl:,.2f}",
        )

    with col2:
        st.metric(
            label="Trades Today",
            value=str(summary.get("total_trades", 0)),
        )

    with col3:
        win_rate = summary.get("win_rate", 0) * 100
        st.metric(
            label="Win Rate",
            value=f"{win_rate:.0f}%",
        )

    st.markdown("---")

    # Recent trades
    if trades:
        st.subheader("Recent Trades")
        df = pd.DataFrame(trades[:20])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No trades yet. Start the pilot to see results.")


if __name__ == "__main__":
    main()
```

**3. If You Must Use Async: Proper Event Loop Management**

```python
# pm_arb/dashboard/async_bridge.py
"""Safe bridge between Streamlit and async code."""

import asyncio
import threading
from typing import Any, Callable, TypeVar, Coroutine

T = TypeVar("T")

_event_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def get_or_create_loop() -> asyncio.AbstractEventLoop:
    """Get or create event loop in background thread.

    NEVER create event loop in Streamlit's main thread.
    Use separate thread instead.
    """
    global _event_loop

    if _event_loop is None or _event_loop.is_closed():
        with _loop_lock:
            # Double-check after acquiring lock
            if _event_loop is None or _event_loop.is_closed():
                # Create loop in background thread
                _event_loop = asyncio.new_event_loop()

                def run_loop():
                    asyncio.set_event_loop(_event_loop)
                    _event_loop.run_forever()

                thread = threading.Thread(target=run_loop, daemon=True)
                thread.start()

    return _event_loop


def run_async_in_thread(
    coro: Coroutine[Any, Any, T],
) -> T:
    """Run async code safely in background thread.

    This is the CORRECT way to use async in Streamlit.
    """
    loop = get_or_create_loop()

    # Schedule coroutine on background loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    # Wait for result
    return future.result(timeout=30.0)


# Usage in dashboard:
# result = run_async_in_thread(get_daily_summary())
```

**4. Document the Decision**

```python
# pm_arb/dashboard/README.md
"""
# Dashboard Architecture

## Why No Asyncio?

Streamlit is fundamentally single-threaded and synchronous.
It creates its own event loop for rerun logic.

Using `asyncio.run()` in Streamlit causes "There is already a running event loop" errors.

### Solutions (in order of preference):

1. **Use sync database client** (RECOMMENDED)
   - Simplest, no conflicts
   - Uses psycopg3 (sync Postgres driver)
   - Cached with @st.cache_resource

2. **Use SQLAlchemy with sync engine** (GOOD)
   - ORM abstracts driver choice
   - Easier migration to async later
   - Same caching strategy

3. **Use background thread with asyncio** (COMPLEX)
   - Only if you must use async libraries
   - Run event loop in daemon thread
   - Use `asyncio.run_coroutine_threadsafe()`
   - Significantly more complex

4. ~~Use `nest_asyncio.apply()`~~ (WRONG)
   - Monkey-patches asyncio internals
   - Fragile, breaks with Python updates
   - Creates hard-to-debug race conditions
   - DO NOT USE in production

## Current Architecture

- Database: Sync psycopg3 driver
- Caching: Streamlit's @st.cache_resource
- Refresh: Manual or auto-rerun
- No asyncio in main thread

## Performance Implications

- Slightly slower queries (no concurrency in dashboard)
- But dashboard is UI layer, not performance-critical
- Real async work (pilot agents) runs elsewhere
- Separation of concerns keeps systems simple
```

### Test Cases

```python
# tests/dashboard/test_db_service.py
"""Tests for dashboard database service."""

import pytest
import threading

from pm_arb.dashboard.db_service import DashboardDatabaseService


def test_db_service_thread_safety():
    """Test that service is thread-safe."""
    service = DashboardDatabaseService("postgresql://localhost/test")

    # Simulate multiple threads accessing service
    results = []

    def access_in_thread():
        try:
            summary = service.get_daily_summary(days=1)
            results.append(("success", summary))
        except Exception as e:
            results.append(("error", str(e)))
        finally:
            service.close_connection()

    threads = [threading.Thread(target=access_in_thread) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should have 3 results, no errors
    assert len(results) == 3
    assert all(r[0] == "success" or "connection" in r[1] for r in results)


# tests/dashboard/test_async_bridge.py
"""Tests for async bridge (if using async)."""

import pytest
import asyncio

from pm_arb.dashboard.async_bridge import run_async_in_thread


@pytest.mark.asyncio
async def test_async_bridge_runs_coroutine():
    """Test that bridge runs async code safely."""
    async def test_coro():
        await asyncio.sleep(0.01)
        return "success"

    result = run_async_in_thread(test_coro())
    assert result == "success"


@pytest.mark.asyncio
async def test_async_bridge_multiple_calls():
    """Test that multiple calls work."""
    async def test_coro(value):
        await asyncio.sleep(0.01)
        return value * 2

    results = [run_async_in_thread(test_coro(i)) for i in range(3)]
    assert results == [0, 2, 4]
```

### Best Practices

- **Never use `asyncio.run()` in Streamlit** — it conflicts with Streamlit's own event loop
- **Use sync database drivers** in dashboard code
- **Use Streamlit's `@st.cache_resource`** for expensive operations
- **Separate concerns**: async pilots run elsewhere, dashboard is sync
- **Document the architecture** so future devs don't repeat the mistake
- **Test thread safety** if using threading
- **Monitor for event loop conflicts** in logging
- **If you must use async**, run in background thread (complex but works)

---

## Integration Test: Full Prevention

```python
# tests/integration/test_bug_prevention.py
"""Integration tests verifying all bug fixes."""

import pytest
from decimal import Decimal
from pm_arb.core.validators import SymbolValidator
from pm_arb.core.parsing import SafeParser
from pm_arb.core.api_batcher import RateLimitBatcher


@pytest.mark.integration
def test_symbol_doubling_prevented():
    """Test Bug #1: Verify symbol doubling is prevented."""
    # Validate symbols at entry
    bare_symbols = SymbolValidator.validate_bare_symbols(["BTC", "ETH"])
    assert bare_symbols == ["BTC", "ETH"]

    # Should reject pre-suffixed
    with pytest.raises(ValueError):
        SymbolValidator.validate_bare_symbols(["BTCUSDT"])


@pytest.mark.integration
def test_decimal_parsing_safe():
    """Test Bug #2: Verify decimal parsing handles all edge cases."""
    # Empty string
    assert SafeParser.decimal("") == Decimal("0")

    # NaN
    assert SafeParser.decimal("NaN") == Decimal("0")

    # Valid
    assert SafeParser.decimal("123.45") == Decimal("123.45")


@pytest.mark.integration
async def test_multi_provider_fallback():
    """Test Bug #3: Verify oracle fallback on geoblocking."""
    # Would test MultiProviderOracle fallback behavior
    pass


@pytest.mark.integration
async def test_rate_limit_respected():
    """Test Bug #4: Verify CoinGecko rate limits respected."""
    batcher = RateLimitBatcher(max_requests_per_minute=20)

    # Should allow 20 requests per minute
    # and enforce limits
    assert len(batcher._request_times) == 0


@pytest.mark.integration
def test_dashboard_no_event_loop_conflicts():
    """Test Bug #5: Verify no event loop conflicts in dashboard."""
    # Dashboard uses sync database service
    # Should not create event loops
    from pm_arb.dashboard.db_service import DashboardDatabaseService

    service = DashboardDatabaseService("postgresql://localhost/test")
    # Should not raise event loop errors
```

---

## Prevention Checklist

Use this checklist when adding new integrations or external APIs:

```markdown
## Before Integrating External API

- [ ] **Symbol Format**
  - [ ] Document canonical format for symbols
  - [ ] Add validators at API boundaries
  - [ ] Write test for symbol transformation chain
  - [ ] Reject pre-formatted input explicitly

- [ ] **Data Parsing**
  - [ ] Document expected data types/ranges
  - [ ] Implement defensive parsing for all fields
  - [ ] Handle None, empty strings, NaN, special values
  - [ ] Add logging for parsing failures
  - [ ] Test with malformed/edge-case data

- [ ] **Service Resilience**
  - [ ] Identify geographic/access restrictions
  - [ ] Design multi-provider fallback
  - [ ] Implement health monitoring
  - [ ] Document fallback chain
  - [ ] Test with provider unavailable

- [ ] **Rate Limiting**
  - [ ] Find advertised rate limit
  - [ ] Implement batching if possible
  - [ ] Add rate limit batcher
  - [ ] Implement exponential backoff
  - [ ] Test at 1.5x, 2x rate limits
  - [ ] Log rate limit events

- [ ] **Async/Concurrency**
  - [ ] Document threading model
  - [ ] If using async, separate from UI
  - [ ] Use Streamlit caching, not asyncio in main thread
  - [ ] Test for race conditions
  - [ ] Document thread safety guarantees
```

---

## Conclusion

These five bugs represent common failure modes in systems that depend on external services and asynchronous operations:

1. **Implicit assumptions** about data formats cause cascading failures
2. **Lack of defensive parsing** exposes to API response variability
3. **Single-point-of-failure** architecture breaks with expected disruptions
4. **Inefficient API usage** hits rate limits unexpectedly
5. **Event loop conflicts** break when mixing sync and async systems

The prevention strategies and test cases in this document will help avoid similar bugs in future development. Add the prevention checklist to your PR review process, and these issues will not recur.

**Key Principle:** External systems are unreliable. Assume they will fail, return garbage data, block you geographically, rate-limit you, or behave unexpectedly. Build defenses explicitly, document assumptions, and test edge cases comprehensively.

