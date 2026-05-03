from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from parallax.api.deps import (
    get_read_session,
    get_write_session,
    require_read_access,
    require_write_access,
)
from parallax.audit.service import AuditService
from parallax.autopsy.service import AutopsyService
from parallax.shared.schemas import (
    AutopsyLabel,
    AutopsyRecordResponse,
    Leg,
    PositionDetail,
    PositionSummary,
    SettlementRequest,
)
from parallax.tracker.service import TrackerService

router = APIRouter(tags=["positions"])


@router.get("/positions", response_model=list[PositionSummary])
def list_positions(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> list[PositionSummary]:
    tracker = TrackerService(session)
    rows = tracker.list_positions(status=status, limit=limit)
    return [
        PositionSummary(
            id=str(row.id),
            candidate_id=str(row.candidate_id),
            status=row.status,
            opened_at=row.opened_at,
            closed_at=row.closed_at,
            actual_pnl=row.actual_pnl,
        )
        for row in rows
    ]


@router.get("/positions/{position_id}", response_model=PositionDetail)
def get_position(
    position_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> PositionDetail:
    tracker = TrackerService(session)
    row = tracker.get_position(position_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Position not found")
    return PositionDetail(
        id=str(row.id),
        candidate_id=str(row.candidate_id),
        status=row.status,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        actual_pnl=row.actual_pnl,
        legs=[Leg.model_validate(leg) for leg in row.legs_json],
    )


@router.get("/candidates/{candidate_id}/autopsy", response_model=list[AutopsyRecordResponse])
def list_candidate_autopsy(
    candidate_id: str,
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> list[AutopsyRecordResponse]:
    svc = AutopsyService(session)
    rows = svc.list_for_candidate(candidate_id)
    return [
        AutopsyRecordResponse(
            id=str(row.id),
            candidate_id=str(row.candidate_id),
            position_id=str(row.position_id) if row.position_id else None,
            actual_resolution=row.actual_resolution,
            resolution_type=row.resolution_type,
            identity_error=row.identity_error,
            labels=[AutopsyLabel(label) for label in (row.labels or [])],
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/positions/{position_id}/settle", response_model=AutopsyRecordResponse)
def settle_position(
    position_id: str,
    payload: SettlementRequest,
    _auth: None = Depends(require_write_access),
    session: Session = Depends(get_write_session),
) -> AutopsyRecordResponse:
    tracker = TrackerService(session)
    position = tracker.get_position(position_id)
    if position is None:
        raise HTTPException(status_code=404, detail="Position not found")
    if position.status != "OPEN":
        raise HTTPException(status_code=409, detail="Position already settled")

    closed = tracker.close_position(position_id, actual_pnl=payload.actual_pnl)
    if not closed:
        raise HTTPException(status_code=409, detail="Position could not be closed")

    autopsy = AutopsyService(session).record(
        candidate_id=str(position.candidate_id),
        position_id=position_id,
        actual_resolution=payload.actual_resolution,
        resolution_type=payload.resolution_type,
        labels=payload.labels,
    )
    AuditService(session).record(
        "position.settled",
        "position",
        position_id,
        {
            "candidate_id": str(position.candidate_id),
            "actual_pnl": payload.actual_pnl,
            "resolution_type": payload.resolution_type.value,
            "labels": [label.value for label in payload.labels],
        },
    )
    return AutopsyRecordResponse(
        id=str(autopsy.id),
        candidate_id=str(autopsy.candidate_id),
        position_id=str(autopsy.position_id) if autopsy.position_id else None,
        actual_resolution=autopsy.actual_resolution,
        resolution_type=autopsy.resolution_type,
        identity_error=autopsy.identity_error,
        labels=[AutopsyLabel(label) for label in (autopsy.labels or [])],
        created_at=autopsy.created_at,
    )
