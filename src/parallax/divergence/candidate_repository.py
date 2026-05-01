from __future__ import annotations
import uuid
from sqlalchemy.orm import Session
from parallax.db.models import OpportunityCandidate
from parallax.shared.schemas import CourtDecision, OpportunityType, PayoffMatrix


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
        """Return True if an open candidate already covers this market pair and type."""
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

    def update_decision(
        self, candidate_id: str, decision: CourtDecision
    ) -> bool:
        candidate = self.get(candidate_id)
        if candidate is None:
            return False
        candidate.court_decision = decision.value
        self._session.flush()
        return True
