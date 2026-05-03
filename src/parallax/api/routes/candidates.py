from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from parallax.api.deps import get_read_session, require_read_access
from parallax.candidates.service import CandidateReadService
from parallax.shared.schemas import (
    CandidateDetail,
    DecisionSnapshot,
    CandidateSummary,
)

router = APIRouter(tags=["candidates"])


@router.get("/candidates", response_model=list[CandidateSummary])
def list_candidates(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> list[CandidateSummary]:
    return CandidateReadService(session).list_open_summaries(limit=limit, offset=offset)


@router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
def get_candidate(
    candidate_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> CandidateDetail:
    service = CandidateReadService(session)
    try:
        return service.get_detail(candidate_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Candidate not found")


@router.get("/candidates/{candidate_id}/decision", response_model=DecisionSnapshot)
def get_candidate_decision_snapshot(
    candidate_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> DecisionSnapshot:
    service = CandidateReadService(session)
    try:
        detail = service.get_detail(candidate_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Candidate not found")
    snapshot = detail.decision_snapshot
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Decision snapshot not found")
    return snapshot
