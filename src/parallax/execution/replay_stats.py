from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from parallax.db.models import CandidateDecisionSnapshot, OpportunityCandidate, PaperPosition

MIN_HISTORY = 3
MAX_LOOKBACK = 20


@dataclass
class ReplayStats:
    opportunity_type: str
    n_settled: int
    win_rate: float
    mean_edge_capture: float


class ReplayStatisticsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_stats(self, opportunity_type: str) -> ReplayStats | None:
        rows = self._session.execute(
            select(
                PaperPosition.actual_pnl,
                CandidateDecisionSnapshot.simulation_result,
            )
            .join(OpportunityCandidate, OpportunityCandidate.id == PaperPosition.candidate_id)
            .join(
                CandidateDecisionSnapshot,
                CandidateDecisionSnapshot.candidate_id == PaperPosition.candidate_id,
            )
            .where(
                PaperPosition.status == "CLOSED",
                PaperPosition.actual_pnl.isnot(None),
                OpportunityCandidate.opportunity_type == opportunity_type,
            )
            .order_by(PaperPosition.closed_at.desc())
            .limit(MAX_LOOKBACK)
        ).all()

        if len(rows) < MIN_HISTORY:
            return None

        n_profitable = sum(1 for pnl, _ in rows if pnl is not None and pnl > 0)
        win_rate = round(n_profitable / len(rows), 4)

        edge_captures: list[float] = []
        for actual_pnl, sim_result in rows:
            if not isinstance(sim_result, dict):
                continue
            stored_edge = float(sim_result.get("executable_edge") or 0.0)
            if stored_edge > 1e-9 and actual_pnl is not None:
                edge_captures.append(actual_pnl / stored_edge)

        if not edge_captures:
            return None

        mean_edge_capture = round(sum(edge_captures) / len(edge_captures), 4)
        return ReplayStats(
            opportunity_type=opportunity_type,
            n_settled=len(rows),
            win_rate=win_rate,
            mean_edge_capture=mean_edge_capture,
        )
