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
        rows = self._repo.list_open(limit=limit, offset=offset)
        return [
            CandidateSummary(
                id=str(row.id),
                opportunity_type=OpportunityType(row.opportunity_type),
                worst_case_payoff=row.worst_case_payoff,
                total_cost=PayoffMatrix.model_validate(row.payoff_matrix).total_cost,
                court_decision=CourtDecision(row.court_decision),
                created_at=row.detected_at,
            )
            for row in rows
        ]

    def get_detail(self, candidate_id: str) -> CandidateDetail:
        row = self._repo.get(candidate_id)
        if row is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(row.payoff_matrix)
        try:
            risk = RiskScore.model_validate(row.risk_scores) if row.risk_scores else None
        except Exception:
            risk = None

        return CandidateDetail(
            id=str(row.id),
            opportunity_type=OpportunityType(row.opportunity_type),
            market_ids=row.market_ids,
            payoff_matrix=matrix,
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
