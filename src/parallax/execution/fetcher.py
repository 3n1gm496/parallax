from __future__ import annotations

from parallax.config import Settings
from parallax.execution.clob_adapter import PolymarketCLOBAdapter
from parallax.execution.kalshi_quote_adapter import KalshiQuoteAdapter
from parallax.execution.schemas import OrderbookSnapshot


class OrderbookFetcher:
    """
    Unified entry point: given (platform, market_id, outcome, token_id),
    dispatch to the correct adapter and return a snapshot or None.
    """

    def __init__(
        self,
        settings: Settings,
        polymarket_adapter: PolymarketCLOBAdapter | None = None,
        kalshi_adapter: KalshiQuoteAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._poly = polymarket_adapter or PolymarketCLOBAdapter(
            timeout=settings.orderbook_fetch_timeout_seconds
        )
        self._kalshi = kalshi_adapter or KalshiQuoteAdapter(
            timeout=settings.orderbook_fetch_timeout_seconds,
            api_key=settings.kalshi_api_key,
        )

    async def fetch(
        self,
        platform: str,
        market_id: str,
        outcome: str,
        token_id: str | None = None,
    ) -> OrderbookSnapshot | None:
        if not self._settings.orderbook_enabled:
            return None
        if platform == "polymarket":
            if not token_id:
                return None
            return await self._poly.fetch_snapshot(market_id, outcome, token_id)
        if platform == "kalshi":
            return await self._kalshi.fetch_snapshot(market_id, outcome)
        return None
