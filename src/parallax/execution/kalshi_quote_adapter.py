from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx

from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot

_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiQuoteAdapter:
    """Read-only orderbook fetcher for Kalshi markets."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
        api_key: str = "",
    ) -> None:
        self._client = http_client
        self._timeout = timeout
        self._api_key = api_key

    async def fetch_snapshot(
        self, market_id: str, outcome: str
    ) -> OrderbookSnapshot | None:
        """Fetch live orderbook for a Kalshi market ticker. Returns None on any error."""
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own = self._client is None
        try:
            return await self._fetch(client, market_id, outcome)
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
    ) -> OrderbookSnapshot | None:
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        resp = await client.get(
            f"{_KALSHI_BASE}/markets/{market_id}/orderbook",
            timeout=self._timeout,
            headers=headers,
        )
        if resp.status_code != 200:
            return None
        data = resp.json().get("orderbook", {})
        # Kalshi YES side: "yes" key; NO is complement
        yes_bids, yes_asks = _parse_kalshi_sides(data, outcome)
        mid = _mid_price(yes_bids, yes_asks)
        spread = _spread_bps(yes_bids, yes_asks)
        return OrderbookSnapshot(
            id=str(uuid.uuid4()),
            platform="kalshi",
            market_id=market_id,
            token_id=None,
            outcome=outcome,
            captured_at=datetime.now(timezone.utc),
            bids=yes_bids,
            asks=yes_asks,
            mid_price=mid,
            spread_bps=spread,
        )


def _parse_kalshi_sides(
    data: dict, outcome: str
) -> tuple[OrderbookSide, OrderbookSide]:
    """
    Kalshi orderbook format:
      { "yes": [[price_cents, size], ...], "no": [[price_cents, size], ...] }
    YES bids = yes entries as bids (buyer willing to pay price/100 for YES).
    NO bids → implied YES asks = (100 - no_price) / 100.
    """
    outcome_upper = outcome.upper()
    if outcome_upper == "YES":
        raw_bids = data.get("yes") or []
        raw_no = data.get("no") or []
        bids = _parse_cents_side(raw_bids)
        # NO bids become YES asks: ask_price = 1 - no_bid_price
        asks_levels = []
        for entry in raw_no:
            try:
                price_cents, size = int(entry[0]), float(entry[1])
                ask_price = (100 - price_cents) / 100.0
                if 0 < ask_price < 1 and size > 0:
                    asks_levels.append(OrderbookLevel(price=ask_price, size=size))
            except (IndexError, TypeError, ValueError):
                continue
        asks = OrderbookSide(levels=asks_levels)
    else:
        # NO outcome: mirror
        raw_bids = data.get("no") or []
        raw_yes = data.get("yes") or []
        bids = _parse_cents_side(raw_bids)
        asks_levels = []
        for entry in raw_yes:
            try:
                price_cents, size = int(entry[0]), float(entry[1])
                ask_price = (100 - price_cents) / 100.0
                if 0 < ask_price < 1 and size > 0:
                    asks_levels.append(OrderbookLevel(price=ask_price, size=size))
            except (IndexError, TypeError, ValueError):
                continue
        asks = OrderbookSide(levels=asks_levels)
    return bids, asks


def _parse_cents_side(entries: list) -> OrderbookSide:
    levels = []
    for entry in entries:
        try:
            price_cents, size = int(entry[0]), float(entry[1])
            price = price_cents / 100.0
            if 0 < price < 1 and size > 0:
                levels.append(OrderbookLevel(price=price, size=size))
        except (IndexError, TypeError, ValueError):
            continue
    return OrderbookSide(levels=levels)


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
