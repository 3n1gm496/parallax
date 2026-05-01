from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import OpportunityCandidate, PaperPosition
from parallax.shared.schemas import PayoffMatrix


class TrackerService:
    """Open and close paper positions linked to approved opportunity candidates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def open_position(self, candidate_id: str) -> PaperPosition | None:
        """Open a paper position for a candidate. Returns None if already open."""
        existing = (
            self._session.query(PaperPosition)
            .filter_by(candidate_id=uuid.UUID(candidate_id), status="OPEN")
            .first()
        )
        if existing:
            return None

        candidate: OpportunityCandidate | None = self._session.get(
            OpportunityCandidate, uuid.UUID(candidate_id)
        )
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
        position = PaperPosition(
            id=uuid.uuid4(),
            candidate_id=uuid.UUID(candidate_id),
            status="OPEN",
            legs_json=[leg.model_dump() for leg in matrix.legs],
        )
        self._session.add(position)
        self._session.flush()
        return position

    def close_position(
        self, position_id: str, actual_pnl: float
    ) -> bool:
        """Close a position and record actual PnL. Returns False if not found or already closed."""
        position: PaperPosition | None = self._session.get(
            PaperPosition, uuid.UUID(position_id)
        )
        if position is None or position.status != "OPEN":
            return False

        position.status = "CLOSED"
        position.closed_at = datetime.now(timezone.utc)
        position.actual_pnl = actual_pnl
        self._session.flush()
        return True

    def get_open_positions(self) -> list[PaperPosition]:
        return (
            self._session.query(PaperPosition)
            .filter_by(status="OPEN")
            .all()
        )
