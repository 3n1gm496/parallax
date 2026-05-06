from __future__ import annotations
import anyio
import asyncio
import json
from datetime import datetime
import httpx
from parallax.ingestion.adapter import PlatformAdapter
from parallax.shared.schemas import RawMarketData

_GAMMA_BASE = "https://gamma-api.polymarket.com"
_PAGE_SIZE = 100
_RETRYABLE_FETCH_ATTEMPTS = 3
_RETRYABLE_FETCH_DELAY_SECONDS = 1.0


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
            resp = await self._get_with_retries(
                client,
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

    def _parse(self, raw: dict) -> RawMarketData | None:
        try:
            end_date = raw.get("endDate") or raw.get("endDateIso") or raw.get("end_date_iso")
            if not end_date:
                return None
            deadline = datetime.fromisoformat(end_date.replace("Z", "+00:00"))

            outcomes, outcome_prices = self._parse_outcomes(raw)

            return RawMarketData(
                platform="polymarket",
                market_id=str(raw["id"]),
                title=raw.get("question", ""),
                description=raw.get("description", ""),
                resolution_criteria=raw.get("description", raw.get("resolutionSource", "")),
                outcomes=outcomes,
                outcome_prices=outcome_prices,
                category=raw.get("category"),
                group_id=self._extract_group_id(raw),
                deadline=deadline,
                is_closed=bool(raw.get("closed", False)),
                resolution_source=raw.get("resolutionSource"),
                raw_payload=raw,
                token_ids=PolymarketAdapter._extract_token_ids(raw),
            )
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _extract_token_ids(raw: dict) -> dict[str, str]:
        result: dict[str, str] = {}
        tokens = raw.get("tokens")
        if isinstance(tokens, list):
            for t in tokens:
                if isinstance(t, dict) and t.get("token_id") and t.get("outcome"):
                    result[str(t["outcome"])] = str(t["token_id"])
            if result:
                return result
        outcomes = raw.get("outcomes", [])
        clob_ids = raw.get("clobTokenIds", [])
        if isinstance(outcomes, list) and isinstance(clob_ids, list):
            for outcome, tid in zip(outcomes, clob_ids):
                if outcome and tid:
                    result[str(outcome)] = str(tid)
        return result

    @staticmethod
    def _parse_outcomes(raw: dict) -> tuple[list[str], list[float]]:
        tokens = raw.get("tokens")
        if isinstance(tokens, list) and tokens:
            outcomes = [str(token.get("outcome", "")) for token in tokens]
            prices = [float(token.get("price")) if token.get("price") is not None else 0.0 for token in tokens]
            return outcomes, prices

        outcomes_raw = PolymarketAdapter._coerce_list(raw.get("outcomes"))
        prices_raw = PolymarketAdapter._coerce_list(raw.get("outcomePrices"))
        outcomes = [str(value) for value in outcomes_raw]
        prices = [float(value) if value is not None else 0.0 for value in prices_raw]
        return outcomes, prices

    @staticmethod
    def _extract_group_id(raw: dict) -> str | None:
        for key in ("eventId", "event_id"):
            value = raw.get(key)
            if value is not None:
                text = str(value).strip()
                if text:
                    return text

        events = raw.get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                for key in ("id", "ticker", "slug"):
                    value = event.get(key)
                    if value is not None:
                        text = str(value).strip()
                        if text:
                            return text
        return None

    @staticmethod
    def _coerce_list(value: object) -> list:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return []
