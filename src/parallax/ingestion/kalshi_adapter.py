from __future__ import annotations

from datetime import datetime

import httpx

from parallax.ingestion.adapter import PlatformAdapter
from parallax.shared.schemas import RawMarketData

_KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"
_PAGE_SIZE = 200


class KalshiAdapter(PlatformAdapter):
    """Fetches open markets from Kalshi via the REST API v2 (requires Bearer API key)."""

    def __init__(
        self,
        api_key: str,
        max_markets: int = 500,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_markets = max_markets
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
        headers = {"Authorization": f"Bearer {self._api_key}"}
        while len(results) < self._max_markets:
            params: dict = {"status": "open", "limit": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                f"{_KALSHI_BASE}/markets",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("markets", [])
            for raw in batch:
                parsed = self._parse(raw)
                if parsed is not None:
                    results.append(parsed)
            cursor = data.get("cursor", "")
            if not cursor or not batch:
                break
        return results

    def _parse(self, raw: dict) -> RawMarketData | None:
        try:
            if raw.get("status", "") != "open":
                return None
            close_time = raw.get("close_time")
            if not close_time:
                return None
            deadline = datetime.fromisoformat(close_time.replace("Z", "+00:00"))

            yes_bid = raw.get("yes_bid", 0.0) or 0.0
            yes_ask = raw.get("yes_ask", 0.0) or 0.0
            yes_mid = (float(yes_bid) + float(yes_ask)) / 2.0

            return RawMarketData(
                platform="kalshi",
                market_id=raw["ticker"],
                title=raw.get("title", ""),
                description=raw.get("rules_primary", ""),
                resolution_criteria=raw.get("rules_primary", ""),
                outcomes=["Yes", "No"],
                outcome_prices=[round(yes_mid, 4), round(1.0 - yes_mid, 4)],
                category=raw.get("category"),
                group_id=raw.get("event_ticker"),
                deadline=deadline,
                is_closed=False,
                resolution_source=None,
                raw_payload=raw,
            )
        except (KeyError, ValueError, TypeError):
            return None
