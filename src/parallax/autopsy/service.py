from __future__ import annotations
import uuid
from sqlalchemy.orm import Session
from parallax.db.models import AutopsyRecord
from parallax.shared.schemas import ResolutionType


class AutopsyService:
    """Stub: record post-resolution analysis for a candidate.

    Slice 1 records the actual resolution and flags identity errors.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        candidate_id: str,
        actual_resolution: dict[str, str],
        resolution_type: ResolutionType,
        position_id: str | None = None,
    ) -> AutopsyRecord:
        record = AutopsyRecord(
            id=uuid.uuid4(),
            candidate_id=uuid.UUID(candidate_id),
            position_id=uuid.UUID(position_id) if position_id else None,
            actual_resolution=actual_resolution,
            resolution_type=resolution_type.value,
            identity_error=resolution_type == ResolutionType.IDENTITY_ERROR,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_for_candidate(self, candidate_id: str) -> list[AutopsyRecord]:
        return (
            self._session.query(AutopsyRecord)
            .filter_by(candidate_id=uuid.UUID(candidate_id))
            .all()
        )
