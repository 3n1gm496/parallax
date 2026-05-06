import anyio
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
        self._all_markets_lock = anyio.Lock()

    async def run_once(self) -> dict[str, int]:
        """Fetch and upsert from all adapters concurrently (BUG-016 Fix)."""
        counts: dict[str, int] = {adapter.platform_name: 0 for adapter in self._adapters}
        all_markets = []

        async with anyio.create_task_group() as tg:
            async def _task(adapter):
                try:
                    markets = await self._ingest_one(adapter)
                    counts[adapter.platform_name] = len(markets)
                    async with self._all_markets_lock:
                        all_markets.extend(markets)
                except Exception as exc:
                    log.warning("ingestion adapter %s failed: %s", adapter.platform_name, exc)
                    self._safe_record_adapter_failure(adapter.platform_name, exc)

            for adapter in self._adapters:
                tg.start_soon(_task, adapter)

        # BUG-018: Token discovery outside the loop to avoid redundant processing
        if all_markets:
             with self._session_factory() as session:
                 TokenDiscoveryService(session).process(all_markets)
                 session.commit()

        return counts

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            try:
                counts = await self.run_once()
                log.info("ingestion cycle complete: %s", counts)
            except Exception:
                log.exception("ingestion cycle failed")
            
            # [L-016] Reduce poll interval for arbitrage responsiveness
            interval = settings.ingestion_poll_interval_seconds if hasattr(settings, "ingestion_poll_interval_seconds") else 30
            await anyio.sleep(interval)

    def stop(self) -> None:
        self._running = False

    async def _ingest_one(self, adapter: PlatformAdapter) -> list:
        with anyio.fail_after(max(1, self._adapter_timeout_seconds)):
            markets = await adapter.fetch_markets()
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
            
            # [LOGIC FIX L-004] Detect Zombie Markets for this platform
            market_ids = [m.market_id for m in markets]
            closed_count = repo.close_missing_markets(adapter.platform_name, market_ids)
            if closed_count > 0:
                log.info(f"Closed {closed_count} zombie markets for {adapter.platform_name}")

            session.commit()
        return markets

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
