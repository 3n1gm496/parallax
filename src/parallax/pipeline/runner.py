from __future__ import annotations
import logging
from contextlib import AbstractContextManager
from typing import Callable

from sqlalchemy.orm import Session

from parallax.audit.service import AuditService
from parallax.compiler.anthropic_provider import AnthropicCompilerProvider
from parallax.compiler.service import CompilerService
from parallax.config import settings
from parallax.court.service import CourtService
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.divergence.service import DivergenceService
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.ingestion.market_repository import MarketRepository
from parallax.detection.stage2 import Stage2LLMDetector
from parallax.prover.service import ProverService
from parallax.shared.schemas import RunSummary
from parallax.simulator.service import SimulatorService

log = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractContextManager[Session]]


class PipelineRunner:
    """Orchestrate a single pipeline run: compile → prove → diverge → court → simulate."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def run_once(self) -> RunSummary:
        errors: list[str] = []
        contracts_compiled = 0
        relations_detected = 0
        candidates_found = 0
        candidates_watchlisted = 0

        try:
            with self._session_factory() as session:
                market_repo = MarketRepository(session)
                graph_repo = PostgresGraphRepository(session)
                audit_svc = AuditService(session)

                open_markets = market_repo.list_open()
                log.info("pipeline: %d open markets loaded", len(open_markets))

                provider = AnthropicCompilerProvider()
                compiler_svc = CompilerService(session, provider)
                for market in open_markets:
                    try:
                        await compiler_svc.compile(market)
                        contracts_compiled += 1
                    except Exception as exc:
                        log.warning("pipeline: compile failed for %s: %s", market.id, exc)
                        errors.append(f"compile:{market.id}:{exc}")
                audit_svc.record(
                    "pipeline.compiler.complete",
                    "pipeline",
                    "global",
                    {"compiled": contracts_compiled},
                )

                import anthropic as anthropic_sdk
                stage2 = Stage2LLMDetector(anthropic_sdk.AsyncAnthropic(api_key=settings.anthropic_api_key))
                prover = ProverService(session, graph_repo, stage2_classifier=stage2)
                relations_detected = await prover.run(open_markets)
                audit_svc.record("pipeline.prover.complete", "pipeline", "global", {"relations": relations_detected})

                divergence_svc = DivergenceService(session, graph_repo, friction_bps=settings.friction_bps)
                candidates_found = divergence_svc.scan(open_markets)
                audit_svc.record("pipeline.divergence.complete", "pipeline", "global", {"candidates": candidates_found})

                candidate_repo = CandidateRepository(session)
                court_svc = CourtService(session)
                simulator_svc = SimulatorService(session)

                for candidate in candidate_repo.list_open():
                    cid = str(candidate.id)
                    try:
                        decision = court_svc.evaluate(cid)
                        simulator_svc.simulate(cid)
                        if decision.value == "WATCHLIST":
                            candidates_watchlisted += 1
                    except Exception as exc:
                        log.warning("pipeline: candidate %s failed: %s", cid, exc)
                        errors.append(f"candidate:{cid}:{exc}")

                session.commit()

        except Exception as exc:
            log.error("pipeline: run failed: %s", exc)
            errors.append(str(exc))

        return RunSummary(
            markets_ingested=0,
            contracts_compiled=contracts_compiled,
            events_resolved=0,
            relations_detected=relations_detected,
            candidates_found=candidates_found,
            candidates_watchlisted=candidates_watchlisted,
            errors=errors,
        )


if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    from parallax.db.session import session_scope
    runner = PipelineRunner(session_scope)
    summary = asyncio.run(runner.run_once())
    print(summary)
