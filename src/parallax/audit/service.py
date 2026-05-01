from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.audit.repository import AuditRepository
from parallax.db.models import AuditEvent


class AuditService:
    def __init__(self, session: Session) -> None:
        self._repo = AuditRepository(session)
        self._session = session

    def record(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict,
    ) -> AuditEvent:
        event = self._repo.append(event_type, entity_type, entity_id, payload)
        self._session.flush()
        return event

    def get_history(self, entity_type: str, entity_id: str) -> list[AuditEvent]:
        return self._repo.list_for_entity(entity_type, entity_id)

    def get_recent(self, limit: int = 100) -> list[AuditEvent]:
        return self._repo.list_recent(limit)
