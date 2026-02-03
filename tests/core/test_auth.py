"""Tests for wallet authentication models."""

import os
from unittest.mock import patch

import pytest

from pm_arb.core.auth import PolymarketCredentials, load_credentials


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
    with patch.dict(os.environ, {}, clear=True):
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
