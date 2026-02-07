"""Tests for Kalshi venue adapter."""

import base64
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from pm_arb.adapters.venues.kalshi import KalshiAdapter, KALSHI_API_BASE
from pm_arb.core.auth import KalshiCredentials
from pm_arb.core.models import (
    OrderBook,
    Side,
    Trade,
    TradeRequest,
    TradeStatus,
)


# --- Fixtures ---


def _generate_test_rsa_key() -> rsa.RSAPrivateKey:
    """Generate a 2048-bit RSA private key for testing."""
    return rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )


def _key_to_pem(key: rsa.RSAPrivateKey) -> str:
    """Serialize RSA key to PEM string."""
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


@pytest.fixture
def rsa_key() -> rsa.RSAPrivateKey:
    """Provide a test RSA private key."""
    return _generate_test_rsa_key()


@pytest.fixture
def rsa_pem(rsa_key: rsa.RSAPrivateKey) -> str:
    """Provide the PEM-encoded string of the test RSA key."""
    return _key_to_pem(rsa_key)


@pytest.fixture
def credentials(rsa_pem: str) -> KalshiCredentials:
    """Provide test KalshiCredentials."""
    return KalshiCredentials(
        api_key_id="test-api-key-id-12345",
        private_key=rsa_pem,
    )


@pytest.fixture
def adapter(credentials: KalshiCredentials) -> KalshiAdapter:
    """Provide a KalshiAdapter with test credentials."""
    return KalshiAdapter(credentials=credentials)


@pytest.fixture
def unauthenticated_adapter() -> KalshiAdapter:
    """Provide a KalshiAdapter without credentials."""
    return KalshiAdapter()


def _make_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
) -> httpx.Response:
    """Build a mock httpx.Response."""
    response = httpx.Response(
        status_code=status_code,
        json=json_data or {},
        request=httpx.Request("GET", "https://test.kalshi.com"),
    )
    return response


# --- Authentication / Signing Tests ---


class TestSignRequest:
    """Tests for RSA-PSS signature generation."""

    def test_sign_request_returns_required_headers(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Signing should produce all three Kalshi auth headers."""
        headers = adapter._sign_request("GET", "/trade-api/v2/markets")

        assert "KALSHI-ACCESS-KEY" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert "KALSHI-ACCESS-TIMESTAMP" in headers

    def test_sign_request_key_matches_api_key_id(
        self,
        adapter: KalshiAdapter,
        credentials: KalshiCredentials,
    ) -> None:
        """The access key header should match the configured API key ID."""
        headers = adapter._sign_request("GET", "/trade-api/v2/markets")
        assert headers["KALSHI-ACCESS-KEY"] == credentials.api_key_id

    def test_sign_request_timestamp_is_current_ms(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Timestamp should be a recent millisecond epoch value."""
        before_ms = int(time.time() * 1000)
        headers = adapter._sign_request("GET", "/trade-api/v2/exchange/status")
        after_ms = int(time.time() * 1000)

        ts = int(headers["KALSHI-ACCESS-TIMESTAMP"])
        assert before_ms <= ts <= after_ms

    def test_sign_request_signature_is_valid_base64(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Signature should be valid base64-encoded data."""
        headers = adapter._sign_request("GET", "/trade-api/v2/markets")
        sig_bytes = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])
        # RSA 2048-bit key produces 256-byte signatures
        assert len(sig_bytes) == 256

    def test_sign_request_signature_verifies(
        self,
        adapter: KalshiAdapter,
        rsa_key: rsa.RSAPrivateKey,
    ) -> None:
        """Signature should verify against the public key with PSS/SHA256."""
        method = "POST"
        path = "/trade-api/v2/portfolio/orders"

        headers = adapter._sign_request(method, path)

        timestamp_ms = headers["KALSHI-ACCESS-TIMESTAMP"]
        message = (timestamp_ms + method + path).encode("utf-8")
        signature = base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"])

        public_key = rsa_key.public_key()

        # This will raise InvalidSignature if verification fails
        public_key.verify(
            signature,
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_sign_request_without_credentials_raises(self) -> None:
        """Signing without credentials should raise RuntimeError."""
        adapter = KalshiAdapter()  # No credentials
        with pytest.raises(RuntimeError, match="No credentials provided"):
            adapter._sign_request("GET", "/trade-api/v2/markets")


# --- Connect / Disconnect Lifecycle Tests ---


class TestConnectDisconnect:
    """Tests for adapter lifecycle management."""

    @pytest.mark.asyncio
    async def test_connect_sets_connected(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """After connect, is_connected should be True."""
        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"trading_active": True}
            await adapter.connect()

        assert adapter.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_authenticates_with_credentials(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Connect with credentials should verify exchange status and set authenticated."""
        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"trading_active": True}
            await adapter.connect()

        assert adapter.is_authenticated is True
        mock_req.assert_called_once_with("GET", "/exchange/status")

    @pytest.mark.asyncio
    async def test_connect_without_credentials_not_authenticated(
        self,
        unauthenticated_adapter: KalshiAdapter,
    ) -> None:
        """Connect without credentials should not attempt authentication."""
        await unauthenticated_adapter.connect()

        assert unauthenticated_adapter.is_connected is True
        assert unauthenticated_adapter.is_authenticated is False

    @pytest.mark.asyncio
    async def test_connect_auth_failure_still_connected(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """If auth check fails, adapter should still be connected but not authenticated."""
        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.HTTPStatusError(
                "Unauthorized",
                request=httpx.Request("GET", "https://test.kalshi.com"),
                response=httpx.Response(401),
            )
            await adapter.connect()

        assert adapter.is_connected is True
        assert adapter.is_authenticated is False

    @pytest.mark.asyncio
    async def test_disconnect_resets_state(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Disconnect should reset connected, authenticated, and client state."""
        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"trading_active": True}
            await adapter.connect()

        await adapter.disconnect()

        assert adapter.is_connected is False
        assert adapter.is_authenticated is False
        assert adapter._client is None
        assert adapter._rsa_private_key is None


# --- get_markets Tests ---


class TestGetMarkets:
    """Tests for fetching and parsing Kalshi markets."""

    @pytest.mark.asyncio
    async def test_get_markets_parses_response(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Should parse Kalshi API response into Market objects."""
        mock_markets = [
            {
                "ticker": "BTCUSD-26FEB04-T104000",
                "title": "BTC above $104,000?",
                "rules_primary": "Resolves YES if Bitcoin closes above $104,000.",
                "yes_bid": 65,
                "no_bid": 35,
                "volume_24h": 5000,
                "open_interest": 12000,
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert len(markets) == 1

        market = markets[0]
        assert market.venue == "kalshi"
        assert market.id == "kalshi:BTCUSD-26FEB04-T104000"
        assert market.external_id == "BTCUSD-26FEB04-T104000"
        assert market.title == "BTC above $104,000?"
        assert market.description == "Resolves YES if Bitcoin closes above $104,000."

    @pytest.mark.asyncio
    async def test_get_markets_converts_cents_to_decimal(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Kalshi cent prices (0-99) should convert to Decimal fractions (0.00-1.00)."""
        mock_markets = [
            {
                "ticker": "TICKER-A",
                "title": "Test Market A",
                "yes_bid": 72,
                "no_bid": 28,
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert len(markets) == 1
        assert markets[0].yes_price == Decimal("0.72")
        assert markets[0].no_price == Decimal("0.28")

    @pytest.mark.asyncio
    async def test_get_markets_handles_zero_prices(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Markets with zero prices should still parse (edge case)."""
        mock_markets = [
            {
                "ticker": "TICKER-ZERO",
                "title": "Zero price market",
                "yes_bid": 0,
                "no_bid": 0,
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert len(markets) == 1
        assert markets[0].yes_price == Decimal("0")
        assert markets[0].no_price == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_markets_skips_missing_ticker(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Markets without a ticker should be skipped."""
        mock_markets = [
            {
                "title": "No ticker market",
                "yes_bid": 50,
                "no_bid": 50,
            },
            {
                "ticker": "VALID-TICKER",
                "title": "Valid market",
                "yes_bid": 60,
                "no_bid": 40,
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert len(markets) == 1
        assert markets[0].external_id == "VALID-TICKER"

    @pytest.mark.asyncio
    async def test_get_markets_volume_and_liquidity(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Volume and liquidity fields should be parsed correctly."""
        mock_markets = [
            {
                "ticker": "VOL-TEST",
                "title": "Volume test",
                "yes_bid": 50,
                "no_bid": 50,
                "volume_24h": 9500,
                "open_interest": 25000,
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert markets[0].volume_24h == Decimal("9500")
        assert markets[0].liquidity == Decimal("25000")

    @pytest.mark.asyncio
    async def test_get_markets_yes_price_fallback_to_yes_price_field(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Should fall back to yes_price if yes_bid is not present."""
        mock_markets = [
            {
                "ticker": "FALLBACK",
                "title": "Fallback test",
                "yes_price": 55,
                "no_price": 45,
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert len(markets) == 1
        assert markets[0].yes_price == Decimal("0.55")
        assert markets[0].no_price == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_get_markets_computes_complementary_price(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """If only yes_bid is present, no should be computed as 100 - yes."""
        mock_markets = [
            {
                "ticker": "COMPLEMENT",
                "title": "Complement test",
                "yes_bid": 73,
                # no_bid intentionally missing
            },
        ]

        with patch.object(adapter, "_fetch_markets", new_callable=AsyncMock) as mock:
            mock.return_value = mock_markets
            markets = await adapter.get_markets()

        assert len(markets) == 1
        assert markets[0].yes_price == Decimal("0.73")
        assert markets[0].no_price == Decimal("0.27")


# --- place_order Tests ---


class TestPlaceOrder:
    """Tests for order placement."""

    def _make_trade_request(self, **overrides: object) -> TradeRequest:
        """Build a TradeRequest with sensible defaults."""
        defaults = {
            "id": "req-001",
            "opportunity_id": "opp-001",
            "strategy": "test_strategy",
            "market_id": "kalshi:BTCUSD-26FEB04-T104000",
            "side": Side.BUY,
            "outcome": "YES",
            "amount": Decimal("10"),
            "max_price": Decimal("0.65"),
            "expected_edge": Decimal("0.03"),
        }
        defaults.update(overrides)
        return TradeRequest(**defaults)

    @pytest.mark.asyncio
    async def test_place_order_success(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Successful order should return a Trade with SUBMITTED status."""
        request = self._make_trade_request()

        order_response = {
            "order": {
                "order_id": "kalshi-order-abc123",
                "status": "resting",
                "ticker": "BTCUSD-26FEB04-T104000",
            }
        }

        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = order_response
            trade = await adapter.place_order(request)

        assert isinstance(trade, Trade)
        assert trade.venue == "kalshi"
        assert trade.status == TradeStatus.SUBMITTED
        assert trade.external_id == "kalshi-order-abc123"
        assert trade.request_id == "req-001"
        assert trade.side == Side.BUY
        assert trade.outcome == "YES"

    @pytest.mark.asyncio
    async def test_place_order_sends_correct_body(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Order request should convert price to cents and map fields correctly."""
        request = self._make_trade_request(
            outcome="YES",
            side=Side.BUY,
            max_price=Decimal("0.65"),
            amount=Decimal("10"),
        )

        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"order": {"order_id": "x", "status": "resting"}}
            await adapter.place_order(request)

        mock_req.assert_called_once_with(
            "POST",
            "/portfolio/orders",
            json={
                "ticker": "BTCUSD-26FEB04-T104000",
                "action": "buy",
                "side": "yes",
                "type": "limit",
                "count": 10,
                "yes_price": 65,
            },
        )

    @pytest.mark.asyncio
    async def test_place_order_no_outcome(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """NO outcome should set no_price in the order body."""
        request = self._make_trade_request(
            outcome="NO",
            max_price=Decimal("0.40"),
        )

        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"order": {"order_id": "x", "status": "resting"}}
            await adapter.place_order(request)

        call_kwargs = mock_req.call_args
        order_json = call_kwargs.kwargs["json"]
        assert order_json["side"] == "no"
        assert order_json["no_price"] == 40
        assert "yes_price" not in order_json

    @pytest.mark.asyncio
    async def test_place_order_sell_side(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """SELL side should map to action='sell'."""
        request = self._make_trade_request(side=Side.SELL)

        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"order": {"order_id": "x", "status": "resting"}}
            await adapter.place_order(request)

        call_kwargs = mock_req.call_args
        assert call_kwargs.kwargs["json"]["action"] == "sell"

    @pytest.mark.asyncio
    async def test_place_order_not_authenticated_raises(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Placing an order without auth should raise RuntimeError."""
        request = self._make_trade_request()

        # Adapter not authenticated (default state)
        with pytest.raises(RuntimeError, match="Not authenticated"):
            await adapter.place_order(request)

    @pytest.mark.asyncio
    async def test_place_order_api_error_returns_failed_trade(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """API errors should return a Trade with FAILED status, not raise."""
        request = self._make_trade_request()
        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.HTTPStatusError(
                "Forbidden",
                request=httpx.Request("POST", "https://test.kalshi.com"),
                response=httpx.Response(403),
            )
            trade = await adapter.place_order(request)

        assert trade.status == TradeStatus.FAILED
        assert trade.request_id == "req-001"
        assert trade.venue == "kalshi"

    @pytest.mark.asyncio
    async def test_place_order_executed_status(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Kalshi 'executed' status should map to TradeStatus.FILLED."""
        request = self._make_trade_request()
        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {
                "order": {
                    "order_id": "fill-123",
                    "status": "executed",
                },
            }
            trade = await adapter.place_order(request)

        assert trade.status == TradeStatus.FILLED


# --- get_balance Tests ---


class TestGetBalance:
    """Tests for balance retrieval."""

    @pytest.mark.asyncio
    async def test_get_balance_converts_cents_to_dollars(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Balance in cents should be converted to dollars."""
        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"balance": 150075}
            balance = await adapter.get_balance()

        assert balance == Decimal("1500.75")
        mock_req.assert_called_once_with("GET", "/portfolio/balance")

    @pytest.mark.asyncio
    async def test_get_balance_zero(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Zero balance should return Decimal('0')."""
        adapter._is_authenticated = True

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"balance": 0}
            balance = await adapter.get_balance()

        assert balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_balance_not_authenticated_raises(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Balance query without auth should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Not authenticated"):
            await adapter.get_balance()


# --- get_order_book Tests ---


class TestGetOrderBook:
    """Tests for order book fetching and parsing."""

    @pytest.mark.asyncio
    async def test_get_order_book_parses_levels(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Order book levels should be parsed and price-converted from cents."""
        adapter._client = MagicMock()  # Fake connected state

        api_response = {
            "orderbook": {
                "yes": [[65, 100], [60, 200], [55, 150]],
                "no": [[35, 100], [40, 200], [45, 150]],
            }
        }

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = api_response
            book = await adapter.get_order_book("kalshi:TICKER-X", "YES")

        assert book is not None
        assert isinstance(book, OrderBook)
        assert book.market_id == "kalshi:TICKER-X"

        # Bids sorted high to low
        assert len(book.bids) == 3
        assert book.bids[0].price == Decimal("0.65")
        assert book.bids[0].size == Decimal("100")
        assert book.bids[1].price == Decimal("0.60")
        assert book.bids[2].price == Decimal("0.55")

        # Asks sorted low to high
        assert len(book.asks) == 3
        assert book.asks[0].price == Decimal("0.35")
        assert book.asks[1].price == Decimal("0.40")
        assert book.asks[2].price == Decimal("0.45")

    @pytest.mark.asyncio
    async def test_get_order_book_empty(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Empty order book should return an OrderBook with empty lists."""
        adapter._client = MagicMock()

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"orderbook": {"yes": [], "no": []}}
            book = await adapter.get_order_book("kalshi:EMPTY", "YES")

        assert book is not None
        assert len(book.bids) == 0
        assert len(book.asks) == 0

    @pytest.mark.asyncio
    async def test_get_order_book_http_error_returns_none(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """HTTP errors should return None, not raise."""
        adapter._client = MagicMock()

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=httpx.Request("GET", "https://test.kalshi.com"),
                response=httpx.Response(404),
            )
            book = await adapter.get_order_book("kalshi:MISSING", "YES")

        assert book is None

    @pytest.mark.asyncio
    async def test_get_order_book_extracts_ticker_from_market_id(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Should extract ticker from 'kalshi:TICKER' format for the API call."""
        adapter._client = MagicMock()

        with patch.object(adapter, "_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"orderbook": {"yes": [], "no": []}}
            await adapter.get_order_book("kalshi:MY-TICKER-123", "YES")

        mock_req.assert_called_once_with("GET", "/markets/MY-TICKER-123/orderbook")


# --- Error Handling Tests ---


class TestErrorHandling:
    """Tests for graceful error handling."""

    @pytest.mark.asyncio
    async def test_request_not_connected_raises(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Making a request when not connected should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter._request("GET", "/markets")

    @pytest.mark.asyncio
    async def test_request_propagates_http_errors(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """Non-2xx responses should raise httpx.HTTPStatusError."""
        adapter._client = httpx.AsyncClient()

        mock_response = httpx.Response(
            status_code=500,
            json={"error": "Internal Server Error"},
            request=httpx.Request("GET", "https://api.elections.kalshi.com/trade-api/v2/markets"),
        )

        with patch.object(adapter._client, "request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_response

            with pytest.raises(httpx.HTTPStatusError):
                await adapter._request("GET", "/markets")

        await adapter._client.aclose()


# --- Adapter Properties Tests ---


class TestAdapterProperties:
    """Tests for adapter name and basic properties."""

    def test_name_is_kalshi(self) -> None:
        """Adapter name should be 'kalshi'."""
        adapter = KalshiAdapter()
        assert adapter.name == "kalshi"

    def test_initial_state_not_connected(self) -> None:
        """Fresh adapter should not be connected or authenticated."""
        adapter = KalshiAdapter()
        assert adapter.is_connected is False
        assert adapter.is_authenticated is False

    @pytest.mark.asyncio
    async def test_subscribe_prices_noop(
        self,
        adapter: KalshiAdapter,
    ) -> None:
        """subscribe_prices should be a no-op placeholder (no exception)."""
        await adapter.subscribe_prices(["kalshi:TICKER-1", "kalshi:TICKER-2"])
