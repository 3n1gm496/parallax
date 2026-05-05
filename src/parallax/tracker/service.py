from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.candidates.repository import CandidateRepository
from parallax.certificates.service import CertificateService
from parallax.config import settings
from parallax.db.models import OpportunityCandidate, PaperPosition
from parallax.shared.schemas import CourtDecision, PayoffMatrix, TradeProofCertificateStatus


class TrackerService:
    """Open and close paper positions linked to approved opportunity candidates."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._candidate_repo = CandidateRepository(session)
        self._certificates = CertificateService(session)

    def open_position(self, candidate_id: str) -> PaperPosition | None:
        """Open a paper position for a candidate. Returns None if already open."""
        if settings.runtime_global_pause or settings.runtime_degraded_read_only:
            return None
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
        if candidate.court_decision != CourtDecision.APPROVED.value:
            return None
        certificate = self._certificates.get_for_candidate(candidate_id)
        if certificate is None or certificate.certificate_status != TradeProofCertificateStatus.ISSUED.value:
            return None

        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
        position = PaperPosition(
            id=uuid.uuid4(),
            candidate_id=uuid.UUID(candidate_id),
            certificate_id=certificate.id,
            status="OPEN",
            legs_json=[leg.model_dump() for leg in matrix.legs],
        )
        self._session.add(position)
        candidate.court_decision = CourtDecision.PAPER_TRADE.value
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
        self._candidate_repo.close(str(position.candidate_id))
        self._session.flush()
        return True

    def get_open_positions(self) -> list[PaperPosition]:
        return (
            self._session.query(PaperPosition)
            .filter_by(status="OPEN")
            .all()
        )

    def list_positions(self, status: str | None = None, limit: int = 100) -> list[PaperPosition]:
        query = self._session.query(PaperPosition).order_by(PaperPosition.opened_at.desc())
        if status is not None:
            query = query.filter_by(status=status)
        return query.limit(limit).all()

    def get_position(self, position_id: str) -> PaperPosition | None:
        return self._session.get(PaperPosition, uuid.UUID(position_id))
