"""Tests for pilot orchestrator."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pm_arb.core.market_matcher import MatchResult
from pm_arb.pilot import PilotOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_starts_agents(redis_url, test_db_pool):
    """Test that orchestrator starts all agents."""
    with (
        patch("pm_arb.pilot.PolymarketAdapter") as mock_poly_cls,
        patch("pm_arb.pilot.BinanceOracle") as mock_binance_cls,
        patch("pm_arb.pilot.MarketMatcher") as mock_matcher_cls,
        patch("pm_arb.pilot.init_db", new_callable=AsyncMock),
        patch("pm_arb.pilot.get_pool", new_callable=AsyncMock),
    ):
        # Configure mock Polymarket adapter
        mock_poly = AsyncMock()
        mock_poly.connect = AsyncMock()
        mock_poly.disconnect = AsyncMock()
        mock_poly.get_markets = AsyncMock(return_value=[])
        mock_poly.is_connected = True
        mock_poly_cls.return_value = mock_poly

        # Configure mock Binance oracle
        mock_binance = MagicMock()
        mock_binance.name = "binance"
        mock_binance_cls.return_value = mock_binance

        # Configure mock matcher
        mock_matcher = MagicMock()
        mock_matcher.match_markets = AsyncMock(
            return_value=MatchResult(
                total_markets=0, matched=0, skipped=0, failed=0, matched_markets=[]
            )
        )
        mock_matcher_cls.return_value = mock_matcher

        orchestrator = PilotOrchestrator(
            redis_url=redis_url,
            db_pool=test_db_pool,
        )

        # Start in background
        task = asyncio.create_task(orchestrator.run())

        # Give agents time to start
        await asyncio.sleep(0.5)

        # Verify agents are running
        assert orchestrator.is_running
        assert len(orchestrator.agents) >= 5

        # Stop gracefully
        await orchestrator.stop()
        await task


@pytest.mark.asyncio
async def test_orchestrator_health_check(redis_url, test_db_pool):
    """Test that orchestrator reports health status."""
    with (
        patch("pm_arb.pilot.PolymarketAdapter") as mock_poly_cls,
        patch("pm_arb.pilot.BinanceOracle") as mock_binance_cls,
        patch("pm_arb.pilot.MarketMatcher") as mock_matcher_cls,
        patch("pm_arb.pilot.init_db", new_callable=AsyncMock),
        patch("pm_arb.pilot.get_pool", new_callable=AsyncMock),
    ):
        # Configure mock Polymarket adapter
        mock_poly = AsyncMock()
        mock_poly.connect = AsyncMock()
        mock_poly.disconnect = AsyncMock()
        mock_poly.get_markets = AsyncMock(return_value=[])
        mock_poly.is_connected = True
        mock_poly_cls.return_value = mock_poly

        # Configure mock Binance oracle
        mock_binance = MagicMock()
        mock_binance.name = "binance"
        mock_binance_cls.return_value = mock_binance

        # Configure mock matcher
        mock_matcher = MagicMock()
        mock_matcher.match_markets = AsyncMock(
            return_value=MatchResult(
                total_markets=0, matched=0, skipped=0, failed=0, matched_markets=[]
            )
        )
        mock_matcher_cls.return_value = mock_matcher

        orchestrator = PilotOrchestrator(
            redis_url=redis_url,
            db_pool=test_db_pool,
        )

        task = asyncio.create_task(orchestrator.run())
        await asyncio.sleep(0.5)

        health = orchestrator.get_health()
        assert "agents" in health
        assert "uptime_seconds" in health

        await orchestrator.stop()
        await task


class TestPilotMarketMatching:
    """Tests for market matching integration in pilot."""

    @pytest.mark.asyncio
    async def test_matches_markets_before_scanning(self) -> None:
        """Should match markets after creating agents but before running."""
        with (
            patch("pm_arb.pilot.PolymarketAdapter") as mock_adapter_cls,
            patch("pm_arb.pilot.BinanceOracle"),
            patch("pm_arb.pilot.MarketMatcher") as mock_matcher_cls,
            patch("pm_arb.pilot.init_db", new_callable=AsyncMock),
            patch("pm_arb.pilot.get_pool", new_callable=AsyncMock),
        ):
            # Setup mock adapter
            mock_adapter = AsyncMock()
            mock_adapter.get_markets = AsyncMock(return_value=[])
            mock_adapter_cls.return_value = mock_adapter

            # Setup mock matcher
            mock_matcher = MagicMock()
            mock_matcher.match_markets = AsyncMock(
                return_value=MatchResult(
                    total_markets=0,
                    matched=0,
                    skipped=0,
                    failed=0,
                    matched_markets=[],
                )
            )
            mock_matcher_cls.return_value = mock_matcher

            orchestrator = PilotOrchestrator(redis_url="redis://localhost:6379")

            # Run briefly then stop
            async def run_and_stop() -> None:
                task = asyncio.create_task(orchestrator.run())
                await asyncio.sleep(0.1)
                await orchestrator.stop()
                await task

            await run_and_stop()

            # Verify matcher was called
            mock_matcher.match_markets.assert_called_once()
