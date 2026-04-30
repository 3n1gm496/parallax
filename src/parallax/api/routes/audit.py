from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from parallax.api.deps import get_session
from parallax.audit.repository import AuditRepository
from parallax.shared.schemas import AuditEventResponse

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=list[AuditEventResponse])
def list_audit_events(
    limit: int = 100,
    session: Session = Depends(get_session),
) -> list[AuditEventResponse]:
    repo = AuditRepository(session)
    rows = repo.list_recent(limit=limit)
    return [
        AuditEventResponse(
            id=str(r.id),
            event_type=r.event_type,
            entity_id=r.entity_id,
            payload=r.payload,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/audit/{entity_type}/{entity_id}", response_model=list[AuditEventResponse])
def list_audit_for_entity(
    entity_type: str,
    entity_id: str,
    session: Session = Depends(get_session),
) -> list[AuditEventResponse]:
    repo = AuditRepository(session)
    rows = repo.list_for_entity(entity_type, entity_id)
    return [
        AuditEventResponse(
            id=str(r.id),
            event_type=r.event_type,
            entity_id=r.entity_id,
            payload=r.payload,
            created_at=r.created_at,
        )
        for r in rows
    ]
