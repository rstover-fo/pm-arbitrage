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


def load_credentials(venue: str) -> PolymarketCredentials:
    """Load credentials from environment variables or settings.

    Credentials are loaded from environment variables first, falling back
    to pydantic-settings (which loads from .env file).

    Args:
        venue: Venue name (e.g., "polymarket")

    Returns:
        Credentials object for the venue

    Raises:
        ValueError: If required credentials are missing
    """
    # Import settings here to avoid circular import
    from pm_arb.core.config import settings

    prefix = venue.upper()

    # Try environment variables first, fall back to settings
    api_key = os.environ.get(f"{prefix}_API_KEY") or (
        settings.polymarket_api_key if venue == "polymarket" else ""
    )
    secret = os.environ.get(f"{prefix}_SECRET") or (
        settings.polymarket_secret if venue == "polymarket" else ""
    )
    passphrase = os.environ.get(f"{prefix}_PASSPHRASE") or (
        settings.polymarket_passphrase if venue == "polymarket" else ""
    )
    private_key = os.environ.get(f"{prefix}_PRIVATE_KEY") or (
        settings.polymarket_private_key if venue == "polymarket" else ""
    )

    missing = []
    if not api_key:
        missing.append(f"{prefix}_API_KEY")
    if not secret:
        missing.append(f"{prefix}_SECRET")
    if not passphrase:
        missing.append(f"{prefix}_PASSPHRASE")
    if not private_key:
        missing.append(f"{prefix}_PRIVATE_KEY")

    if missing:
        raise ValueError(f"Missing required credentials: {', '.join(missing)}")

    return PolymarketCredentials(
        api_key=api_key,
        secret=secret,
        passphrase=passphrase,
        private_key=private_key,
    )
