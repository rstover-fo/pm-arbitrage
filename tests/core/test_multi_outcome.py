"""Tests for MultiOutcomeMarket model."""

from decimal import Decimal

from pm_arb.core.models import MultiOutcomeMarket, Outcome


def test_multi_outcome_market_creation() -> None:
    """Should create market with multiple outcomes."""
    market = MultiOutcomeMarket(
        id="polymarket:president-2024",
        venue="polymarket",
        external_id="pres2024",
        title="Who will win the 2024 presidential election?",
        outcomes=[
            Outcome(name="Trump", price=Decimal("0.52")),
            Outcome(name="Biden", price=Decimal("0.35")),
            Outcome(name="Other", price=Decimal("0.08")),
        ],
    )

    assert len(market.outcomes) == 3
    assert market.price_sum == Decimal("0.95")


def test_multi_outcome_detects_mispricing() -> None:
    """Should detect when outcome sum < 1.0."""
    market = MultiOutcomeMarket(
        id="polymarket:test",
        venue="polymarket",
        external_id="test",
        title="Test",
        outcomes=[
            Outcome(name="A", price=Decimal("0.30")),
            Outcome(name="B", price=Decimal("0.30")),
            Outcome(name="C", price=Decimal("0.30")),
        ],
    )

    assert market.price_sum == Decimal("0.90")
    assert market.arbitrage_edge == Decimal("0.10")


def test_multi_outcome_no_arbitrage() -> None:
    """Should return zero edge when fairly priced."""
    market = MultiOutcomeMarket(
        id="polymarket:test",
        venue="polymarket",
        external_id="test",
        title="Test",
        outcomes=[
            Outcome(name="A", price=Decimal("0.50")),
            Outcome(name="B", price=Decimal("0.50")),
        ],
    )

    assert market.price_sum == Decimal("1.00")
    assert market.arbitrage_edge == Decimal("0")
