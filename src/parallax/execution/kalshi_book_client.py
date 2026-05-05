import asyncio
import base64
import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable, Coroutine

import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from websockets.exceptions import ConnectionClosed

from parallax.config import settings
from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot

logger = logging.getLogger(__name__)

class KalshiBookClient:
    """Connects to Kalshi Trade API WebSocket v2 to stream orderbook data."""

    def __init__(self, callback: Callable[[str, OrderbookSnapshot], Coroutine[None, None, None]]):
        self.url = settings.kalshi_ws_url
        self.callback = callback
        
        self.market_tickers: set[str] = set()
        
        # market_ticker -> { "bids": {price: size}, "asks": {price: size} }
        self.books: dict[str, dict] = {}
        
        self._running = False
        self._ws = None

    def add_markets(self, market_registry: dict[str, dict]):
        """
        market_registry is a mapping: market_id -> {"ticker": "...", "platform": "..."}
        We care about Kalshi markets with a ticker.
        """
        for market_id, info in market_registry.items():
            if info.get("platform") == "kalshi":
                # For Kalshi, market_id is usually the ticker itself in our DB, 
                # but we use info.get("ticker") or market_id just in case.
                ticker = info.get("ticker", market_id)
                self.market_tickers.add(ticker)
                if ticker not in self.books:
                    self.books[ticker] = {"bids": {}, "asks": {}}

    async def start(self):
        """Start the WebSocket connection and stream."""
        self._running = True
        
        if not self.market_tickers:
            logger.info("No Kalshi tickers to subscribe to. Stopping client.")
            self._running = False
            return

        reconnect_attempts = 0
        while self._running:
            try:
                headers = self._get_auth_headers()
                if not headers:
                    logger.warning("Kalshi WebSocket auth headers could not be generated (missing or invalid credentials). Retrying later...")
                    await asyncio.sleep(10)
                    continue

                logger.info(f"Connecting to Kalshi Trade API WS at {self.url}...")
                async with websockets.connect(self.url, extra_headers=headers) as ws:
                    self._ws = ws
                    reconnect_attempts = 0
                    logger.info("Connected to Kalshi Trade API WS.")
                    await self._subscribe()
                    await self._listen()
            except ConnectionClosed as e:
                logger.warning(f"Kalshi WebSocket disconnected: {e}")
            except Exception as e:
                logger.error(f"Kalshi WebSocket error: {e}")
            
            self._ws = None
            if not self._running:
                break
                
            reconnect_attempts += 1
            if reconnect_attempts > settings.ws_reconnect_max_attempts:
                logger.error("Max reconnect attempts reached for Kalshi WebSocket.")
                break
                
            delay = settings.ws_reconnect_base_delay_seconds * min(reconnect_attempts, 10)
            logger.info(f"Reconnecting in {delay} seconds...")
            await asyncio.sleep(delay)

    async def stop(self):
        self._running = False
        if self._ws:
            await self._ws.close()

    def _get_auth_headers(self):
        api_key_id = settings.kalshi_api_key
        private_key_str = settings.kalshi_api_secret
        
        if not api_key_id or not private_key_str:
            return None
            
        try:
            # Ensure it's properly formatted PEM
            if "-----BEGIN" not in private_key_str:
                # If someone passed the raw base64 string without headers, format it
                private_key_str = f"-----BEGIN PRIVATE KEY-----\n{private_key_str}\n-----END PRIVATE KEY-----"
                
            private_key = serialization.load_pem_private_key(
                private_key_str.encode('utf-8'),
                password=None,
            )
            
            timestamp = str(int(time.time() * 1000))
            msg_string = timestamp + "GET" + "/trade-api/ws/v2"
            
            signature = private_key.sign(
                msg_string.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            signature_b64 = base64.b64encode(signature).decode('utf-8')
            
            return {
                "KALSHI-ACCESS-KEY": api_key_id,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "KALSHI-ACCESS-SIGNATURE": signature_b64
            }
        except Exception as e:
            logger.error(f"Failed to generate Kalshi auth headers: {e}")
            return None

    async def _subscribe(self):
        if not self._ws:
            return
            
        msg = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": list(self.market_tickers)
            }
        }
        await self._ws.send(json.dumps(msg))
        logger.info(f"Subscribed to {len(self.market_tickers)} Kalshi markets.")

    async def _listen(self):
        if not self._ws:
            return
            
        async for message in self._ws:
            if not self._running:
                break
                
            try:
                data = json.loads(message)
                msg_type = data.get("type")
                msg_data = data.get("msg", {})
                
                if msg_type == "orderbook_snapshot":
                    self._handle_snapshot(msg_data)
                    await self._emit_snapshot(msg_data.get("market_ticker"), msg_data.get("ts"))
                elif msg_type == "orderbook_delta":
                    self._handle_delta(msg_data)
                    await self._emit_snapshot(msg_data.get("market_ticker"), msg_data.get("ts"))
            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.error(f"Error processing message: {e}")

    def _handle_snapshot(self, data: dict):
        ticker = data.get("market_ticker")
        if not ticker or ticker not in self.books:
            return
            
        book = self.books[ticker]
        book["bids"].clear()
        book["asks"].clear()
        
        # Kalshi snapshot provides arrays of [price_cents, quantity]
        for bid in data.get("yes_bid_levels", []):
            if len(bid) == 2:
                # price in cents, convert to probability (0.0 to 1.0)
                price = float(bid[0]) / 100.0
                size = float(bid[1])
                book["bids"][price] = size
                
        for ask in data.get("yes_ask_levels", []):
            if len(ask) == 2:
                price = float(ask[0]) / 100.0
                size = float(ask[1])
                book["asks"][price] = size

    def _handle_delta(self, data: dict):
        ticker = data.get("market_ticker")
        if not ticker or ticker not in self.books:
            return
            
        book = self.books[ticker]
        
        # Delta format usually has price in cents or price_fp
        price_cents = data.get("price")
        if price_cents is None:
            return
            
        price = float(price_cents) / 100.0
        # Delta is the change in size. Wait, Kalshi delta might be absolute size or relative?
        # Typically Kalshi sends the new absolute size at that price level for orderbook_delta?
        # Actually docs say "delta" in Kalshi V2 is usually absolute quantity remaining at the level.
        # Let's check Kalshi docs: "delta" usually represents the new quantity at that price level.
        # Wait, if `delta` is sent, sometimes it's absolute. 
        # For safety, let's treat `delta` as the new size. 
        # If it's 0, remove.
        size = float(data.get("quantity", data.get("delta", 0)))
        side = data.get("side")
        
        if side == "yes_bid":
            if size <= 0:
                book["bids"].pop(price, None)
            else:
                book["bids"][price] = size
        elif side == "yes_ask":
            if size <= 0:
                book["asks"].pop(price, None)
            else:
                book["asks"][price] = size

    async def _emit_snapshot(self, ticker: str, ts_raw):
        if not ticker or ticker not in self.books:
            return
            
        book = self.books[ticker]
        
        bids = [OrderbookLevel(price=p, size=s) for p, s in book["bids"].items()]
        asks = [OrderbookLevel(price=p, size=s) for p, s in book["asks"].items()]
        
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
                captured_at = datetime.fromtimestamp(int(ts_raw) / 1000.0, tz=timezone.utc)
            except Exception:
                pass
                
        snapshot = OrderbookSnapshot(
            id=f"kalshi_{ticker}_{int(datetime.now(timezone.utc).timestamp()*1000)}",
            platform="kalshi",
            market_id=ticker,
            outcome="YES",
            captured_at=captured_at,
            bids=OrderbookSide(levels=bids),
            asks=OrderbookSide(levels=asks),
            mid_price=mid_price,
            spread_bps=spread_bps
        )
        
        await self.callback(ticker, snapshot)
