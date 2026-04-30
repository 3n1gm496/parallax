from __future__ import annotations
import uuid
from sqlalchemy.orm import Session
from parallax.db.models import CanonicalEvent


class EventRepository:
    """CRUD for CanonicalEvents (the identity layer)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, event_id: uuid.UUID) -> CanonicalEvent | None:
        return self._session.get(CanonicalEvent, event_id)

    def get_by_group_key(self, platform_group_key: str) -> CanonicalEvent | None:
        return (
            self._session.query(CanonicalEvent)
            .filter_by(platform_group_key=platform_group_key)
            .first()
        )

    def create(
        self,
        name: str,
        domain: str,
        platform_group_key: str | None = None,
    ) -> CanonicalEvent:
        event = CanonicalEvent(
            id=uuid.uuid4(),
            name=name,
            domain=domain,
            platform_group_key=platform_group_key,
        )
        self._session.add(event)
        return event

    def list_active(self, domain: str | None = None) -> list[CanonicalEvent]:
        q = self._session.query(CanonicalEvent).filter_by(status="active")
        if domain:
            q = q.filter_by(domain=domain)
        return q.all()
