"""Tests for MarketMatcher."""

from decimal import Decimal

from pm_arb.core.market_matcher import MarketMatcher, MatchResult, ParsedMarket


class TestParsedMarket:
    """Tests for ParsedMarket dataclass."""

    def test_creates_with_all_fields(self) -> None:
        """Should create ParsedMarket with all fields."""
        parsed = ParsedMarket(
            market_id="polymarket:123",
            asset="BTC",
            threshold=Decimal("100000"),
            direction="above",
            expiry="February 28",
            parse_method="regex",
        )
        assert parsed.market_id == "polymarket:123"
        assert parsed.asset == "BTC"
        assert parsed.threshold == Decimal("100000")
        assert parsed.direction == "above"
        assert parsed.expiry == "February 28"
        assert parsed.parse_method == "regex"

    def test_creates_with_none_values(self) -> None:
        """Should allow None for optional fields."""
        parsed = ParsedMarket(
            market_id="polymarket:456",
            asset=None,
            threshold=None,
            direction=None,
            expiry=None,
            parse_method="regex",
        )
        assert parsed.asset is None
        assert parsed.threshold is None


class TestMatchResult:
    """Tests for MatchResult dataclass."""

    def test_creates_with_counts(self) -> None:
        """Should create MatchResult with counts."""
        result = MatchResult(
            total_markets=100,
            matched=25,
            skipped=70,
            failed=5,
            matched_markets=[],
        )
        assert result.total_markets == 100
        assert result.matched == 25
        assert result.skipped == 70
        assert result.failed == 5


class TestAssetAliases:
    """Tests for asset alias resolution."""

    def test_resolves_btc_lowercase(self) -> None:
        """Should resolve 'btc' to 'BTC'."""
        assert MarketMatcher.ASSET_ALIASES["btc"] == "BTC"

    def test_resolves_bitcoin(self) -> None:
        """Should resolve 'bitcoin' to 'BTC'."""
        assert MarketMatcher.ASSET_ALIASES["bitcoin"] == "BTC"

    def test_resolves_ethereum(self) -> None:
        """Should resolve 'ethereum' to 'ETH'."""
        assert MarketMatcher.ASSET_ALIASES["ethereum"] == "ETH"

    def test_resolves_solana(self) -> None:
        """Should resolve 'solana' to 'SOL'."""
        assert MarketMatcher.ASSET_ALIASES["solana"] == "SOL"
