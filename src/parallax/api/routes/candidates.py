from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from parallax.api.deps import get_session
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.shared.schemas import (
    CandidateDetail,
    CandidateSummary,
    CourtDecision,
    OpportunityType,
    PayoffMatrix,
    RiskScore,
)

router = APIRouter(tags=["candidates"])


@router.get("/candidates", response_model=list[CandidateSummary])
def list_candidates(
    session: Session = Depends(get_session),
) -> list[CandidateSummary]:
    repo = CandidateRepository(session)
    rows = repo.list_open()
    return [
        CandidateSummary(
            id=str(r.id),
            opportunity_type=OpportunityType(r.opportunity_type),
            worst_case_payoff=r.worst_case_payoff,
            total_cost=PayoffMatrix.model_validate(r.payoff_matrix).total_cost,
            court_decision=CourtDecision(r.court_decision),
            created_at=r.detected_at,
        )
        for r in rows
    ]


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(
    candidate_id: str,
    session: Session = Depends(get_session),
) -> CandidateDetail:
    repo = CandidateRepository(session)
    row = repo.get(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    matrix = PayoffMatrix.model_validate(row.payoff_matrix)
    risk = RiskScore.model_validate(row.risk_scores) if row.risk_scores else None
    return CandidateDetail(
        id=str(row.id),
        opportunity_type=OpportunityType(row.opportunity_type),
        market_ids=row.market_ids,
        payoff_matrix=matrix,
        risk_score=risk,
        simulation_result=None,
        court_decision=CourtDecision(row.court_decision),
        created_at=row.detected_at,
    )
