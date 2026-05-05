import asyncio
import logging
from typing import Callable, Awaitable, Protocol

from parallax.execution.schemas import OrderbookSnapshot
from parallax.execution.kalshi_book_client import KalshiBookClient
from parallax.execution.polymarket_book_client import PolymarketBookClient

logger = logging.getLogger(__name__)

class BaseStreamer(Protocol):
    orderbooks: dict[str, OrderbookSnapshot]
    
    def subscribe(self, callback: Callable[[str], Awaitable[None]]) -> None: ...
    async def start(self, market_registry: dict[str, dict]) -> None: ...
    async def stop(self) -> None: ...

class OrderbookStreamer(BaseStreamer):
    def __init__(self):
        self.orderbooks: dict[str, OrderbookSnapshot] = {}
        self.callbacks: list[Callable[[str], Awaitable[None]]] = []
        self._running = False
        
        self.polymarket_client = PolymarketBookClient(self.update_snapshot)
        self.kalshi_client = KalshiBookClient(self.update_snapshot)

    def subscribe(self, callback: Callable[[str], Awaitable[None]]):
        """Add a callback to be invoked when a market orderbook updates."""
        self.callbacks.append(callback)

    async def _emit(self, market_id: str):
        for cb in self.callbacks:
            try:
                await cb(market_id)
            except Exception as e:
                logger.error(f"Error in streamer callback for {market_id}: {e}")

    async def update_snapshot(self, market_id: str, snapshot: OrderbookSnapshot):
        """Called by clients when a new snapshot is generated from the stream."""
        self.orderbooks[market_id] = snapshot
        await self._emit(market_id)

    async def start(self, market_registry: dict[str, dict]):
        """
        Starts the WebSocket listeners for the specified markets.
        market_registry is a mapping: market_id -> {"token_id": "...", "platform": "...", "ticker": "..."}
        """
        self._running = True
        logger.info(f"Starting OrderbookStreamer for {len(market_registry)} markets")
        
        self.polymarket_client.add_markets(market_registry)
        self.kalshi_client.add_markets(market_registry)
        
        asyncio.create_task(self.polymarket_client.start())
        asyncio.create_task(self.kalshi_client.start())

    async def stop(self):
        self._running = False
        await self.polymarket_client.stop()
        await self.kalshi_client.stop()
