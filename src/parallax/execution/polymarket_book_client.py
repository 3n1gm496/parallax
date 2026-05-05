import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Coroutine

import websockets
from websockets.exceptions import ConnectionClosed

from parallax.config import settings
from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot

logger = logging.getLogger(__name__)

class PolymarketBookClient:
    """Connects to Polymarket CLOB WebSocket to stream orderbook data."""

    def __init__(self, callback: Callable[[str, OrderbookSnapshot], Coroutine[None, None, None]]):
        self.url = settings.polymarket_clob_ws_url
        self.callback = callback
        
        # market_id -> token_id
        self.market_to_token: dict[str, str] = {}
        # token_id -> market_id
        self.token_to_market: dict[str, str] = {}
        
        # token_id -> { "bids": {price: size}, "asks": {price: size} }
        self.books: dict[str, dict] = {}
        
        self._running = False
        self._ws = None

    def add_markets(self, market_registry: dict[str, dict]):
        """
        market_registry is a mapping: market_id -> {"token_id": "...", "platform": "..."}
        We only care about Polymarket markets with a token_id.
        """
        for market_id, info in market_registry.items():
            if info.get("platform") in ("polymarket", "pm"):
                token_id = info.get("token_id")
                if token_id:
                    self.market_to_token[market_id] = token_id
                    self.token_to_market[token_id] = market_id
                    self.books[token_id] = {"bids": {}, "asks": {}}

    async def start(self):
        """Start the WebSocket connection and stream."""
        self._running = True
        
        if not self.token_to_market:
            logger.info("No Polymarket tokens to subscribe to. Stopping client.")
            self._running = False
            return

        reconnect_attempts = 0
        while self._running:
            try:
                logger.info(f"Connecting to Polymarket CLOB at {self.url}...")
                async with websockets.connect(self.url) as ws:
                    self._ws = ws
                    reconnect_attempts = 0
                    logger.info("Connected to Polymarket CLOB.")
                    await self._subscribe()
                    await self._listen()
            except ConnectionClosed as e:
                logger.warning(f"Polymarket WebSocket disconnected: {e}")
            except Exception as e:
                logger.error(f"Polymarket WebSocket error: {e}")
            
            self._ws = None
            if not self._running:
                break
                
            reconnect_attempts += 1
            if reconnect_attempts > settings.ws_reconnect_max_attempts:
                logger.error("Max reconnect attempts reached for Polymarket WebSocket.")
                break
                
            delay = settings.ws_reconnect_base_delay_seconds * min(reconnect_attempts, 10)
            logger.info(f"Reconnecting in {delay} seconds...")
            await asyncio.sleep(delay)

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()

    async def _subscribe(self):
        if not self._ws:
            return
            
        token_ids = list(self.token_to_market.keys())
        msg = {
            "assets_ids": token_ids,
            "type": "market",
            "custom_feature_enabled": True
        }
        await self._ws.send(json.dumps(msg))
        logger.info(f"Subscribed to {len(token_ids)} Polymarket assets.")

    async def _listen(self):
        if not self._ws:
            return
            
        async for message in self._ws:
            if not self._running:
                break
                
            try:
                data = json.loads(message)
                event_type = data.get("event_type")
                asset_id = data.get("asset_id")
                
                if not asset_id or asset_id not in self.books:
                    continue
                    
                if event_type in ("book", "price_change"):
                    self._handle_book_update(asset_id, data, is_snapshot=(event_type == "book"))
                    await self._emit_snapshot(asset_id, data.get("timestamp"))
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    def _handle_book_update(self, asset_id: str, data: dict, is_snapshot: bool):
        book = self.books[asset_id]
        
        if is_snapshot:
            book["bids"].clear()
            book["asks"].clear()
            
        for side in ("bids", "asks"):
            for level in data.get(side, []):
                price = float(level["price"])
                size = float(level["size"])
                if size <= 0:
                    book[side].pop(price, None)
                else:
                    book[side][price] = size

    async def _emit_snapshot(self, asset_id: str, ts_raw):
        market_id = self.token_to_market[asset_id]
        book = self.books[asset_id]
        
        bids = [OrderbookLevel(price=p, size=s) for p, s in book["bids"].items()]
        asks = [OrderbookLevel(price=p, size=s) for p, s in book["asks"].items()]
        
        # Sort properly: highest bids first, lowest asks first
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        
        best_bid = bids[0].price if bids else None
        best_ask = asks[0].price if asks else None
        
        mid_price = None
        spread_bps = None
        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2
            spread_bps = (best_ask - best_bid) * 10000
        
        captured_at = datetime.now(timezone.utc)
        if ts_raw:
            try:
                # TS is usually milliseconds
                captured_at = datetime.fromtimestamp(int(ts_raw) / 1000.0, tz=timezone.utc)
            except Exception:
                pass
                
        snapshot = OrderbookSnapshot(
            id=f"poly_{asset_id}_{int(datetime.now(timezone.utc).timestamp()*1000)}",
            platform="polymarket",
            market_id=market_id,
            token_id=asset_id,
            outcome="YES",
            captured_at=captured_at,
            bids=OrderbookSide(levels=bids),
            asks=OrderbookSide(levels=asks),
            mid_price=mid_price,
            spread_bps=spread_bps
        )
        
        await self.callback(market_id, snapshot)
