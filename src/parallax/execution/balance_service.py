import anyio
import logging
from typing import Dict
from parallax.config import settings

logger = logging.getLogger(__name__)

class BalanceService:
    """Tracks and caches balances across multiple venues."""
    
    def __init__(self, kalshi_client, polymarket_client):
        self.kalshi = kalshi_client
        self.polymarket = polymarket_client
        self._balances: Dict[str, float] = {
            "kalshi": 0.0,
            "polymarket": 0.0,
            "pm": 0.0,
        }
        self._last_updated: Dict[str, float] = {}

    async def refresh_all(self):
        """Update balances from all venues concurrently."""
        async with anyio.create_task_group() as tg:
            tg.start_soon(self._refresh_kalshi)
            tg.start_soon(self._refresh_polymarket)

    async def _refresh_kalshi(self):
        try:
            balance = await self.kalshi.get_balance()
            if balance is not None:
                self._balances["kalshi"] = balance
                logger.info(f"Kalshi balance refreshed: ${balance:.2f}")
        except Exception as e:
            logger.error(f"Failed to refresh Kalshi balance: {e}")

    async def _refresh_polymarket(self):
        try:
            balance = await self.polymarket.get_balance()
            if balance is not None:
                self._balances["polymarket"] = balance
                self._balances["pm"] = balance
                logger.info(f"Polymarket balance refreshed: {balance:.2f} USDC")
        except Exception as e:
            logger.error(f"Failed to refresh Polymarket balance: {e}")

    def get_balance(self, venue: str) -> float:
        return self._balances.get(venue, 0.0)

    def has_sufficient_funds(self, venue: str, amount: float) -> bool:
        """Check if a venue has enough funds for an operation."""
        # Add a small buffer (e.g. 1% or $1) for fees/slippage if not already in amount
        return self.get_balance(venue) >= amount
