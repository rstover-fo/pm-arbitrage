"""Tests for MarketMatcher."""

from decimal import Decimal

from pm_arb.core.market_matcher import MarketMatcher, MatchResult, ParsedMarket
from pm_arb.core.models import Market


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


class TestParseWithRegex:
    """Tests for _parse_with_regex."""

    def test_parses_btc_above(self) -> None:
        """Should parse 'Will BTC be above $100,000 on February 28?'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:123",
            venue="polymarket",
            external_id="123",
            title="Will BTC be above $100,000 on February 28?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("100000")
        assert result.direction == "above"
        assert result.parse_method == "regex"

    def test_parses_bitcoin_alias(self) -> None:
        """Should parse 'Bitcoin above $95,000'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:456",
            venue="polymarket",
            external_id="456",
            title="Bitcoin above $95,000 on March 1?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("95000")

    def test_parses_eth_above(self) -> None:
        """Should parse 'ETH price above $4,000'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:789",
            venue="polymarket",
            external_id="789",
            title="ETH price above $4,000 at end of February?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.threshold == Decimal("4000")
        assert result.direction == "above"

    def test_parses_reach_as_above(self) -> None:
        """Should parse 'reach' as direction='above'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:111",
            venue="polymarket",
            external_id="111",
            title="Will Ethereum reach $5,000 in Q1 2025?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.direction == "above"
        assert result.threshold == Decimal("5000")

    def test_parses_below(self) -> None:
        """Should parse 'below' direction."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:222",
            venue="polymarket",
            external_id="222",
            title="BTC below $90,000 by March?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.direction == "below"
        assert result.threshold == Decimal("90000")

    def test_handles_commas_in_price(self) -> None:
        """Should strip commas from price."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:333",
            venue="polymarket",
            external_id="333",
            title="Will BTC be above $1,000,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.threshold == Decimal("1000000")

    def test_returns_none_for_politics(self) -> None:
        """Should return None for non-crypto market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:444",
            venue="polymarket",
            external_id="444",
            title="Will Biden win the 2024 election?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is None

    def test_returns_none_for_crypto_without_threshold(self) -> None:
        """Should return None if crypto mentioned but no threshold pattern."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:555",
            venue="polymarket",
            external_id="555",
            title="Will Bitcoin ETF be approved?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is None
