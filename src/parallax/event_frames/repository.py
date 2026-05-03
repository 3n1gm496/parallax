from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from parallax.db.models import CanonicalEventFrame, EventFrameMembership


class EventFrameRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_key(self, frame_key: str) -> CanonicalEventFrame | None:
        return self._session.query(CanonicalEventFrame).filter_by(frame_key=frame_key).first()

    def get_for_market(self, raw_market_id: str) -> CanonicalEventFrame | None:
        membership = (
            self._session.query(EventFrameMembership)
            .filter(EventFrameMembership.raw_market_id == raw_market_id)
            .order_by(EventFrameMembership.created_at.desc())
            .first()
        )
        if membership is None:
            return None
        return self._session.get(CanonicalEventFrame, membership.frame_id)

    def list_market_ids(self, frame_id: uuid.UUID) -> list[str]:
        rows = self._session.query(EventFrameMembership).filter(EventFrameMembership.frame_id == frame_id).all()
        return [row.raw_market_id for row in rows]

    def get_or_create_frame(
        self,
        *,
        frame_key: str,
        frame_type: str,
        title: str,
        domain: str,
        canonical_event_id: uuid.UUID | None = None,
    ) -> CanonicalEventFrame:
        existing = self.get_by_key(frame_key)
        if existing is not None:
            existing.title = title
            existing.domain = domain
            existing.frame_type = frame_type
            existing.canonical_event_id = canonical_event_id
            return existing
        row = CanonicalEventFrame(
            id=uuid.uuid4(),
            frame_key=frame_key,
            frame_type=frame_type,
            title=title,
            domain=domain,
            canonical_event_id=canonical_event_id,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def upsert_membership(
        self,
        *,
        raw_market_id: str,
        frame_id: uuid.UUID,
        membership_type: str,
        confidence: float,
        evidence: dict,
    ) -> EventFrameMembership:
        row = (
            self._session.query(EventFrameMembership)
            .filter(
                EventFrameMembership.raw_market_id == raw_market_id,
                EventFrameMembership.frame_id == frame_id,
            )
            .first()
        )
        if row is None:
            row = EventFrameMembership(
                raw_market_id=raw_market_id,
                frame_id=frame_id,
                membership_type=membership_type,
                confidence=confidence,
                evidence=evidence,
            )
            self._session.add(row)
        else:
            row.membership_type = membership_type
            row.confidence = confidence
            row.evidence = evidence
        self._session.flush()
        return row
