"""Mock data for dashboard development and testing."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def get_mock_portfolio() -> dict[str, Any]:
    """Return mock portfolio summary."""
    return {
        "total_capital": Decimal("1000"),
        "current_value": Decimal("1125"),
        "total_pnl": Decimal("125"),
        "total_trades": 15,
        "total_wins": 9,
        "overall_win_rate": Decimal("0.60"),
        "strategy_count": 2,
    }


def get_mock_strategies() -> list[dict[str, Any]]:
    """Return mock strategy summaries."""
    return [
        {
            "strategy": "oracle-sniper",
            "total_pnl": Decimal("150"),
            "trades": 10,
            "wins": 7,
            "losses": 3,
            "win_rate": Decimal("0.70"),
            "largest_win": Decimal("50"),
            "largest_loss": Decimal("-20"),
            "allocation_pct": Decimal("0.60"),
        },
        {
            "strategy": "cross-arb",
            "total_pnl": Decimal("-25"),
            "trades": 5,
            "wins": 2,
            "losses": 3,
            "win_rate": Decimal("0.40"),
            "largest_win": Decimal("20"),
            "largest_loss": Decimal("-30"),
            "allocation_pct": Decimal("0.40"),
        },
    ]


def get_mock_risk_state() -> dict[str, Any]:
    """Return mock risk metrics."""
    return {
        "current_value": Decimal("1125"),
        "high_water_mark": Decimal("1150"),
        "drawdown": Decimal("25"),
        "drawdown_pct": Decimal("0.0217"),
        "daily_pnl": Decimal("45"),
        "initial_bankroll": Decimal("1000"),
        "positions": {
            "polymarket:btc-100k": Decimal("100"),
            "polymarket:eth-5k": Decimal("50"),
        },
        "platform_exposure": {
            "polymarket": Decimal("150"),
        },
        "halted": False,
    }


def get_mock_trades() -> list[dict[str, Any]]:
    """Return mock recent trades."""
    return [
        {
            "id": "paper-abc123",
            "request_id": "req-001",
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "side": "buy",
            "outcome": "YES",
            "amount": Decimal("50"),
            "price": Decimal("0.55"),
            "fees": Decimal("0.05"),
            "status": "filled",
            "executed_at": datetime(2026, 1, 31, 14, 30, 0, tzinfo=UTC).isoformat(),
        },
        {
            "id": "paper-def456",
            "request_id": "req-002",
            "market_id": "polymarket:eth-5k",
            "venue": "polymarket",
            "side": "buy",
            "outcome": "NO",
            "amount": Decimal("30"),
            "price": Decimal("0.40"),
            "fees": Decimal("0.03"),
            "status": "filled",
            "executed_at": datetime(2026, 1, 31, 14, 15, 0, tzinfo=UTC).isoformat(),
        },
        {
            "id": "paper-ghi789",
            "request_id": "req-003",
            "market_id": "polymarket:btc-100k",
            "venue": "polymarket",
            "side": "sell",
            "outcome": "YES",
            "amount": Decimal("25"),
            "price": Decimal("0.65"),
            "fees": Decimal("0.025"),
            "status": "filled",
            "executed_at": datetime(2026, 1, 31, 14, 0, 0, tzinfo=UTC).isoformat(),
        },
    ]
