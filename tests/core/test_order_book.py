"""Tests for OrderBook model and VWAP calculation."""

from decimal import Decimal

import pytest

from pm_arb.core.models import OrderBook, OrderBookLevel


def test_order_book_creation() -> None:
    """Should create OrderBook with bid/ask levels."""
    book = OrderBook(
        market_id="polymarket:btc-up",
        bids=[
            OrderBookLevel(price=Decimal("0.45"), size=Decimal("100")),
            OrderBookLevel(price=Decimal("0.44"), size=Decimal("200")),
        ],
        asks=[
            OrderBookLevel(price=Decimal("0.46"), size=Decimal("150")),
            OrderBookLevel(price=Decimal("0.47"), size=Decimal("250")),
        ],
    )

    assert book.best_bid == Decimal("0.45")
    assert book.best_ask == Decimal("0.46")
    assert book.spread == Decimal("0.01")


def test_vwap_calculation_single_level() -> None:
    """VWAP for amount within first level equals that level's price."""
    book = OrderBook(
        market_id="test",
        bids=[OrderBookLevel(price=Decimal("0.50"), size=Decimal("1000"))],
        asks=[OrderBookLevel(price=Decimal("0.52"), size=Decimal("1000"))],
    )

    vwap = book.calculate_buy_vwap(Decimal("100"))
    assert vwap == Decimal("0.52")


def test_vwap_calculation_multiple_levels() -> None:
    """VWAP across multiple levels is volume-weighted."""
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("100")),  # $50 total
            OrderBookLevel(price=Decimal("0.60"), size=Decimal("100")),  # $60 total
        ],
    )

    # Buy 200 tokens: 100 @ 0.50, 100 @ 0.60
    # VWAP = (100*0.50 + 100*0.60) / 200 = 110 / 200 = 0.55
    vwap = book.calculate_buy_vwap(Decimal("200"))
    assert vwap == Decimal("0.55")


def test_vwap_insufficient_liquidity() -> None:
    """VWAP returns None when insufficient liquidity."""
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[OrderBookLevel(price=Decimal("0.50"), size=Decimal("100"))],
    )

    vwap = book.calculate_buy_vwap(Decimal("500"))
    assert vwap is None


def test_available_liquidity() -> None:
    """Should calculate total available liquidity at price limit."""
    book = OrderBook(
        market_id="test",
        bids=[],
        asks=[
            OrderBookLevel(price=Decimal("0.50"), size=Decimal("100")),
            OrderBookLevel(price=Decimal("0.55"), size=Decimal("200")),
            OrderBookLevel(price=Decimal("0.60"), size=Decimal("300")),
        ],
    )

    # Liquidity up to price 0.55
    liquidity = book.available_liquidity_at_price(Decimal("0.55"), side="buy")
    assert liquidity == Decimal("300")  # 100 + 200

    # Liquidity up to price 0.60
    liquidity = book.available_liquidity_at_price(Decimal("0.60"), side="buy")
    assert liquidity == Decimal("600")  # 100 + 200 + 300
