from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx

from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot

_CLOB_BASE = "https://clob.polymarket.com"
_GAMMA_BASE = "https://gamma-api.polymarket.com"


class PolymarketCLOBAdapter:
    """Read-only CLOB orderbook fetcher for Polymarket."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._client = http_client
        self._timeout = timeout

    async def fetch_snapshot(
        self, market_id: str, outcome: str, token_id: str
    ) -> OrderbookSnapshot | None:
        """Fetch live orderbook for a single token. Returns None on any error."""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own = self._client is None
        try:
            return await self._fetch(client, market_id, outcome, token_id)
        except Exception:
            return None
        finally:
            if own:
                await client.aclose()

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        market_id: str,
        outcome: str,
        token_id: str,
    ) -> OrderbookSnapshot | None:
        resp = await client.get(
            f"{_CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=self._timeout,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        bids = _parse_side(data.get("bids") or [])
        asks = _parse_side(data.get("asks") or [])
        mid = _mid_price(bids, asks)
        spread = _spread_bps(bids, asks)
        return OrderbookSnapshot(
            id=str(uuid.uuid4()),
            platform="polymarket",
            market_id=market_id,
            token_id=token_id,
            outcome=outcome,
            captured_at=datetime.now(timezone.utc),
            bids=bids,
            asks=asks,
            mid_price=mid,
            spread_bps=spread,
        )

    async def resolve_token_id(self, market_id: str, outcome: str) -> str | None:
        """Resolve Polymarket token_id from Gamma API using market_id + outcome label."""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own = self._client is None
        try:
            resp = await client.get(
                f"{_GAMMA_BASE}/markets",
                params={"clob_token_ids": market_id},
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                return None
            markets = resp.json()
            if not isinstance(markets, list) or not markets:
                return None
            market = markets[0]
            outcomes = market.get("outcomes") or []
            tokens = market.get("clobTokenIds") or []
            for i, o in enumerate(outcomes):
                if str(o).upper() == outcome.upper() and i < len(tokens):
                    return tokens[i]
            return None
        except Exception:
            return None
        finally:
            if own:
                await client.aclose()


def _parse_side(levels: list[dict]) -> OrderbookSide:
    parsed = []
    for lvl in levels:
        try:
            price = float(lvl.get("price", 0))
            size = float(lvl.get("size", 0))
            if price > 0 and size > 0:
                parsed.append(OrderbookLevel(price=price, size=size))
        except (TypeError, ValueError):
            continue
    return OrderbookSide(levels=parsed)


def _mid_price(bids: OrderbookSide, asks: OrderbookSide) -> float | None:
    best_bid = max((l.price for l in bids.levels), default=None)
    best_ask = min((l.price for l in asks.levels), default=None)
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2


def _spread_bps(bids: OrderbookSide, asks: OrderbookSide) -> float | None:
    best_bid = max((l.price for l in bids.levels), default=None)
    best_ask = min((l.price for l in asks.levels), default=None)
    if best_bid is None or best_ask is None or best_bid <= 0:
        return None
    return ((best_ask - best_bid) / best_bid) * 10000
