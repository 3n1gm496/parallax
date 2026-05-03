from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from parallax.db.models import CandidateDecisionSnapshot, OpportunityCandidate
from parallax.shared.schemas import (
    CourtAssessment,
    CourtDecision,
    DecisionSnapshot,
    OpportunityType,
    PayoffMatrix,
    RelationEvidenceResponse,
    RiskScore,
    SimulationResult,
)


class CandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        market_ids: list[str],
        payoff_matrix: PayoffMatrix,
        opportunity_type: OpportunityType,
        risk_scores: dict,
    ) -> OpportunityCandidate:
        candidate = OpportunityCandidate(
            id=uuid.uuid4(),
            market_ids=market_ids,
            payoff_matrix=payoff_matrix.model_dump(),
            opportunity_type=opportunity_type.value,
            worst_case_payoff=payoff_matrix.worst_case_payoff,
            friction_bps=payoff_matrix.friction_bps,
            risk_scores=risk_scores,
            court_decision=CourtDecision.PENDING.value,
        )
        self._session.add(candidate)
        self._session.flush()
        return candidate

    def get(self, candidate_id: str) -> OpportunityCandidate | None:
        return self._session.get(OpportunityCandidate, uuid.UUID(candidate_id))

    def candidate_exists(self, market_ids: list[str], opportunity_type: OpportunityType) -> bool:
        target = frozenset(market_ids)
        rows = (
            self._session.query(OpportunityCandidate)
            .filter_by(opportunity_type=opportunity_type.value, status="open")
            .all()
        )
        return any(frozenset(row.market_ids) == target for row in rows)

    def list_open(self, limit: int = 100, offset: int = 0) -> list[OpportunityCandidate]:
        return (
            self._session.query(OpportunityCandidate)
            .filter_by(status="open")
            .order_by(OpportunityCandidate.detected_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def update_decision(self, candidate_id: str, decision: CourtDecision) -> bool:
        candidate = self.get(candidate_id)
        if candidate is None:
            return False
        candidate.court_decision = decision.value
        self._session.flush()
        return True

    def close(self, candidate_id: str) -> bool:
        candidate = self.get(candidate_id)
        if candidate is None:
            return False
        candidate.status = "closed"
        candidate.resolved_at = datetime.now(timezone.utc)
        self._session.flush()
        return True

    def get_decision_snapshot(self, candidate_id: str) -> CandidateDecisionSnapshot | None:
        return self._session.get(CandidateDecisionSnapshot, uuid.UUID(candidate_id))

    def upsert_decision_snapshot(
        self,
        candidate_id: str,
        *,
        run_id: str | None,
        risk_score: RiskScore | None,
        relation_evidence: RelationEvidenceResponse | None,
        simulation_result: SimulationResult | None,
        court_assessment: CourtAssessment | None,
        evaluated_at: datetime | None = None,
        snapshot_version: str = "decision-snapshot-v1",
    ) -> CandidateDecisionSnapshot:
        snapshot = self.get_decision_snapshot(candidate_id)
        if snapshot is None:
            snapshot = CandidateDecisionSnapshot(candidate_id=uuid.UUID(candidate_id))
            self._session.add(snapshot)
        snapshot.run_id = run_id
        snapshot.risk_score = risk_score.model_dump() if risk_score is not None else None
        snapshot.relation_evidence = relation_evidence.model_dump() if relation_evidence is not None else None
        snapshot.simulation_result = simulation_result.model_dump() if simulation_result is not None else None
        snapshot.court_assessment = court_assessment.model_dump() if court_assessment is not None else None
        snapshot.snapshot_version = snapshot_version
        snapshot.evaluated_at = evaluated_at or datetime.now(timezone.utc)
        self._session.flush()
        return snapshot

    @staticmethod
    def snapshot_to_schema(row: CandidateDecisionSnapshot | None) -> DecisionSnapshot | None:
        if row is None:
            return None
        return DecisionSnapshot(
            candidate_id=str(row.candidate_id),
            run_id=row.run_id,
            risk_score=RiskScore.model_validate(row.risk_score) if row.risk_score else None,
            relation_evidence=RelationEvidenceResponse.model_validate(row.relation_evidence)
            if row.relation_evidence
            else None,
            simulation_result=SimulationResult.model_validate(row.simulation_result)
            if row.simulation_result
            else None,
            court_assessment=CourtAssessment.model_validate(row.court_assessment)
            if row.court_assessment
            else None,
            snapshot_version=row.snapshot_version,
            evaluated_at=row.evaluated_at,
        )
