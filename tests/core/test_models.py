"""Tests for core domain models."""

from datetime import UTC, datetime
from decimal import Decimal

from pm_arb.core.models import (
    Market,
    Opportunity,
    OpportunityType,
    OracleData,
    Position,
    RiskDecision,
    Side,
    StrategyPerformance,
    Trade,
    TradeRequest,
    TradeStatus,
)


class TestSideEnum:
    """Tests for Side enum."""

    def test_buy_value(self) -> None:
        """Should have BUY with correct value."""
        assert Side.BUY.value == "buy"

    def test_sell_value(self) -> None:
        """Should have SELL with correct value."""
        assert Side.SELL.value == "sell"


class TestOpportunityTypeEnum:
    """Tests for OpportunityType enum."""

    def test_cross_platform_value(self) -> None:
        """Should have CROSS_PLATFORM with correct value."""
        assert OpportunityType.CROSS_PLATFORM.value == "cross_platform"

    def test_oracle_lag_value(self) -> None:
        """Should have ORACLE_LAG with correct value."""
        assert OpportunityType.ORACLE_LAG.value == "oracle_lag"

    def test_temporal_value(self) -> None:
        """Should have TEMPORAL with correct value."""
        assert OpportunityType.TEMPORAL.value == "temporal"

    def test_mispricing_value(self) -> None:
        """Should have MISPRICING with correct value."""
        assert OpportunityType.MISPRICING.value == "mispricing"


class TestTradeStatusEnum:
    """Tests for TradeStatus enum."""

    def test_all_statuses_exist(self) -> None:
        """Should have all trade lifecycle statuses."""
        expected_statuses = [
            "pending",
            "approved",
            "rejected",
            "submitted",
            "filled",
            "partial",
            "cancelled",
            "failed",
        ]
        actual_values = [s.value for s in TradeStatus]
        assert sorted(actual_values) == sorted(expected_statuses)


class TestMarket:
    """Tests for Market model."""

    def test_market_creation(self) -> None:
        """Should create Market with required fields."""
        market = Market(
            id="polymarket:btc-up-15m",
            venue="polymarket",
            external_id="abc123",
            title="BTC up in next 15 minutes",
            yes_price=Decimal("0.45"),
            no_price=Decimal("0.55"),
        )

        assert market.id == "polymarket:btc-up-15m"
        assert market.venue == "polymarket"
        assert market.external_id == "abc123"
        assert market.title == "BTC up in next 15 minutes"
        assert market.yes_price == Decimal("0.45")
        assert market.no_price == Decimal("0.55")

    def test_market_optional_fields_defaults(self) -> None:
        """Should have sensible defaults for optional fields."""
        market = Market(
            id="kalshi:weather-miami",
            venue="kalshi",
            external_id="xyz789",
            title="Miami temp above 80F",
            yes_price=Decimal("0.60"),
            no_price=Decimal("0.40"),
        )

        assert market.description == ""
        assert market.volume_24h == Decimal("0")
        assert market.liquidity == Decimal("0")
        assert market.end_date is None
        assert market.last_updated is not None

    def test_market_with_all_fields(self) -> None:
        """Should accept all optional fields."""
        now = datetime.now(UTC)
        end_date = datetime(2024, 12, 31, tzinfo=UTC)

        market = Market(
            id="polymarket:btc-up-15m",
            venue="polymarket",
            external_id="abc123",
            title="BTC up in next 15 minutes",
            description="Will BTC price increase in the next 15 minutes?",
            yes_price=Decimal("0.45"),
            no_price=Decimal("0.55"),
            volume_24h=Decimal("50000.00"),
            liquidity=Decimal("100000.00"),
            end_date=end_date,
            last_updated=now,
        )

        assert market.description == "Will BTC price increase in the next 15 minutes?"
        assert market.volume_24h == Decimal("50000.00")
        assert market.liquidity == Decimal("100000.00")
        assert market.end_date == end_date
        assert market.last_updated == now


class TestOracleData:
    """Tests for OracleData model."""

    def test_oracle_data_creation(self) -> None:
        """Should create OracleData with required fields."""
        oracle = OracleData(
            source="binance",
            symbol="BTC",
            value=Decimal("65000.50"),
        )

        assert oracle.source == "binance"
        assert oracle.symbol == "BTC"
        assert oracle.value == Decimal("65000.50")
        assert oracle.timestamp is not None
        assert oracle.metadata == {}

    def test_oracle_data_with_metadata(self) -> None:
        """Should accept metadata dictionary."""
        now = datetime.now(UTC)
        oracle = OracleData(
            source="openweather",
            symbol="Miami-temp",
            value=Decimal("82.5"),
            timestamp=now,
            metadata={"unit": "fahrenheit", "humidity": 65},
        )

        assert oracle.timestamp == now
        assert oracle.metadata["unit"] == "fahrenheit"
        assert oracle.metadata["humidity"] == 65


class TestOpportunity:
    """Tests for Opportunity model."""

    def test_opportunity_creation(self) -> None:
        """Should create Opportunity with classification."""
        now = datetime.now(UTC)
        opp = Opportunity(
            id="opp-001",
            type=OpportunityType.ORACLE_LAG,
            markets=["polymarket:btc-up-15m"],
            oracle_value=Decimal("65000"),
            signal_strength=Decimal("0.85"),
            detected_at=now,
        )

        assert opp.id == "opp-001"
        assert opp.type == OpportunityType.ORACLE_LAG
        assert opp.markets == ["polymarket:btc-up-15m"]
        assert opp.oracle_value == Decimal("65000")
        assert opp.signal_strength == Decimal("0.85")
        assert opp.detected_at == now

    def test_opportunity_optional_fields_defaults(self) -> None:
        """Should have sensible defaults for optional fields."""
        opp = Opportunity(
            id="opp-002",
            type=OpportunityType.CROSS_PLATFORM,
            markets=["polymarket:btc-up-15m", "kalshi:btc-up-15m"],
            signal_strength=Decimal("0.70"),
        )

        assert opp.oracle_source is None
        assert opp.oracle_value is None
        assert opp.expected_edge == Decimal("0")
        assert opp.expires_at is None
        assert opp.metadata == {}
        assert opp.detected_at is not None

    def test_opportunity_cross_platform(self) -> None:
        """Should support cross-platform arbitrage."""
        opp = Opportunity(
            id="opp-003",
            type=OpportunityType.CROSS_PLATFORM,
            markets=["polymarket:election-2024", "kalshi:election-2024"],
            expected_edge=Decimal("0.05"),
            signal_strength=Decimal("0.92"),
        )

        assert len(opp.markets) == 2
        assert opp.expected_edge == Decimal("0.05")


class TestTradeRequest:
    """Tests for TradeRequest model."""

    def test_trade_request_creation(self) -> None:
        """Should create TradeRequest for risk evaluation."""
        request = TradeRequest(
            id="req-001",
            opportunity_id="opp-001",
            strategy="oracle-sniper",
            market_id="polymarket:btc-up-15m",
            side=Side.BUY,
            outcome="YES",
            amount=Decimal("10.00"),
            max_price=Decimal("0.50"),
        )

        assert request.id == "req-001"
        assert request.opportunity_id == "opp-001"
        assert request.strategy == "oracle-sniper"
        assert request.market_id == "polymarket:btc-up-15m"
        assert request.side == Side.BUY
        assert request.outcome == "YES"
        assert request.amount == Decimal("10.00")
        assert request.max_price == Decimal("0.50")
        assert request.created_at is not None

    def test_trade_request_sell_no(self) -> None:
        """Should support SELL side and NO outcome."""
        request = TradeRequest(
            id="req-002",
            opportunity_id="opp-002",
            strategy="mean-reversion",
            market_id="kalshi:weather-miami",
            side=Side.SELL,
            outcome="NO",
            amount=Decimal("25.00"),
            max_price=Decimal("0.35"),
        )

        assert request.side == Side.SELL
        assert request.outcome == "NO"


class TestRiskDecision:
    """Tests for RiskDecision model."""

    def test_risk_decision_approved(self) -> None:
        """Should create approved RiskDecision."""
        decision = RiskDecision(
            request_id="req-001",
            approved=True,
            reason="Within position limits",
        )

        assert decision.request_id == "req-001"
        assert decision.approved is True
        assert decision.reason == "Within position limits"
        assert decision.rule_triggered is None
        assert decision.decided_at is not None

    def test_risk_decision_rejected(self) -> None:
        """Should create rejected RiskDecision with rule triggered."""
        decision = RiskDecision(
            request_id="req-002",
            approved=False,
            reason="Position limit exceeded for this market",
            rule_triggered="max_position_per_market",
        )

        assert decision.approved is False
        assert decision.rule_triggered == "max_position_per_market"


class TestTrade:
    """Tests for Trade model."""

    def test_trade_creation(self) -> None:
        """Should create Trade with required fields."""
        now = datetime.now(UTC)
        trade = Trade(
            id="trade-001",
            request_id="req-001",
            market_id="polymarket:btc-up-15m",
            venue="polymarket",
            side=Side.BUY,
            outcome="YES",
            amount=Decimal("10.00"),
            price=Decimal("0.48"),
            status=TradeStatus.FILLED,
            executed_at=now,
        )

        assert trade.id == "trade-001"
        assert trade.request_id == "req-001"
        assert trade.market_id == "polymarket:btc-up-15m"
        assert trade.venue == "polymarket"
        assert trade.side == Side.BUY
        assert trade.outcome == "YES"
        assert trade.amount == Decimal("10.00")
        assert trade.price == Decimal("0.48")
        assert trade.fees == Decimal("0")
        assert trade.status == TradeStatus.FILLED
        assert trade.external_id is None
        assert trade.executed_at == now
        assert trade.filled_at is None

    def test_trade_with_fees_and_external_id(self) -> None:
        """Should accept fees and external ID."""
        now = datetime.now(UTC)
        trade = Trade(
            id="trade-002",
            request_id="req-002",
            market_id="kalshi:weather-miami",
            venue="kalshi",
            side=Side.SELL,
            outcome="NO",
            amount=Decimal("25.00"),
            price=Decimal("0.60"),
            fees=Decimal("0.25"),
            status=TradeStatus.FILLED,
            external_id="kalshi-ext-123",
            executed_at=now,
            filled_at=now,
        )

        assert trade.fees == Decimal("0.25")
        assert trade.external_id == "kalshi-ext-123"
        assert trade.filled_at == now

    def test_trade_pending_status(self) -> None:
        """Should support pending trade status."""
        trade = Trade(
            id="trade-003",
            request_id="req-003",
            market_id="polymarket:election-2024",
            venue="polymarket",
            side=Side.BUY,
            outcome="YES",
            amount=Decimal("50.00"),
            price=Decimal("0.52"),
            status=TradeStatus.PENDING,
        )

        assert trade.status == TradeStatus.PENDING


class TestPosition:
    """Tests for Position model."""

    def test_position_creation(self) -> None:
        """Should create Position with required fields."""
        now = datetime.now(UTC)
        position = Position(
            id="pos-001",
            market_id="polymarket:btc-up-15m",
            venue="polymarket",
            outcome="YES",
            quantity=Decimal("20.0"),
            avg_price=Decimal("0.48"),
            current_price=Decimal("0.55"),
            unrealized_pnl=Decimal("1.40"),
            opened_at=now,
        )

        assert position.id == "pos-001"
        assert position.market_id == "polymarket:btc-up-15m"
        assert position.venue == "polymarket"
        assert position.outcome == "YES"
        assert position.quantity == Decimal("20.0")
        assert position.avg_price == Decimal("0.48")
        assert position.current_price == Decimal("0.55")
        assert position.unrealized_pnl == Decimal("1.40")
        assert position.opened_at == now
        assert position.last_updated is not None

    def test_position_negative_pnl(self) -> None:
        """Should handle negative unrealized PnL."""
        now = datetime.now(UTC)
        position = Position(
            id="pos-002",
            market_id="kalshi:weather-miami",
            venue="kalshi",
            outcome="NO",
            quantity=Decimal("15.0"),
            avg_price=Decimal("0.40"),
            current_price=Decimal("0.35"),
            unrealized_pnl=Decimal("-0.75"),
            opened_at=now,
        )

        assert position.unrealized_pnl == Decimal("-0.75")


class TestStrategyPerformance:
    """Tests for StrategyPerformance model."""

    def test_strategy_performance_creation(self) -> None:
        """Should create StrategyPerformance with required fields."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)

        perf = StrategyPerformance(
            strategy="oracle-sniper",
            period_start=start,
            period_end=end,
            trades=50,
            wins=35,
            losses=15,
            total_pnl=Decimal("250.00"),
            allocation_pct=Decimal("25.0"),
        )

        assert perf.strategy == "oracle-sniper"
        assert perf.period_start == start
        assert perf.period_end == end
        assert perf.trades == 50
        assert perf.wins == 35
        assert perf.losses == 15
        assert perf.total_pnl == Decimal("250.00")
        assert perf.sharpe_ratio is None
        assert perf.max_drawdown is None
        assert perf.allocation_pct == Decimal("25.0")

    def test_strategy_performance_with_metrics(self) -> None:
        """Should accept Sharpe ratio and max drawdown."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)

        perf = StrategyPerformance(
            strategy="mean-reversion",
            period_start=start,
            period_end=end,
            trades=100,
            wins=60,
            losses=40,
            total_pnl=Decimal("500.00"),
            sharpe_ratio=Decimal("1.85"),
            max_drawdown=Decimal("50.00"),
            allocation_pct=Decimal("30.0"),
        )

        assert perf.sharpe_ratio == Decimal("1.85")
        assert perf.max_drawdown == Decimal("50.00")

    def test_strategy_performance_negative_pnl(self) -> None:
        """Should handle negative total PnL."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)

        perf = StrategyPerformance(
            strategy="experimental",
            period_start=start,
            period_end=end,
            trades=20,
            wins=5,
            losses=15,
            total_pnl=Decimal("-75.00"),
            allocation_pct=Decimal("5.0"),
        )

        assert perf.total_pnl == Decimal("-75.00")


class TestStrategyAllocation:
    """Tests for StrategyAllocation model."""

    def test_allocation_creation(self) -> None:
        """Should create strategy allocation."""
        from pm_arb.core.models import StrategyAllocation

        allocation = StrategyAllocation(
            strategy="oracle-sniper",
            allocation_pct=Decimal("0.25"),
            total_capital=Decimal("1000"),
            available_capital=Decimal("250"),
        )

        assert allocation.strategy == "oracle-sniper"
        assert allocation.allocation_pct == Decimal("0.25")
        assert allocation.available_capital == Decimal("250")
