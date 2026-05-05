from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from parallax.api.deps import get_read_session, get_write_session, require_read_access, require_write_access
from parallax.certificates.service import CertificateService
from parallax.candidates.service import CandidateReadService
from parallax.shared.schemas import (
    CandidateDetail,
    CourtAssessment,
    DecisionSnapshot,
    CandidateSummary,
    DecisionLedgerEntry,
    TradeProofCertificate,
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


@router.get("/candidates/{candidate_id}/decision-ledger", response_model=list[DecisionLedgerEntry])
def get_candidate_decision_ledger(
    candidate_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> list[DecisionLedgerEntry]:
    service = CandidateReadService(session)
    try:
        service.get_detail(candidate_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return service.list_decision_ledger_entries(candidate_id, limit=limit)


@router.get("/candidates/{candidate_id}/certificate", response_model=TradeProofCertificate)
def get_candidate_certificate(
    candidate_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> TradeProofCertificate:
    row = CertificateService(session).get_for_candidate(candidate_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return CertificateService.to_schema(row)


@router.post("/candidates/{candidate_id}/certificate/issue", response_model=TradeProofCertificate)
def issue_candidate_certificate(
    candidate_id: str,
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_write_session),
) -> TradeProofCertificate:
    try:
        row = CertificateService(session).issue(candidate_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CertificateService.to_schema(row)


@router.post("/candidates/{candidate_id}/backtest", response_model=CourtAssessment)
def backtest_candidate(
    candidate_id: str,
    _auth: None = Depends(require_write_access), # Use write access to prevent abuse
    session: Session = Depends(get_write_session),
) -> CourtAssessment:
    """
    [Opp 17] One-Click Backtest:
    Replays the Court's evaluation logic for a given candidate, returning the full assessment and trace.
    """
    from parallax.court.service import CourtService
    court_svc = CourtService(session)
    
    try:
        assessment = court_svc.assess(candidate_id)
        return assessment
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

