from __future__ import annotations
import asyncio
import logging
from parallax.config import settings
from parallax.execution.token_discovery import TokenDiscoveryService
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
        adapter_timeout_seconds: int | None = None,
    ) -> None:
        self._adapters = adapters
        self._session_factory = session_factory
        self._poll_interval = poll_interval_seconds
        self._adapter_timeout_seconds = (
            settings.ingestion_adapter_timeout_seconds
            if adapter_timeout_seconds is None
            else adapter_timeout_seconds
        )
        self._running = False

    async def run_once(self) -> dict[str, int]:
        """Fetch and upsert from all adapters. Returns per-platform processed counts."""
        counts: dict[str, int] = {}
        for adapter in self._adapters:
            try:
                counts[adapter.platform_name] = await self._ingest_one(adapter)
            except Exception as exc:
                counts[adapter.platform_name] = 0
                log.warning("ingestion adapter %s failed: %s", adapter.platform_name, exc)
                self._safe_record_adapter_failure(adapter.platform_name, exc)
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
        markets = await asyncio.wait_for(
            adapter.fetch_markets(),
            timeout=max(1, self._adapter_timeout_seconds),
        )
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
            token_count = TokenDiscoveryService(session).process(markets)
            audit.record(
                "ingestion.token_discovery.complete",
                "ingestion",
                adapter.platform_name,
                {"platform": adapter.platform_name, "tokens_upserted": token_count},
            )
            session.commit()
        return len(markets)

    def _safe_record_adapter_failure(self, platform_name: str, exc: Exception) -> None:
        try:
            self._record_adapter_failure(platform_name, exc)
        except Exception:
            log.exception("failed to persist ingestion failure audit for %s", platform_name)

    def _record_adapter_failure(self, platform_name: str, exc: Exception) -> None:
        error_text = str(exc).strip() or exc.__class__.__name__
        with self._session_factory() as session:
            AuditService(session).record(
                "ingestion.adapter.failed",
                "platform",
                platform_name,
                {"platform": platform_name, "error": error_text},
            )
            session.commit()
