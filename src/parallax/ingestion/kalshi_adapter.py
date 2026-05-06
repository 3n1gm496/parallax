from __future__ import annotations

import anyio
import asyncio
from datetime import datetime, timezone

import httpx

from parallax.ingestion.adapter import PlatformAdapter
from parallax.shared.schemas import RawMarketData

_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
_PAGE_SIZE = 100
_RETRYABLE_FETCH_ATTEMPTS = 3
_RETRYABLE_FETCH_DELAY_SECONDS = 1.0


class KalshiAdapter(PlatformAdapter):
    """Fetch active binary markets directly from the public Kalshi API."""

    def __init__(self, max_events: int = 50, http_client: httpx.AsyncClient | None = None) -> None:
        self._max_events = max_events
        self._client = http_client

    @property
    def platform_name(self) -> str:
        return "kalshi"

    async def fetch_markets(self) -> list[RawMarketData]:
        client = self._client or httpx.AsyncClient(timeout=30)
        own_client = self._client is None
        try:
            return await self._fetch(client)
        finally:
            if own_client:
                await client.aclose()

    async def _fetch(self, client: httpx.AsyncClient) -> list[RawMarketData]:
        results: list[RawMarketData] = []
        cursor = ""
        while len(results) < self._max_events:
            params: dict[str, object] = {"limit": min(_PAGE_SIZE, self._max_events), "cursor": cursor}
            if not cursor:
                params.pop("cursor")
            response = await self._get_with_retries(client, f"{_KALSHI_BASE}/events", params=params)
            response.raise_for_status()
            payload = response.json()
            events = payload.get("events", [])
            if not isinstance(events, list) or not events:
                break
            for event in events:
                parsed_markets = await self._fetch_event_markets(client, event)
                for market in parsed_markets:
                    results.append(market)
                    if len(results) >= self._max_events:
                        return results
            cursor = str(payload.get("cursor") or "")
            if not cursor:
                break
        return results

    async def _fetch_event_markets(self, client: httpx.AsyncClient, event: dict) -> list[RawMarketData]:
        event_ticker = str(event.get("event_ticker") or "").strip()
        if not event_ticker:
            return []
        response = await self._get_with_retries(client, f"{_KALSHI_BASE}/events/{event_ticker}", params={})
        response.raise_for_status()
        payload = response.json()
        event_payload = payload.get("event") if isinstance(payload.get("event"), dict) else event
        markets = payload.get("markets", [])
        if not isinstance(markets, list):
            return []
        results: list[RawMarketData] = []
        for market in markets:
            parsed = self._parse_market(event_payload, market)
            if parsed is not None:
                results.append(parsed)
        return results

    async def _get_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, object],
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, _RETRYABLE_FETCH_ATTEMPTS + 1):
            try:
                return await client.get(url, params=params)
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt >= _RETRYABLE_FETCH_ATTEMPTS:
                    raise
                await anyio.sleep(_RETRYABLE_FETCH_DELAY_SECONDS * attempt)
        assert last_exc is not None
        raise last_exc

    def _parse_market(self, event: dict, market: dict) -> RawMarketData | None:
        if not self._is_supported_market(market):
            return None
        deadline_raw = market.get("expiration_time") or market.get("close_time")
        if not deadline_raw:
            return None
        deadline = datetime.fromisoformat(str(deadline_raw).replace("Z", "+00:00"))
        yes_price = self._extract_yes_price(market)
        if yes_price is None:
            return None
        event_title = str(event.get("title") or market.get("title") or "").strip()
        yes_sub_title = str(market.get("yes_sub_title") or "").strip()
        title = event_title if not yes_sub_title else f"{event_title} — {yes_sub_title}"
        description_parts = [
            event_title,
            str(event.get("sub_title") or "").strip(),
            yes_sub_title,
        ]
        description = " | ".join(part for part in description_parts if part)
        market_ticker = str(market.get("ticker") or "").strip()
        if not market_ticker:
            return None

        return RawMarketData(
            platform="kalshi",
            market_id=market_ticker,
            title=title,
            description=description or title,
            resolution_criteria=str(market.get("rules_primary") or event.get("title") or title),
            outcomes=["Yes", "No"],
            outcome_prices=[yes_price, round(1.0 - yes_price, 4)],
            category=str(event.get("category") or "").strip() or None,
            group_id=str(event.get("event_ticker") or "").strip() or None,
            deadline=deadline.astimezone(timezone.utc),
            is_closed=str(market.get("status", "active")).lower() != "active",
            resolution_source="kalshi_rules_primary",
            raw_payload={"event": event, "market": market},
        )

    @staticmethod
    def _is_supported_market(market: dict) -> bool:
        if str(market.get("status", "")).lower() != "active":
            return False
        if str(market.get("market_type", "")).lower() != "binary":
            return False
        if market.get("mve_collection_ticker") or market.get("mve_selected_legs") or market.get("custom_strike"):
            return False
        ticker = str(market.get("ticker") or "")
        event_ticker = str(market.get("event_ticker") or "")
        if ticker.startswith("KXMVE") or event_ticker.startswith("KXMVE"):
            return False
        return True

    @classmethod
    def _extract_yes_price(cls, market: dict) -> float | None:
        yes_bid = cls._as_float(market.get("yes_bid_dollars"))
        yes_ask = cls._as_float(market.get("yes_ask_dollars"))
        if yes_bid is not None and yes_ask is not None:
            return round((yes_bid + yes_ask) / 2.0, 4)
        last_price = cls._as_float(market.get("last_price_dollars"))
        if last_price is not None:
            return round(last_price, 4)
        if yes_bid is not None:
            return round(yes_bid, 4)
        if yes_ask is not None:
            return round(yes_ask, 4)
        no_bid = cls._as_float(market.get("no_bid_dollars"))
        if no_bid is not None:
            return round(1.0 - no_bid, 4)
        no_ask = cls._as_float(market.get("no_ask_dollars"))
        if no_ask is not None:
            return round(1.0 - no_ask, 4)
        return None

    @staticmethod
    def _as_float(value: object) -> float | None:
        if value in (None, ""):
            return None
        return float(value)
