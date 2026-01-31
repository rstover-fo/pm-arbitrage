"""Tests for Opportunity Scanner agent."""

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.agents.opportunity_scanner import OpportunityScannerAgent
from pm_arb.core.models import Market, OpportunityType


@pytest.mark.asyncio
async def test_scanner_subscribes_to_channels() -> None:
    """Scanner should subscribe to venue and oracle channels."""
    agent = OpportunityScannerAgent(
        redis_url="redis://localhost:6379",
        venue_channels=["venue.polymarket.prices"],
        oracle_channels=["oracle.binance.BTC"],
    )

    subs = agent.get_subscriptions()

    assert "venue.polymarket.prices" in subs
    assert "oracle.binance.BTC" in subs
