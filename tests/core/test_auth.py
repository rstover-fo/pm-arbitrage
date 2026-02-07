"""Tests for wallet authentication models."""

import os
from unittest.mock import patch

import pytest

from pm_arb.core.auth import KalshiCredentials, PolymarketCredentials, load_credentials

# ---------------------------------------------------------------------------
# Sample RSA PEM key for testing (not a real credential)
# ---------------------------------------------------------------------------
SAMPLE_RSA_PEM = """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/ygWyF0PbnGcY5unA67hqxnfZoGMaEclq
sPDkfPDHBFkFBHVzKhZ9FsNm3JCBnMSCr0bAkFHG/WF0HLuF4rJpGfHsbiHBCdm
e5M0EFAsUQBcMn2bNBIjYoRHhJeTrMBk5vRANml0ISIN1bGOm2cEr7RYYQ2Xf5jD
mJKwC1y1H7k6eFNTGCIQCXNJ8LJXbhFSbNzA8b1K6cBOHsm5jVNlcE9xJgN5PMd
bQV5cHWRaFHq5UMRMiN4eFqH4MBjb5hMFLEL9VkZVjT9BMSEQ5bKZ5LJJxm5eJg
gOrVWX5TYRYJCjRUFQ9ivNMqIF3raC5R3bBXrwIDAQABAKCAQB0T4GY5VxZ1MFUP
QiPNTmGRAWZbqXBPNJFafcDBgI7N7aFHROiuz0NP6kfumY3UX0xsXhmGtkCdGw4V
j1Pgcb5F5dMXMbvNLSKJF6I0j3yKkLFTbKKHA1E3N7SlKGMFCfRN0RHVH5S0SQ8h
qJFhaJF8dXAFmiig0W5TSMxMl4RWdL2YB0L0slbuJPqDvdPNCfQKT9r8EbhHR4GY
Q1KcRG0GBuGN0XOEVDQh/piDrMHz1RCHPQLzQJFaWnPrSMqPHbTcv8jiHV3pg3xL
DFIW+UbWA7CRP1bDSvsC2K4yMdp7c3FvraGCGBESixkEVcJFRFz/c3EFHB6tAZfp
B2POR7GBAoGBAPH/hJX5x6h5X7c7xS+uhR/72dKkq2rK+8T7HTxc85/0EFwbi7JI
qMwDSM15IyFLAB3Y0FPKvDMGLGmaN/gH4KBq/tFp0dGUfBJ3RnIGE3dIaFO8cP6B
aN4+VIJbF+k1LmCLECqGFi5LGMTh9VlIiUNnFtsi9vBLFoJ0rEsPAoGBANyOhkAG
mGDkBaJhXMKkCr0L1EKMaC1aSIHz+E/Excp0iFpmP8K3JjJMfteACVjMyfFrXwnJ
test12345678901234567890123456789012345678901234567890==
-----END RSA PRIVATE KEY-----""".strip()


def test_credentials_from_env() -> None:
    """Should load credentials from environment variables."""
    private_key = "0x" + "1234567890abcdef" * 4
    with patch.dict(
        os.environ,
        {
            "POLYMARKET_API_KEY": "test-api-key",
            "POLYMARKET_SECRET": "test-secret",
            "POLYMARKET_PASSPHRASE": "test-passphrase",
            "POLYMARKET_PRIVATE_KEY": private_key,
        },
    ):
        creds = load_credentials("polymarket")

    assert creds.api_key == "test-api-key"
    assert creds.secret == "test-secret"
    assert creds.passphrase == "test-passphrase"
    assert creds.private_key == private_key


def test_credentials_validates_private_key() -> None:
    """Should reject invalid private key format."""
    with pytest.raises(ValueError, match="Invalid private key"):
        PolymarketCredentials(
            api_key="test",
            secret="test",
            passphrase="test",
            private_key="not-a-valid-key",
        )


def test_credentials_masks_secrets() -> None:
    """Should not expose secrets in string representation."""
    creds = PolymarketCredentials(
        api_key="test-api-key",
        secret="test-secret",
        passphrase="test-passphrase",
        private_key="0x" + "a" * 64,
    )

    str_repr = str(creds)
    assert "test-secret" not in str_repr
    assert "test-passphrase" not in str_repr
    assert "aaaa" not in str_repr


def test_credentials_missing_env_vars() -> None:
    """Should raise error when credentials are missing."""
    mock_settings = type("MockSettings", (), {
        "polymarket_api_key": "",
        "polymarket_secret": "",
        "polymarket_passphrase": "",
        "polymarket_private_key": "",
    })()

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("pm_arb.core.config.settings", mock_settings),
    ):
        with pytest.raises(ValueError, match="Missing required credentials"):
            load_credentials("polymarket")


def test_to_client_args() -> None:
    """Should return dict suitable for py-clob-client."""
    creds = PolymarketCredentials(
        api_key="test-api-key",
        secret="test-secret",
        passphrase="test-passphrase",
        private_key="0x" + "a" * 64,
    )

    args = creds.to_client_args()
    assert args["key"] == "test-api-key"
    assert args["secret"] == "test-secret"
    assert args["passphrase"] == "test-passphrase"
    assert args["private_key"] == "0x" + "a" * 64


# ---------------------------------------------------------------------------
# KalshiCredentials model tests
# ---------------------------------------------------------------------------


class TestKalshiCredentials:
    """Tests for KalshiCredentials Pydantic model."""

    def test_valid_pem_key_accepted(self) -> None:
        """Should accept a well-formed RSA PEM private key."""
        creds = KalshiCredentials(
            api_key_id="my-kalshi-key-id",
            private_key=SAMPLE_RSA_PEM,
        )
        assert creds.api_key_id == "my-kalshi-key-id"
        assert "BEGIN" in creds.private_key
        assert "END" in creds.private_key

    def test_invalid_pem_key_rejected(self) -> None:
        """Should reject a private key that lacks PEM markers."""
        with pytest.raises(ValueError, match="PEM"):
            KalshiCredentials(
                api_key_id="my-kalshi-key-id",
                private_key="not-a-valid-pem-key",
            )

    def test_ec_pem_key_accepted(self) -> None:
        """Should accept an EC PEM private key (BEGIN EC PRIVATE KEY)."""
        ec_pem = (
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHQCAQEEIBkg4LVWM9nuwNSk3yByxZpYRTBnVkxJBEMaU7LBZL+coAcGBSuB\n"
            "-----END EC PRIVATE KEY-----"
        )
        creds = KalshiCredentials(
            api_key_id="ec-key-id",
            private_key=ec_pem,
        )
        assert creds.api_key_id == "ec-key-id"

    def test_masks_secrets_in_str(self) -> None:
        """Should not expose the private key or full key id in str."""
        creds = KalshiCredentials(
            api_key_id="my-kalshi-key-id-full",
            private_key=SAMPLE_RSA_PEM,
        )
        str_repr = str(creds)
        assert "BEGIN" not in str_repr
        assert "my-kalshi-key-id-full" not in str_repr
        # Should show truncated key id
        assert "my-kalshi" in str_repr

    def test_masks_secrets_in_repr(self) -> None:
        """repr should behave like str."""
        creds = KalshiCredentials(
            api_key_id="my-kalshi-key-id-full",
            private_key=SAMPLE_RSA_PEM,
        )
        assert repr(creds) == str(creds)


# ---------------------------------------------------------------------------
# load_credentials("kalshi") tests
# ---------------------------------------------------------------------------


class TestLoadKalshiCredentials:
    """Tests for load_credentials with venue='kalshi'."""

    def test_loads_from_env_vars(self) -> None:
        """Should load Kalshi credentials from environment variables."""
        with patch.dict(
            os.environ,
            {
                "KALSHI_API_KEY_ID": "env-key-id",
                "KALSHI_PRIVATE_KEY": SAMPLE_RSA_PEM,
            },
        ):
            creds = load_credentials("kalshi")

        assert isinstance(creds, KalshiCredentials)
        assert creds.api_key_id == "env-key-id"
        assert creds.private_key == SAMPLE_RSA_PEM

    def test_falls_back_to_settings(self) -> None:
        """Should fall back to settings when env vars are absent."""
        mock_settings = type(
            "MockSettings",
            (),
            {
                "kalshi_api_key_id": "settings-key-id",
                "kalshi_private_key": SAMPLE_RSA_PEM,
            },
        )()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("pm_arb.core.config.settings", mock_settings),
        ):
            creds = load_credentials("kalshi")

        assert isinstance(creds, KalshiCredentials)
        assert creds.api_key_id == "settings-key-id"

    def test_raises_on_missing_credentials(self) -> None:
        """Should raise ValueError when Kalshi credentials are missing."""
        mock_settings = type(
            "MockSettings",
            (),
            {
                "kalshi_api_key_id": "",
                "kalshi_private_key": "",
            },
        )()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("pm_arb.core.config.settings", mock_settings),
        ):
            with pytest.raises(ValueError, match="Missing required credentials"):
                load_credentials("kalshi")

    def test_raises_on_partial_credentials(self) -> None:
        """Should raise ValueError when only some Kalshi credentials are set."""
        mock_settings = type(
            "MockSettings",
            (),
            {
                "kalshi_api_key_id": "has-key-id",
                "kalshi_private_key": "",
            },
        )()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("pm_arb.core.config.settings", mock_settings),
        ):
            with pytest.raises(ValueError, match="KALSHI_PRIVATE_KEY"):
                load_credentials("kalshi")


# ---------------------------------------------------------------------------
# load_credentials("polymarket") still works
# ---------------------------------------------------------------------------


class TestLoadPolymarketStillWorks:
    """Ensure Polymarket credential loading is unchanged."""

    def test_polymarket_from_env(self) -> None:
        """Should still load Polymarket credentials from env vars."""
        private_key = "0x" + "abcdef01" * 8
        with patch.dict(
            os.environ,
            {
                "POLYMARKET_API_KEY": "pm-key",
                "POLYMARKET_SECRET": "pm-secret",
                "POLYMARKET_PASSPHRASE": "pm-pass",
                "POLYMARKET_PRIVATE_KEY": private_key,
            },
        ):
            creds = load_credentials("polymarket")

        assert isinstance(creds, PolymarketCredentials)
        assert creds.api_key == "pm-key"


class TestLoadUnsupportedVenue:
    """Unsupported venues should fail gracefully."""

    def test_unsupported_venue_raises(self) -> None:
        """Should raise ValueError for unknown venue names."""
        with pytest.raises(ValueError, match="Unsupported venue"):
            load_credentials("binance")
