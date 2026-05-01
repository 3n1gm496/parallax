from __future__ import annotations
import uuid
from sqlalchemy.orm import Session
from parallax.db.models import CanonicalEvent, MarketEventLink
from parallax.identity.event_repository import EventRepository


class IdentityService:
    """Resolve raw markets to canonical events and manage market-event links."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = EventRepository(session)

    def get_or_create_event(
        self,
        name: str,
        domain: str,
        platform_group_key: str | None = None,
    ) -> tuple[CanonicalEvent, bool]:
        """Return (event, created). Looks up by group key if provided."""
        if platform_group_key:
            existing = self._repo.get_by_group_key(platform_group_key)
            if existing:
                return existing, False
        event = self._repo.create(name, domain, platform_group_key)
        self._session.flush()
        return event, True

    def link_market(
        self,
        raw_market_id: str,
        canonical_event_id: uuid.UUID,
    ) -> MarketEventLink | None:
        """Link a raw market to a canonical event. Returns None if already linked."""
        existing = self._session.get(
            MarketEventLink, (raw_market_id, canonical_event_id)
        )
        if existing:
            return None
        link = MarketEventLink(
            raw_market_id=raw_market_id,
            canonical_event_id=canonical_event_id,
        )
        self._session.add(link)
        self._session.flush()
        return link

    def get_events_for_market(self, raw_market_id: str) -> list[CanonicalEvent]:
        links = (
            self._session.query(MarketEventLink)
            .filter_by(raw_market_id=raw_market_id)
            .all()
        )
        return [
            self._repo.get(link.canonical_event_id)
            for link in links
            if self._repo.get(link.canonical_event_id) is not None
        ]
