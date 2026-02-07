"""Authentication and credential management for venue APIs."""

import os
import re
from typing import Any

from pydantic import BaseModel, field_validator


class PolymarketCredentials(BaseModel):
    """Credentials for Polymarket CLOB API."""

    api_key: str
    secret: str
    passphrase: str
    private_key: str  # Ethereum private key for signing

    @field_validator("private_key")
    @classmethod
    def validate_private_key(cls, v: str) -> str:
        """Validate private key format."""
        if not re.match(r"^0x[a-fA-F0-9]{64}$", v):
            raise ValueError("Invalid private key format (expected 0x + 64 hex chars)")
        return v

    def __str__(self) -> str:
        """Mask secrets in string representation."""
        return f"PolymarketCredentials(api_key={self.api_key[:8]}...)"

    def __repr__(self) -> str:
        return self.__str__()

    def to_client_args(self) -> dict[str, Any]:
        """Return dict suitable for py-clob-client initialization."""
        return {
            "key": self.api_key,
            "secret": self.secret,
            "passphrase": self.passphrase,
            "private_key": self.private_key,
        }


class KalshiCredentials(BaseModel):
    """Credentials for Kalshi API (RSA key-based authentication)."""

    api_key_id: str
    private_key: str  # RSA PEM-formatted private key

    @field_validator("private_key")
    @classmethod
    def validate_private_key(cls, v: str) -> str:
        """Validate that private_key contains PEM BEGIN/END markers."""
        if "-----BEGIN" not in v or "-----END" not in v:
            raise ValueError(
                "Invalid private key format: expected PEM-encoded key "
                "with BEGIN/END markers"
            )
        return v

    def __str__(self) -> str:
        """Mask secrets in string representation."""
        return f"KalshiCredentials(api_key_id={self.api_key_id[:12]}...)"

    def __repr__(self) -> str:
        return self.__str__()


def load_credentials(venue: str) -> PolymarketCredentials | KalshiCredentials:
    """Load credentials from environment variables or settings.

    Credentials are loaded from environment variables first, falling back
    to pydantic-settings (which loads from .env file).

    Args:
        venue: Venue name (e.g., "polymarket", "kalshi")

    Returns:
        Credentials object for the venue

    Raises:
        ValueError: If required credentials are missing or venue is unsupported
    """
    if venue == "polymarket":
        return _load_polymarket_credentials()
    elif venue == "kalshi":
        return _load_kalshi_credentials()
    else:
        raise ValueError(f"Unsupported venue: {venue}")


def _load_polymarket_credentials() -> PolymarketCredentials:
    """Load Polymarket credentials from env vars or settings."""
    # Import settings here to avoid circular import
    from pm_arb.core.config import settings

    api_key = os.environ.get("POLYMARKET_API_KEY") or settings.polymarket_api_key
    secret = os.environ.get("POLYMARKET_SECRET") or settings.polymarket_secret
    passphrase = os.environ.get("POLYMARKET_PASSPHRASE") or settings.polymarket_passphrase
    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY") or settings.polymarket_private_key

    missing = []
    if not api_key:
        missing.append("POLYMARKET_API_KEY")
    if not secret:
        missing.append("POLYMARKET_SECRET")
    if not passphrase:
        missing.append("POLYMARKET_PASSPHRASE")
    if not private_key:
        missing.append("POLYMARKET_PRIVATE_KEY")

    if missing:
        raise ValueError(f"Missing required credentials: {', '.join(missing)}")

    return PolymarketCredentials(
        api_key=api_key,
        secret=secret,
        passphrase=passphrase,
        private_key=private_key,
    )


def _load_kalshi_credentials() -> KalshiCredentials:
    """Load Kalshi credentials from env vars or settings."""
    # Import settings here to avoid circular import
    from pm_arb.core.config import settings

    api_key_id = os.environ.get("KALSHI_API_KEY_ID") or settings.kalshi_api_key_id
    private_key = os.environ.get("KALSHI_PRIVATE_KEY") or settings.kalshi_private_key

    missing = []
    if not api_key_id:
        missing.append("KALSHI_API_KEY_ID")
    if not private_key:
        missing.append("KALSHI_PRIVATE_KEY")

    if missing:
        raise ValueError(f"Missing required credentials: {', '.join(missing)}")

    return KalshiCredentials(
        api_key_id=api_key_id,
        private_key=private_key,
    )
