from __future__ import annotations

from sqlalchemy.orm import Session

from parallax.candidates.evidence import load_relation_evidence
from parallax.candidates.repository import CandidateRepository
from parallax.court.service import CourtService
from parallax.shared.schemas import (
    CandidateDetail,
    CandidateSummary,
    CourtDecision,
    DecisionSnapshot,
    OpportunityType,
    PayoffMatrix,
    RiskScore,
)
from parallax.simulator.service import SimulatorService


class CandidateReadService:
    """Own the read-side assembly for candidate API surfaces."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CandidateRepository(session)
        self._simulator = SimulatorService(session)
        self._court = CourtService(session)

    def list_open_summaries(self, *, limit: int = 100, offset: int = 0) -> list[CandidateSummary]:
        from sqlalchemy import select
        from parallax.db.models import CandidateDecisionSnapshot

        rows = self._repo.list_open(limit=limit, offset=offset)
        if not rows:
            return []

        candidate_ids = [row.id for row in rows]
        snap_rows = self._session.execute(
            select(
                CandidateDecisionSnapshot.candidate_id,
                CandidateDecisionSnapshot.simulation_result,
            ).where(CandidateDecisionSnapshot.candidate_id.in_(candidate_ids))
        ).all()
        em_by_id: dict[str, str | None] = {
            str(cid): (sim.get("execution_model") if isinstance(sim, dict) else None)
            for cid, sim in snap_rows
        }

        return [
            CandidateSummary(
                id=str(row.id),
                opportunity_type=OpportunityType(row.opportunity_type),
                worst_case_payoff=row.worst_case_payoff,
                total_cost=PayoffMatrix.model_validate(row.payoff_matrix).total_cost,
                court_decision=CourtDecision(row.court_decision),
                created_at=row.detected_at,
                execution_model=em_by_id.get(str(row.id)),
            )
            for row in rows
        ]

    def get_detail(self, candidate_id: str) -> CandidateDetail:
        row = self._repo.get(candidate_id)
        if row is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(row.payoff_matrix)
        scenario_matrix, proof_object = self._repo.get_solver_artifacts(candidate_id)
        try:
            risk = RiskScore.model_validate(row.risk_scores) if row.risk_scores else None
        except Exception:
            risk = None

        return CandidateDetail(
            id=str(row.id),
            opportunity_type=OpportunityType(row.opportunity_type),
            market_ids=row.market_ids,
            payoff_matrix=matrix,
            scenario_matrix=scenario_matrix,
            proof_object=proof_object,
            basket=row.basket_json or {},
            false_arbitrage_label=row.false_arbitrage_label,
            risk_score=risk,
            decision_snapshot=self.get_decision_snapshot(candidate_id),
            simulation_result=self._simulator.simulate(candidate_id),
            court_assessment=self._court.assess(candidate_id),
            relation_evidence=load_relation_evidence(self._session, row.market_ids),
            court_decision=CourtDecision(row.court_decision),
            created_at=row.detected_at,
        )

    def get_decision_snapshot(self, candidate_id: str) -> DecisionSnapshot | None:
        return self._repo.snapshot_to_schema(self._repo.get_decision_snapshot(candidate_id))

    def list_decision_ledger_entries(self, candidate_id: str, *, limit: int = 100):
        return self._repo.list_decision_ledger_entries(candidate_id, limit=limit)
