from __future__ import annotations
import uuid
from sqlalchemy.orm import Session
from parallax.candidates.repository import CandidateRepository
from parallax.db.models import AutopsyRecord
from parallax.shared.schemas import AutopsyLabel, ResolutionType


class AutopsyService:
    """Record post-resolution analysis for a candidate and persist autopsy labels."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._candidate_repo = CandidateRepository(session)

    def record(
        self,
        candidate_id: str,
        actual_resolution: dict[str, str],
        resolution_type: ResolutionType,
        position_id: str | None = None,
        labels: list[AutopsyLabel] | None = None,
    ) -> AutopsyRecord:
        autopsy_labels = self._normalize_labels(resolution_type, labels or [])
        record = AutopsyRecord(
            id=uuid.uuid4(),
            candidate_id=uuid.UUID(candidate_id),
            position_id=uuid.UUID(position_id) if position_id else None,
            actual_resolution=actual_resolution,
            resolution_type=resolution_type.value,
            identity_error=resolution_type == ResolutionType.IDENTITY_ERROR,
            labels=[label.value for label in autopsy_labels],
        )
        self._session.add(record)
        self._candidate_repo.close(candidate_id)
        self._session.flush()
        return record

    def list_for_candidate(self, candidate_id: str) -> list[AutopsyRecord]:
        return (
            self._session.query(AutopsyRecord)
            .filter_by(candidate_id=uuid.UUID(candidate_id))
            .all()
        )

    @staticmethod
    def _normalize_labels(
        resolution_type: ResolutionType,
        labels: list[AutopsyLabel],
    ) -> list[AutopsyLabel]:
        normalized = {label for label in labels}
        if resolution_type == ResolutionType.IDENTITY_ERROR:
            normalized.add(AutopsyLabel.FALSE_EQUIVALENCE)
        if resolution_type == ResolutionType.ORACLE_DIVERGENCE:
            normalized.add(AutopsyLabel.ORACLE_MISMATCH)
        return sorted(normalized, key=lambda item: item.value)
