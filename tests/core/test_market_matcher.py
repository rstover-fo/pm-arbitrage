"""Tests for MarketMatcher."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.core.market_matcher import (
    KALSHI_ASSET_TO_ORACLE,
    KALSHI_TICKER_PATTERN,
    MarketMatcher,
    MatchResult,
    ParsedMarket,
)
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

    def test_parses_dip_to_as_below(self) -> None:
        """Should parse 'dip to' as direction='below'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:600",
            venue="polymarket",
            external_id="600",
            title="Will Bitcoin dip to $55,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("55000")
        assert result.direction == "below"

    def test_parses_sol_dip(self) -> None:
        """Should parse 'Will Solana dip to $90?'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:601",
            venue="polymarket",
            external_id="601",
            title="Will Solana dip to $90?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "SOL"
        assert result.threshold == Decimal("90")
        assert result.direction == "below"

    def test_parses_hit_as_above(self) -> None:
        """Should parse 'hit' as direction='above'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:602",
            venue="polymarket",
            external_id="602",
            title="Will Bitcoin hit $150,000 by end of year?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("150000")
        assert result.direction == "above"

    def test_parses_dollar_m_abbreviation(self) -> None:
        """Should parse '$1m' as 1000000."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:603",
            venue="polymarket",
            external_id="603",
            title="Will bitcoin hit $1m?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "BTC"
        assert result.threshold == Decimal("1000000")
        assert result.direction == "above"

    def test_parses_dollar_k_abbreviation(self) -> None:
        """Should parse '$55k' as 55000."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:604",
            venue="polymarket",
            external_id="604",
            title="Will ETH hit $5k this month?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.threshold == Decimal("5000")
        assert result.direction == "above"

    def test_parses_drop_as_below(self) -> None:
        """Should parse 'drop' as direction='below'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:605",
            venue="polymarket",
            external_id="605",
            title="Will ETH drop below $2,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.threshold == Decimal("2000")
        assert result.direction == "below"

    def test_parses_exceed_as_above(self) -> None:
        """Should parse 'exceed' as direction='above'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:606",
            venue="polymarket",
            external_id="606",
            title="Will Solana exceed $300?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_with_regex(market)
        assert result is not None
        assert result.asset == "SOL"
        assert result.threshold == Decimal("300")
        assert result.direction == "above"

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


class TestParseWithLLM:
    """Tests for _parse_with_llm."""

    @pytest.mark.asyncio
    async def test_calls_anthropic_with_batch(self) -> None:
        """Should batch multiple titles in one API call."""
        matcher = MarketMatcher(scanner=None, anthropic_api_key="test-key")  # type: ignore[arg-type]

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Will the price of Bitcoin exceed one hundred thousand dollars?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:222",
                venue="polymarket",
                external_id="222",
                title="Crypto winter: ETH under 3k by April?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        mock_response = MagicMock()
        llm_json = (
            '[{"asset": "BTC", "threshold": 100000, "direction": "above"}, '
            '{"asset": "ETH", "threshold": 3000, "direction": "below"}]'
        )
        mock_response.content = [MagicMock(text=llm_json)]

        with patch("pm_arb.core.market_matcher.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            results = await matcher._parse_with_llm(markets)

        assert len(results) == 2
        assert results[0].asset == "BTC"
        assert results[0].threshold == Decimal("100000")
        assert results[0].direction == "above"
        assert results[0].parse_method == "llm"
        assert results[1].asset == "ETH"
        assert results[1].threshold == Decimal("3000")
        assert results[1].direction == "below"

    @pytest.mark.asyncio
    async def test_returns_empty_without_api_key(self) -> None:
        """Should return empty list if no API key configured."""
        matcher = MarketMatcher(scanner=None, anthropic_api_key=None)  # type: ignore[arg-type]

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Unusual crypto phrasing",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        results = await matcher._parse_with_llm(markets)
        assert results == []

    @pytest.mark.asyncio
    async def test_handles_llm_returning_null(self) -> None:
        """Should skip markets where LLM returns null."""
        matcher = MarketMatcher(scanner=None, anthropic_api_key="test-key")  # type: ignore[arg-type]

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Some weird market",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[null]")]

        with patch("pm_arb.core.market_matcher.anthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=mock_response)
            mock_anthropic.AsyncAnthropic.return_value = mock_client

            results = await matcher._parse_with_llm(markets)

        assert results == []


class TestMatchMarkets:
    """Tests for match_markets main method."""

    @pytest.mark.asyncio
    async def test_matches_regex_parseable_markets(self) -> None:
        """Should match markets that regex can parse."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key=None)

        markets = [
            Market(
                id="polymarket:123",
                venue="polymarket",
                external_id="123",
                title="Will BTC be above $100,000 on February 28?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:456",
                venue="polymarket",
                external_id="456",
                title="ETH price above $4,000?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        result = await matcher.match_markets(markets)

        assert result.total_markets == 2
        assert result.matched == 2
        assert result.skipped == 0
        assert result.failed == 0
        assert len(result.matched_markets) == 2

    @pytest.mark.asyncio
    async def test_skips_non_crypto_markets(self) -> None:
        """Should skip non-crypto markets without calling LLM."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key="test-key")

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Will Biden win?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:222",
                venue="polymarket",
                external_id="222",
                title="Super Bowl 2026 winner?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        with patch.object(matcher, "_parse_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            result = await matcher.match_markets(markets)

        assert result.total_markets == 2
        assert result.matched == 0
        assert result.skipped == 2
        # LLM should NOT be called for non-crypto markets
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_registers_mappings_with_scanner(self) -> None:
        """Should call scanner.register_market_oracle_mapping for each match."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key=None)

        markets = [
            Market(
                id="polymarket:123",
                venue="polymarket",
                external_id="123",
                title="Will BTC be above $100,000?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        await matcher.match_markets(markets)

        mock_scanner.register_market_oracle_mapping.assert_called_once_with(
            market_id="polymarket:123",
            oracle_symbol="BTC",
            threshold=Decimal("100000"),
            direction="above",
        )

    @pytest.mark.asyncio
    async def test_uses_llm_fallback_for_unparsed_crypto(self) -> None:
        """Should call LLM for crypto markets that regex couldn't parse."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key="test-key")

        markets = [
            Market(
                id="polymarket:111",
                venue="polymarket",
                external_id="111",
                title="Will BTC be above $100,000?",  # Regex parseable
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
            Market(
                id="polymarket:222",
                venue="polymarket",
                external_id="222",
                title="Bitcoin exceeds one hundred thousand USD?",  # Needs LLM
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        with patch.object(matcher, "_parse_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = [
                ParsedMarket(
                    market_id="polymarket:222",
                    asset="BTC",
                    threshold=Decimal("100000"),
                    direction="above",
                    expiry=None,
                    parse_method="llm",
                )
            ]
            result = await matcher.match_markets(markets)

        assert result.matched == 2
        # LLM called with only the unparsed crypto market
        mock_llm.assert_called_once()
        llm_markets = mock_llm.call_args[0][0]
        assert len(llm_markets) == 1
        assert llm_markets[0].id == "polymarket:222"

    @pytest.mark.asyncio
    async def test_routes_kalshi_markets_to_ticker_parser(self) -> None:
        """Should route kalshi markets to _parse_kalshi_ticker, not regex/LLM."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key="test-key")

        markets = [
            Market(
                id="kalshi:BTCUSD-26FEB04-T104000",
                venue="kalshi",
                external_id="BTCUSD-26FEB04-T104000",
                title="Will BTC be above $104,000?",
                yes_price=Decimal("0.65"),
                no_price=Decimal("0.35"),
            ),
            Market(
                id="polymarket:123",
                venue="polymarket",
                external_id="123",
                title="Will BTC be above $100,000?",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        with patch.object(matcher, "_parse_with_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = []
            result = await matcher.match_markets(markets)

        assert result.total_markets == 2
        assert result.matched == 2
        assert result.skipped == 0
        # Kalshi market should be parsed with kalshi_ticker method
        kalshi_parsed = result.matched_markets[0]
        assert kalshi_parsed.parse_method == "kalshi_ticker"
        assert kalshi_parsed.asset == "BTC"
        assert kalshi_parsed.threshold == Decimal("104000")
        assert kalshi_parsed.direction == "above"
        # Polymarket market should use regex
        poly_parsed = result.matched_markets[1]
        assert poly_parsed.parse_method == "regex"
        # LLM should NOT be called (both markets parsed successfully)
        mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_registers_kalshi_mappings_with_scanner(self) -> None:
        """Should register Kalshi market oracle mappings with scanner."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key=None)

        markets = [
            Market(
                id="kalshi:FEDRATE-26FEB04-T450",
                venue="kalshi",
                external_id="FEDRATE-26FEB04-T450",
                title="Fed funds rate above 4.50%?",
                yes_price=Decimal("0.3"),
                no_price=Decimal("0.7"),
            ),
        ]

        await matcher.match_markets(markets)

        mock_scanner.register_market_oracle_mapping.assert_called_once_with(
            market_id="kalshi:FEDRATE-26FEB04-T450",
            oracle_symbol="FED_RATE",
            threshold=Decimal("4.50"),
            direction="above",
        )

    @pytest.mark.asyncio
    async def test_skips_unparseable_kalshi_market(self) -> None:
        """Should skip kalshi market with unrecognized ticker format."""
        mock_scanner = MagicMock()
        matcher = MarketMatcher(scanner=mock_scanner, anthropic_api_key=None)

        markets = [
            Market(
                id="kalshi:WEIRDFORMAT",
                venue="kalshi",
                external_id="WEIRDFORMAT",
                title="Some weird Kalshi market",
                yes_price=Decimal("0.5"),
                no_price=Decimal("0.5"),
            ),
        ]

        result = await matcher.match_markets(markets)

        assert result.total_markets == 1
        assert result.matched == 0
        assert result.skipped == 1
        mock_scanner.register_market_oracle_mapping.assert_not_called()


class TestKalshiTickerPattern:
    """Tests for the KALSHI_TICKER_PATTERN regex."""

    def test_matches_btcusd_ticker(self) -> None:
        """Should match BTCUSD-26FEB04-T104000."""
        match = KALSHI_TICKER_PATTERN.match("BTCUSD-26FEB04-T104000")
        assert match is not None
        assert match.group("asset") == "BTCUSD"
        assert match.group("threshold") == "104000"

    def test_matches_fedrate_ticker(self) -> None:
        """Should match FEDRATE-26FEB04-T450."""
        match = KALSHI_TICKER_PATTERN.match("FEDRATE-26FEB04-T450")
        assert match is not None
        assert match.group("asset") == "FEDRATE"
        assert match.group("threshold") == "450"

    def test_matches_temp_city_ticker(self) -> None:
        """Should match TEMP-NYC-26FEB04-T40."""
        match = KALSHI_TICKER_PATTERN.match("TEMP-NYC-26FEB04-T40")
        assert match is not None
        assert match.group("asset") == "TEMP-NYC"
        assert match.group("threshold") == "40"

    def test_matches_decimal_threshold_with_p(self) -> None:
        """Should match threshold with P decimal: T4P0."""
        match = KALSHI_TICKER_PATTERN.match("UNEMPLOYMENT-26FEB04-T4P0")
        assert match is not None
        assert match.group("threshold") == "4P0"

    def test_rejects_malformed_ticker(self) -> None:
        """Should not match ticker without date segment."""
        match = KALSHI_TICKER_PATTERN.match("BTCUSD-T104000")
        assert match is None

    def test_rejects_lowercase_ticker(self) -> None:
        """Should not match lowercase tickers."""
        match = KALSHI_TICKER_PATTERN.match("btcusd-26FEB04-T104000")
        assert match is None


class TestIsKalshiMarket:
    """Tests for _is_kalshi_market helper."""

    def test_kalshi_venue(self) -> None:
        """Should identify market with venue='kalshi'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="some-id",
            venue="kalshi",
            external_id="BTCUSD-26FEB04-T104000",
            title="BTC above $104,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        assert matcher._is_kalshi_market(market) is True

    def test_kalshi_prefix_in_id(self) -> None:
        """Should identify market with id starting with 'kalshi:'."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:BTCUSD-26FEB04-T104000",
            venue="other",
            external_id="BTCUSD-26FEB04-T104000",
            title="BTC above $104,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        assert matcher._is_kalshi_market(market) is True

    def test_polymarket_is_not_kalshi(self) -> None:
        """Should reject polymarket market."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="polymarket:123",
            venue="polymarket",
            external_id="123",
            title="Will BTC be above $100,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        assert matcher._is_kalshi_market(market) is False


class TestParseKalshiTicker:
    """Tests for _parse_kalshi_ticker."""

    def test_parses_btcusd_ticker(self) -> None:
        """Should parse BTCUSD-26FEB04-T104000 -> BTC, $104,000, above."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:BTCUSD-26FEB04-T104000",
            venue="kalshi",
            external_id="BTCUSD-26FEB04-T104000",
            title="Will BTC be above $104,000?",
            yes_price=Decimal("0.65"),
            no_price=Decimal("0.35"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.market_id == "kalshi:BTCUSD-26FEB04-T104000"
        assert result.asset == "BTC"
        assert result.threshold == Decimal("104000")
        assert result.direction == "above"
        assert result.parse_method == "kalshi_ticker"

    def test_parses_ethusd_ticker(self) -> None:
        """Should parse ETHUSD ticker to ETH oracle symbol."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:ETHUSD-26FEB04-T4000",
            venue="kalshi",
            external_id="ETHUSD-26FEB04-T4000",
            title="Will ETH be above $4,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.asset == "ETH"
        assert result.threshold == Decimal("4000")

    def test_parses_fedrate_ticker_with_implied_decimal(self) -> None:
        """Should parse FEDRATE-26FEB04-T450 -> FED_RATE, 4.50, above."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:FEDRATE-26FEB04-T450",
            venue="kalshi",
            external_id="FEDRATE-26FEB04-T450",
            title="Fed funds rate above 4.50%?",
            yes_price=Decimal("0.3"),
            no_price=Decimal("0.7"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.market_id == "kalshi:FEDRATE-26FEB04-T450"
        assert result.asset == "FED_RATE"
        assert result.threshold == Decimal("4.50")
        assert result.direction == "above"
        assert result.parse_method == "kalshi_ticker"

    def test_parses_unemployment_ticker_with_p_decimal(self) -> None:
        """Should parse UNEMPLOYMENT-26FEB04-T4P0 -> UNEMPLOYMENT, 4.0, above."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:UNEMPLOYMENT-26FEB04-T4P0",
            venue="kalshi",
            external_id="UNEMPLOYMENT-26FEB04-T4P0",
            title="Unemployment rate above 4.0%?",
            yes_price=Decimal("0.4"),
            no_price=Decimal("0.6"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.asset == "UNEMPLOYMENT"
        assert result.threshold == Decimal("4.0")
        assert result.direction == "above"

    def test_parses_temp_nyc_ticker(self) -> None:
        """Should parse TEMP-NYC-26FEB04-T40 -> TEMP_NYC, 40, above."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:TEMP-NYC-26FEB04-T40",
            venue="kalshi",
            external_id="TEMP-NYC-26FEB04-T40",
            title="Will NYC temperature be above 40F?",
            yes_price=Decimal("0.55"),
            no_price=Decimal("0.45"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.market_id == "kalshi:TEMP-NYC-26FEB04-T40"
        assert result.asset == "TEMP_NYC"
        assert result.threshold == Decimal("40")
        assert result.direction == "above"
        assert result.parse_method == "kalshi_ticker"

    def test_parses_cpi_ticker(self) -> None:
        """Should parse CPI ticker to CPI oracle symbol."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:CPI-26FEB04-T3P5",
            venue="kalshi",
            external_id="CPI-26FEB04-T3P5",
            title="CPI above 3.5%?",
            yes_price=Decimal("0.2"),
            no_price=Decimal("0.8"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.asset == "CPI"
        assert result.threshold == Decimal("3.5")

    def test_returns_none_for_unknown_asset(self) -> None:
        """Should return None for unrecognized Kalshi asset prefix."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:XYZABC-26FEB04-T100",
            venue="kalshi",
            external_id="XYZABC-26FEB04-T100",
            title="Some unknown market",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is None

    def test_returns_none_for_malformed_ticker(self) -> None:
        """Should return None when ticker doesn't match pattern."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:not-a-valid-ticker",
            venue="kalshi",
            external_id="not-a-valid-ticker",
            title="Some market",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is None

    def test_uses_external_id_for_ticker(self) -> None:
        """Should prefer external_id for ticker extraction."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:some-internal-id",
            venue="kalshi",
            external_id="BTCUSD-26FEB04-T104000",
            title="BTC above $104,000?",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        result = matcher._parse_kalshi_ticker(market)
        assert result is not None
        assert result.asset == "BTC"

    def test_falls_back_to_market_id_when_no_external_id(self) -> None:
        """Should fall back to parsing market id if external_id is empty."""
        matcher = MarketMatcher(scanner=None)  # type: ignore[arg-type]
        market = Market(
            id="kalshi:GDPUSD-26FEB04-T200",
            venue="kalshi",
            external_id="",
            title="GDP market",
            yes_price=Decimal("0.5"),
            no_price=Decimal("0.5"),
        )
        # Note: GDPUSD is not in mapping, but GDP is. The ticker has GDPUSD.
        # This should return None since GDPUSD isn't in the mapping.
        result = matcher._parse_kalshi_ticker(market)
        assert result is None


class TestKalshiAssetToOracle:
    """Tests for the KALSHI_ASSET_TO_ORACLE mapping."""

    def test_btcusd_maps_to_btc(self) -> None:
        """BTCUSD should map to BTC oracle symbol."""
        assert KALSHI_ASSET_TO_ORACLE["BTCUSD"] == "BTC"

    def test_ethusd_maps_to_eth(self) -> None:
        """ETHUSD should map to ETH oracle symbol."""
        assert KALSHI_ASSET_TO_ORACLE["ETHUSD"] == "ETH"

    def test_fedrate_maps_to_fed_rate(self) -> None:
        """FEDRATE should map to FED_RATE oracle symbol."""
        assert KALSHI_ASSET_TO_ORACLE["FEDRATE"] == "FED_RATE"

    def test_unemployment_maps_to_unemployment(self) -> None:
        """UNEMPLOYMENT should map to UNEMPLOYMENT oracle symbol."""
        assert KALSHI_ASSET_TO_ORACLE["UNEMPLOYMENT"] == "UNEMPLOYMENT"

    def test_initialclaims_maps_to_initial_claims(self) -> None:
        """INITIALCLAIMS should map to INITIAL_CLAIMS oracle symbol."""
        assert KALSHI_ASSET_TO_ORACLE["INITIALCLAIMS"] == "INITIAL_CLAIMS"
