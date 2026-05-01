from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.shared.schemas import PayoffMatrix, SimulationResult


class SimulatorService:
    """Stub: simulate execution of a candidate trade.

    Slice 1 assumes full fill at quoted prices with no slippage.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = CandidateRepository(session)

    def simulate(self, candidate_id: str) -> SimulationResult:
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
        # worst_case_payoff is already post-friction (applied once in DivergenceService)
        simulated_pnl = matrix.worst_case_payoff

        return SimulationResult(
            candidate_id=candidate_id,
            simulated_pnl=round(simulated_pnl, 6),
            friction_bps=matrix.friction_bps,
            fill_probability=1.0,
            is_executable=simulated_pnl > 0,
            note="stub — no order book model",
        )
