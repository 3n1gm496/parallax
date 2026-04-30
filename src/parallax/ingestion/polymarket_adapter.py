from __future__ import annotations
from datetime import datetime, timezone
import httpx
from parallax.ingestion.adapter import PlatformAdapter
from parallax.shared.schemas import RawMarketData

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_PAGE_SIZE = 100


class PolymarketAdapter(PlatformAdapter):
    """Fetches active markets from Polymarket via the Gamma REST API."""

    def __init__(self, max_events: int = 50, http_client: httpx.AsyncClient | None = None) -> None:
        self._max_events = max_events
        self._client = http_client

    @property
    def platform_name(self) -> str:
        return "polymarket"

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
        offset = 0
        while len(results) < self._max_events:
            limit = min(_PAGE_SIZE, self._max_events - len(results))
            resp = await client.get(
                f"{_GAMMA_BASE}/markets",
                params={"active": "true", "closed": "false", "limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for raw in batch:
                parsed = self._parse(raw)
                if parsed is not None:
                    results.append(parsed)
            if len(batch) < limit:
                break
            offset += limit
        return results

    def _parse(self, raw: dict) -> RawMarketData | None:
        try:
            end_date = raw.get("endDate") or raw.get("end_date_iso")
            if not end_date:
                return None
            deadline = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

            tokens: list[dict] = raw.get("tokens", [])
            outcomes = [t.get("outcome", "") for t in tokens]
            prices_raw = [t.get("price") for t in tokens]
            outcome_prices = [float(p) if p is not None else 0.0 for p in prices_raw]

            return RawMarketData(
                platform="polymarket",
                market_id=str(raw["id"]),
                title=raw.get("question", ""),
                description=raw.get("description", ""),
                resolution_criteria=raw.get("resolutionSource", ""),
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                category=raw.get("category"),
                group_id=raw.get("eventId"),
                deadline=deadline,
                is_closed=bool(raw.get("closed", False)),
                resolution_source=raw.get("resolutionSource"),
                raw_payload=raw,
            )
        except (KeyError, ValueError):
            return None
