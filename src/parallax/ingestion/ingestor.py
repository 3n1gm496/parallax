from __future__ import annotations
import asyncio
import logging
from parallax.ingestion.adapter import PlatformAdapter
from parallax.ingestion.market_repository import MarketRepository
from parallax.audit.service import AuditService

log = logging.getLogger(__name__)


class IngestorService:
    """Polls all registered platform adapters and persists markets."""

    def __init__(
        self,
        adapters: list[PlatformAdapter],
        session_factory,
        poll_interval_seconds: int = 300,
    ) -> None:
        self._adapters = adapters
        self._session_factory = session_factory
        self._poll_interval = poll_interval_seconds
        self._running = False

    async def run_once(self) -> dict[str, int]:
        """Fetch and upsert from all adapters. Returns per-platform counts."""
        counts: dict[str, int] = {}
        for adapter in self._adapters:
            counts[adapter.platform_name] = await self._ingest_one(adapter)
        return counts

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            try:
                counts = await self.run_once()
                log.info("ingestion cycle complete: %s", counts)
            except Exception:
                log.exception("ingestion cycle failed")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    async def _ingest_one(self, adapter: PlatformAdapter) -> int:
        markets = await adapter.fetch_markets()
        created_count = 0
        with self._session_factory() as session:
            repo = MarketRepository(session)
            audit = AuditService(session)
            for data in markets:
                _, created = repo.upsert(data)
                if created:
                    audit.record(
                        "market.ingested",
                        "market",
                        f"{data.platform}:{data.market_id}",
                        {"platform": data.platform, "title": data.title},
                    )
                    created_count += 1
            session.commit()
        return created_count
