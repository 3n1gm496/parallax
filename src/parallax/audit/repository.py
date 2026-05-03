from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import not_
from sqlalchemy.orm import Session
from parallax.db.models import AuditEvent

_LEGACY_EVENT_PREFIX = "oddpool.%"


class AuditRepository:
    """Append-only. No update or delete methods are provided."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict,
    ) -> AuditEvent:
        event = AuditEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(event)
        return event

    def list_for_entity(self, entity_type: str, entity_id: str) -> list[AuditEvent]:
        return (
            self._session.query(AuditEvent)
            .filter_by(entity_type=entity_type, entity_id=entity_id)
            .filter(not_(AuditEvent.event_type.like(_LEGACY_EVENT_PREFIX)))
            .order_by(AuditEvent.created_at)
            .all()
        )

    def list_recent(self, limit: int = 100) -> list[AuditEvent]:
        return (
            self._session.query(AuditEvent)
            .filter(not_(AuditEvent.event_type.like(_LEGACY_EVENT_PREFIX)))
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
            .all()
        )
