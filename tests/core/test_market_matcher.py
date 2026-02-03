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


class TestIsCryptoMarket:
    """Tests for _is_crypto_market helper."""

    def test_btc_is_crypto(self) -> None:
        """Should identify BTC market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Will BTC be above $100,000?") is True

    def test_bitcoin_is_crypto(self) -> None:
        """Should identify Bitcoin market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Bitcoin above $95,000") is True

    def test_ethereum_is_crypto(self) -> None:
        """Should identify Ethereum market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("ETH price above $4,000") is True

    def test_politics_not_crypto(self) -> None:
        """Should reject politics market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Will Biden win?") is False

    def test_sports_not_crypto(self) -> None:
        """Should reject sports market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("Super Bowl winner 2026?") is False

    def test_case_insensitive(self) -> None:
        """Should match regardless of case."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        assert matcher._is_crypto_market("BITCOIN above $100k") is True
        assert matcher._is_crypto_market("ethereum BELOW $3000") is True
