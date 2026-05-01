from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.shared.schemas import CourtDecision


class CourtService:
    """Stub: evaluate candidates and assign a court decision.

    Slice 1 implementation approves any candidate with worst_case_payoff > 0
    and watchlists everything else.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CandidateRepository(session)

    def evaluate(self, candidate_id: str) -> CourtDecision:
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        # TODO Slice 2: replace with real risk gating (vol surface, oracle risk, liquidity check)
        decision = (
            CourtDecision.APPROVED
            if candidate.worst_case_payoff > 0
            else CourtDecision.WATCHLIST
        )
        self._repo.update_decision(candidate_id, decision)
        return decision
