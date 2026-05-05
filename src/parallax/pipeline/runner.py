from __future__ import annotations
import hashlib
import logging
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from parallax.audit.service import AuditService
from parallax.candidates.repository import CandidateRepository
from parallax.compiler.anthropic_provider import AnthropicCompilerProvider
from parallax.compiler.service import CompilerService
from parallax.config import settings
from parallax.court.service import CourtService
from parallax.shared.schemas import CourtDecision
from parallax.divergence.service import DivergenceService
from parallax.db.models import RunProofRecord
from parallax.execution.fetcher import OrderbookFetcher
from parallax.execution.replay_stats import ReplayStatisticsService
from parallax.execution.schemas import OrderbookSnapshot
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.identity.service import IdentityService
from parallax.ingestion.adapter import PlatformAdapter
from parallax.ingestion.ingestor import IngestorService
from parallax.ingestion.kalshi_adapter import KalshiAdapter
from parallax.ingestion.market_repository import MarketRepository
from parallax.ops.runtime import build_readiness_payload
from parallax.ops.candidate_funnel import CandidateDiagnosticsService
from parallax.ops.schemas import RunSummary
from parallax.ingestion.polymarket_adapter import PolymarketAdapter
from parallax.detection.semantic import SemanticRelationAnalyzer
from parallax.prover.service import RelationAnalysisService
from parallax.shared.schemas import PayoffMatrix
from parallax.settlement.scanner import SettlementScannerService
from parallax.tracker.service import TrackerService

log = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]


def _anthropic_available() -> bool:
    api_key = settings.anthropic_api_key.strip()
    return bool(api_key and api_key.lower() != "placeholder")


def _config_fingerprint() -> str:
    relevant = {
        "polymarket_max_events_per_poll": settings.polymarket_max_events_per_poll,
        "kalshi_max_events_per_poll": settings.kalshi_max_events_per_poll,
        "pipeline_max_open_markets": settings.pipeline_max_open_markets,
        "friction_bps": settings.friction_bps,
        "compiler_min_confidence": settings.compiler_min_confidence,
        "semantic_min_relation_confidence": settings.semantic_min_relation_confidence,
        "court_max_composite_risk": settings.court_max_composite_risk,
        "court_min_simulated_pnl": settings.court_min_simulated_pnl,
        "court_min_fill_probability": settings.court_min_fill_probability,
    }
    payload = "|".join(f"{key}={value}" for key, value in sorted(relevant.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _provider_fingerprints() -> dict[str, str]:
    return {
        "polymarket": hashlib.sha256(
            f"native:{settings.polymarket_max_events_per_poll}".encode("utf-8")
        ).hexdigest()[:12],
        "kalshi": hashlib.sha256(
            f"native:{settings.kalshi_max_events_per_poll}".encode("utf-8")
        ).hexdigest()[:12],
    }


def build_ingestion_adapters() -> list[PlatformAdapter]:
    return [
        PolymarketAdapter(max_events=settings.polymarket_max_events_per_poll),
        KalshiAdapter(max_events=settings.kalshi_max_events_per_poll),
    ]


async def _fetch_candidate_snapshots(
    fetcher: OrderbookFetcher,
    session: Session,
    candidate,
) -> dict[str, OrderbookSnapshot | None]:
    """Fetch orderbook snapshots for each leg of a candidate."""
    from sqlalchemy import select as sa_select
    from parallax.db.models import VenueToken

    try:
        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
    except Exception:
        return {}

    snapshots: dict[str, OrderbookSnapshot | None] = {}
    seen: set[str] = set()
    for leg in matrix.legs:
        mid = leg.market_id
        if mid in seen:
            continue
        seen.add(mid)
        platform = leg.platform or "unknown"
        token_id: str | None = None
        if platform == "polymarket":
            try:
                row = session.execute(
                    sa_select(VenueToken.token_id).where(
                        VenueToken.platform == platform,
                        VenueToken.raw_market_id == mid,
                        VenueToken.outcome == leg.side,
                    )
                ).scalar_one_or_none()
                token_id = row
            except Exception:
                token_id = None
        try:
            snap = await fetcher.fetch(platform, mid, leg.side, token_id=token_id)
        except Exception:
            snap = None
        snapshots[mid] = snap
    return snapshots


def _persist_snapshot_sync(session: Session, snap: OrderbookSnapshot) -> None:
    from parallax.db.models import OrderbookSnapshotRecord
    record = OrderbookSnapshotRecord(
        id=snap.id,
        platform=snap.platform,
        raw_market_id=snap.market_id,
        token_id=snap.token_id,
        outcome=snap.outcome,
        captured_at=snap.captured_at,
        bid_levels=[{"price": lv.price, "size": lv.size} for lv in (snap.bids.levels if snap.bids else [])],
        ask_levels=[{"price": lv.price, "size": lv.size} for lv in (snap.asks.levels if snap.asks else [])],
        mid_price=snap.mid_price,
    )
    session.merge(record)


class PipelineRunner:
    """Orchestrate a single pipeline run: compile → prove → diverge → court → simulate."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def run_once(self) -> RunSummary:
        run_id = str(uuid.uuid4())
        config_fingerprint = _config_fingerprint()
        provider_fingerprints = _provider_fingerprints()
        started_at = datetime.now(timezone.utc)
        errors: list[str] = []
        markets_ingested = 0
        market_counts_by_platform: dict[str, int] = {}
        contracts_compiled = 0
        events_resolved = 0
        relations_detected = 0
        candidates_found = 0
        candidates_watchlisted = 0
        positions_opened = 0
        positions_settled = 0
        run_status = "completed"

        try:
            with self._session_factory() as session:
                audit_svc = AuditService(session)
                audit_svc.record(
                    "pipeline.run.started",
                    "pipeline",
                    run_id,
                    {
                        "run_id": run_id,
                        "config_fingerprint": config_fingerprint,
                        "provider_fingerprints": provider_fingerprints,
                        "started_at": started_at.isoformat(),
                    },
                )
                self._upsert_run_proof(
                    session,
                    run_id=run_id,
                    run_status="running",
                    started_at=started_at,
                    completed_at=started_at,
                    config_fingerprint=config_fingerprint,
                    provider_fingerprints=provider_fingerprints,
                    readiness={},
                    markets_ingested=0,
                    market_counts_by_platform={},
                    contracts_compiled=0,
                    events_resolved=0,
                    relations_detected=0,
                    candidates_found=0,
                    candidates_watchlisted=0,
                    positions_opened=0,
                    positions_settled=0,
                    errors=[],
                )
                session.commit()

            adapters = build_ingestion_adapters()
            ingestor = IngestorService(adapters, self._session_factory)
            try:
                counts = await ingestor.run_once()
                markets_ingested = sum(counts.values())
                market_counts_by_platform = counts
            except Exception as exc:
                log.warning("pipeline: ingestion failed: %s", exc)
                errors.append(f"ingestion:{exc}")

            with self._session_factory() as session:
                market_repo = MarketRepository(session)
                graph_repo = PostgresGraphRepository(session)
                audit_svc = AuditService(session)

                open_markets = market_repo.list_open()
                if settings.pipeline_max_open_markets > 0:
                    open_markets = open_markets[: settings.pipeline_max_open_markets]
                log.info("pipeline: %d open markets loaded", len(open_markets))

                llm_enabled = _anthropic_available()
                compiler_provider = AnthropicCompilerProvider() if llm_enabled else None
                if compiler_provider is not None:
                    compiler_svc = CompilerService(session, compiler_provider)
                    for market in open_markets:
                        try:
                            with session.begin_nested():
                                await compiler_svc.compile(market)
                            contracts_compiled += 1
                        except Exception as exc:
                            log.warning("pipeline: compile failed for %s: %s", market.id, exc)
                            errors.append(f"compile:{market.id}:{exc}")
                else:
                    log.info("pipeline: no semantic compiler available, skipping compile and semantic analysis")
                audit_svc.record(
                    "pipeline.compiler.complete",
                    "pipeline",
                    run_id,
                    {
                        "run_id": run_id,
                        "config_fingerprint": config_fingerprint,
                        "compiled": contracts_compiled,
                        "llm_enabled": llm_enabled,
                        "compiler_mode": "anthropic" if llm_enabled else "disabled",
                    },
                )
                session.commit()

                identity_svc = IdentityService(session)
                events_resolved = identity_svc.resolve_all_ungrouped()
                audit_svc.record(
                    "pipeline.identity.complete",
                    "pipeline",
                    run_id,
                    {
                        "run_id": run_id,
                        "config_fingerprint": config_fingerprint,
                        "events_resolved": events_resolved,
                    },
                )
                session.commit()

                semantic_analyzer = None
                if llm_enabled:
                    import anthropic as anthropic_sdk
                    semantic_analyzer = SemanticRelationAnalyzer(
                        anthropic_sdk.AsyncAnthropic(api_key=settings.anthropic_api_key)
                    )
                relation_service = RelationAnalysisService(session, graph_repo, semantic_analyzer=semantic_analyzer)
                relations_detected = await relation_service.run(open_markets)
                audit_svc.record(
                    "pipeline.prover.complete",
                    "pipeline",
                    run_id,
                    {
                        "run_id": run_id,
                        "config_fingerprint": config_fingerprint,
                        "relations": relations_detected,
                    },
                )
                session.commit()

                divergence_svc = DivergenceService(session, graph_repo, friction_bps=settings.friction_bps)
                candidates_found = divergence_svc.scan(open_markets)
                audit_svc.record(
                    "pipeline.divergence.complete",
                    "pipeline",
                    run_id,
                    {
                        "run_id": run_id,
                        "config_fingerprint": config_fingerprint,
                        "candidates": candidates_found,
                    },
                )
                session.commit()

                try:
                    diagnostics_count = CandidateDiagnosticsService(session).rebuild_for_run(run_id, open_markets)
                    audit_svc.record(
                        "pipeline.candidate_funnel.complete",
                        "pipeline",
                        run_id,
                        {
                            "run_id": run_id,
                            "config_fingerprint": config_fingerprint,
                            "observations": diagnostics_count,
                        },
                    )
                    session.commit()
                except Exception as exc:
                    log.warning("pipeline: candidate diagnostics failed: %s", exc)
                    errors.append(f"candidate_diagnostics:{exc}")

                candidate_repo = CandidateRepository(session)
                court_svc = CourtService(session)
                tracker_svc = TrackerService(session)
                ob_fetcher = OrderbookFetcher(settings) if settings.orderbook_enabled else None

                for candidate in candidate_repo.list_open():
                    cid = str(candidate.id)
                    
                    # [Opp 8] Tiered Risk Gates: Fast-Reject
                    if not court_svc.fast_reject_check(cid):
                        audit_svc.record(
                            "pipeline.candidate.evaluated",
                            "candidate",
                            cid,
                            {
                                "decision": CourtDecision.REJECTED.value,
                                "decision_path": "fast_reject",
                                "run_id": run_id,
                            },
                        )
                        continue

                    try:
                        snapshots: dict[str, OrderbookSnapshot | None] | None = None
                        if ob_fetcher is not None:
                            snapshots = await _fetch_candidate_snapshots(
                                ob_fetcher, session, candidate
                            )
                        
                        if snapshots is not None:
                            for snap in snapshots.values():
                                if snap is not None:
                                    _persist_snapshot_sync(session, snap)
                            decision = court_svc.evaluate_with_snapshots(cid, snapshots, run_id=run_id)
                        else:
                            replay_stats = ReplayStatisticsService(session).get_stats(
                                candidate.opportunity_type
                            )
                            if replay_stats is not None:
                                decision = court_svc.evaluate_with_replay(cid, run_id=run_id)
                            else:
                                decision = court_svc.evaluate(cid, run_id=run_id)
                        
                        snapshot = candidate_repo.snapshot_to_schema(candidate_repo.get_decision_snapshot(cid))
                        simulation = snapshot.simulation_result if snapshot is not None else None
                        audit_svc.record(
                            "pipeline.candidate.evaluated",
                            "candidate",
                            cid,
                            {
                                "decision": decision.value,
                                "simulated_pnl": simulation.simulated_pnl if simulation is not None else None,
                                "is_executable": simulation.is_executable if simulation is not None else None,
                                "run_id": run_id,
                            },
                        )
                        # Broadcast candidate evaluation
                        from parallax.ops.telemetry import broker
                        import asyncio
                        asyncio.create_task(broker.broadcast("candidate_evaluated", {
                            "candidate_id": cid,
                            # Fast-path risk score access (Bug #18)
                            "risk_scores": candidate.risk_scores,
                            # decision = court_svc.evaluate(cid, run_id=run_id)
                        }))
                        
                        if decision.value == "APPROVED" and simulation is not None and simulation.is_executable:
                            position = tracker_svc.open_position(cid)
                            if position is not None:
                                positions_opened += 1
                                audit_svc.record(
                                    "pipeline.position.opened",
                                    "position",
                                    str(position.id),
                                    {"candidate_id": cid, "run_id": run_id},
                                )
                                asyncio.create_task(broker.broadcast("position_opened", {
                                    "candidate_id": cid,
                                    "position_id": str(position.id),
                                    "simulated_pnl": simulation.simulated_pnl
                                }))
                            
                            # Execute the basket if live execution is enabled
                            if settings.runtime_live_execution_enabled:
                                from parallax.execution.executor import ExecutionManager
                                executor = ExecutionManager()
                                basket = candidate.basket_json
                                if basket and "selected_legs" in basket:
                                    exec_report = await executor.execute_basket(basket["selected_legs"])
                                    audit_svc.record(
                                        "pipeline.candidate.executed",
                                        "candidate",
                                        cid,
                                        {"execution_report": exec_report, "run_id": run_id}
                                    )
                                    asyncio.create_task(broker.broadcast("basket_executed", {
                                        "candidate_id": cid,
                                        "report": exec_report
                                    }))
                        if decision.value == "WATCHLIST":
                            candidates_watchlisted += 1
                        
                        session.commit() # Commit per candidate to avoid long transactions

                    except Exception as exc:
                        log.warning("pipeline: candidate %s evaluation failed: %s", cid, exc)
                        errors.append(f"evaluate:{cid}:{exc}")

                try:
                    scanner = SettlementScannerService(session)
                    settled_ids = scanner.scan_and_settle()
                    positions_settled += len(settled_ids)
                    if settled_ids:
                        session.commit()
                except Exception as exc:
                    log.warning("pipeline: settlement scan failed: %s", exc)

                audit_svc.record(
                    "pipeline.run.completed",
                    "pipeline",
                    run_id,
                    {
                        "run_id": run_id,
                        "run_status": run_status,
                        "started_at": started_at.isoformat(),
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "config_fingerprint": config_fingerprint,
                        "provider_fingerprints": provider_fingerprints,
                        "markets_ingested": markets_ingested,
                        "market_counts_by_platform": market_counts_by_platform,
                        "contracts_compiled": contracts_compiled,
                        "events_resolved": events_resolved,
                        "relations_detected": relations_detected,
                        "candidates_found": candidates_found,
                        "candidates_watchlisted": candidates_watchlisted,
                        "positions_opened": positions_opened,
                        "positions_settled": positions_settled,
                        "errors": errors,
                    },
                )
                readiness = build_readiness_payload(session)
                self._upsert_run_proof(
                    session,
                    run_id=run_id,
                    run_status=run_status,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    config_fingerprint=config_fingerprint,
                    provider_fingerprints=provider_fingerprints,
                    readiness=readiness.model_dump(mode="json"),
                    markets_ingested=markets_ingested,
                    market_counts_by_platform=market_counts_by_platform,
                    contracts_compiled=contracts_compiled,
                    events_resolved=events_resolved,
                    relations_detected=relations_detected,
                    candidates_found=candidates_found,
                    candidates_watchlisted=candidates_watchlisted,
                    positions_opened=positions_opened,
                    positions_settled=positions_settled,
                    errors=errors,
                )
                session.commit()

        except Exception as exc:
            log.error("pipeline: run failed: %s", exc)
            errors.append(str(exc))
            run_status = "failed"

        return RunSummary(
            run_id=run_id,
            run_status=run_status,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            markets_ingested=markets_ingested,
            market_counts_by_platform=market_counts_by_platform,
            contracts_compiled=contracts_compiled,
            events_resolved=events_resolved,
            relations_detected=relations_detected,
            candidates_found=candidates_found,
            candidates_watchlisted=candidates_watchlisted,
            positions_opened=positions_opened,
            positions_settled=positions_settled,
            config_fingerprint=config_fingerprint,
            provider_fingerprints=provider_fingerprints,
            errors=errors,
        )

    @staticmethod
    def _upsert_run_proof(
        session: Session,
        *,
        run_id: str,
        run_status: str,
        started_at: datetime,
        completed_at: datetime,
        config_fingerprint: str,
        provider_fingerprints: dict[str, str],
        readiness: dict,
        markets_ingested: int,
        market_counts_by_platform: dict[str, int],
        contracts_compiled: int,
        events_resolved: int,
        relations_detected: int,
        candidates_found: int,
        candidates_watchlisted: int,
        positions_opened: int,
        positions_settled: int,
        errors: list[str],
    ) -> None:
        row = session.get(RunProofRecord, run_id)
        if row is None:
            row = RunProofRecord(run_id=run_id)
            session.add(row)
        row.run_status = run_status
        row.started_at = started_at
        row.completed_at = completed_at
        row.config_fingerprint = config_fingerprint
        row.provider_fingerprints = provider_fingerprints
        row.readiness_checks = readiness.get("checks", {})
        row.control_state = readiness.get("controls", {})
        row.markets_ingested = markets_ingested
        row.market_counts_by_platform = market_counts_by_platform
        row.contracts_compiled = contracts_compiled
        row.events_resolved = events_resolved
        row.relations_detected = relations_detected
        row.candidates_found = candidates_found
        row.candidates_watchlisted = candidates_watchlisted
        row.positions_opened = positions_opened
        row.positions_settled = positions_settled
        row.fatal_errors = []
        row.non_fatal_errors = errors
        session.flush()


if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    from parallax.db.session import session_scope
    runner = PipelineRunner(session_scope)
    summary = asyncio.run(runner.run_once())
    print(summary)
