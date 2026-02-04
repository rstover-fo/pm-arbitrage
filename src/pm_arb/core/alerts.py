"""Alert service for trade notifications via Pushover."""

from enum import Enum

import httpx
import structlog

from pm_arb.core.config import settings

logger = structlog.get_logger()

PUSHOVER_API = "https://api.pushover.net/1/messages.json"


class AlertPriority(Enum):
    """Pushover alert priority levels."""

    LOW = -1  # Quiet hours respected
    NORMAL = 0  # Standard notification
    HIGH = 1  # Bypasses quiet hours
    CRITICAL = 2  # Requires acknowledgment


class AlertService:
    """Send alerts via Pushover."""

    def __init__(
        self,
        user_key: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self._user_key = user_key or settings.pushover_user_key
        self._api_token = api_token or settings.pushover_api_token
        self._enabled = bool(self._user_key and self._api_token)

        if not self._enabled:
            logger.warning("alerts_disabled", reason="Missing Pushover credentials")

    @property
    def is_enabled(self) -> bool:
        """Whether alerts are enabled."""
        return self._enabled

    async def send(
        self,
        title: str,
        message: str,
        priority: AlertPriority = AlertPriority.NORMAL,
        url: str | None = None,
    ) -> bool:
        """Send an alert notification.

        Args:
            title: Alert title (shown prominently)
            message: Alert body
            priority: Pushover priority level
            url: Optional URL to include

        Returns:
            True if sent successfully, False otherwise
        """
        if not self._enabled:
            logger.debug("alert_skipped", title=title, reason="disabled")
            return False

        payload: dict[str, str | int] = {
            "token": self._api_token or "",
            "user": self._user_key or "",
            "title": title,
            "message": message,
            "priority": priority.value,
        }

        if url:
            payload["url"] = url

        # Critical alerts require retry/expire params
        if priority == AlertPriority.CRITICAL:
            payload["retry"] = 60  # Retry every 60s
            payload["expire"] = 3600  # For 1 hour

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(PUSHOVER_API, data=payload)
                response.raise_for_status()
                logger.info("alert_sent", title=title, priority=priority.name)
                return True
        except Exception as e:
            logger.error("alert_failed", title=title, error=str(e))
            return False

    # Convenience methods for common alert types

    async def trade_executed(
        self,
        market: str,
        side: str,
        amount: str,
        price: str,
        pnl: str | None = None,
    ) -> bool:
        """Alert for successful trade execution."""
        msg = f"{side.upper()} ${amount} @ {price}"
        if pnl:
            msg += f"\nP&L: {pnl}"
        return await self.send(
            title=f"Trade: {market[:30]}",
            message=msg,
            priority=AlertPriority.NORMAL,
        )

    async def trade_failed(self, market: str, error: str) -> bool:
        """Alert for failed trade."""
        return await self.send(
            title="Trade FAILED",
            message=f"{market[:30]}\n{error}",
            priority=AlertPriority.HIGH,
        )

    async def agent_crash(self, agent_name: str, error: str) -> bool:
        """Alert for agent crash."""
        return await self.send(
            title=f"CRASH: {agent_name}",
            message=error[:200],
            priority=AlertPriority.CRITICAL,
        )

    async def agent_dead(self, agent_name: str, max_restarts: int) -> bool:
        """Alert for agent exceeding max restarts."""
        return await self.send(
            title=f"AGENT DEAD: {agent_name}",
            message=f"Max restarts ({max_restarts}) exceeded. Manual intervention required.",
            priority=AlertPriority.CRITICAL,
        )

    async def drawdown_halt(self, current_value: str, limit: str) -> bool:
        """Alert for drawdown halt."""
        return await self.send(
            title="TRADING HALTED",
            message=f"Drawdown limit exceeded\nValue: {current_value}\nLimit: {limit}",
            priority=AlertPriority.CRITICAL,
        )

    async def daily_summary(
        self,
        trades: int,
        pnl: str,
        positions: int,
    ) -> bool:
        """Daily summary alert."""
        return await self.send(
            title="Daily Summary",
            message=f"Trades: {trades}\nP&L: {pnl}\nOpen positions: {positions}",
            priority=AlertPriority.LOW,
        )

    async def startup(self, mode: str, balance: str | None = None) -> bool:
        """Alert for system startup."""
        msg = f"Mode: {mode}"
        if balance:
            msg += f"\nBalance: ${balance}"
        return await self.send(
            title="PM-ARB Started",
            message=msg,
            priority=AlertPriority.LOW,
        )
