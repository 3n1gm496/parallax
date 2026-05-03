from __future__ import annotations
import logging

from sqlalchemy.orm import Session

from parallax.autopsy.service import AutopsyService
from parallax.db.models import OpportunityCandidate, RawMarket
from parallax.shared.schemas import PayoffMatrix, ResolutionType
from parallax.tracker.service import TrackerService

log = logging.getLogger(__name__)

YES_THRESHOLD = 0.9
NO_THRESHOLD = 0.1


def _infer_resolution(yes_price: float) -> str | None:
    """Return 'YES', 'NO', or None when price is ambiguous."""
    if yes_price >= YES_THRESHOLD:
        return "YES"
    if yes_price <= NO_THRESHOLD:
        return "NO"
    return None


def _compute_leg_payoff(side: str, price: float, quantity: float, resolved: str) -> float:
    """Raw dollar payoff for one leg given final resolution."""
    if side == resolved:
        return (1.0 - price) * quantity
    return -price * quantity


class SettlementScannerService:
    """Scan open paper positions and automatically settle those whose markets have closed."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def scan_and_settle(self) -> list[str]:
        """Settle all positions whose underlying markets closed with deterministic prices.

        Returns list of settled position IDs. Skips positions where any market is
        still open or has an ambiguous final price (0.1 < YES price < 0.9).
        """
        tracker = TrackerService(self._session)
        autopsy = AutopsyService(self._session)
        settled: list[str] = []

        for position in tracker.get_open_positions():
            try:
                position_id = str(position.id)
                candidate_id = str(position.candidate_id)

                candidate = self._session.get(OpportunityCandidate, position.candidate_id)
                if candidate is None:
                    log.warning("scanner: candidate %s not found for position %s", candidate_id, position_id)
                    continue

                matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
                market_ids = {leg.market_id for leg in matrix.legs}

                resolutions: dict[str, str] = {}
                skip = False
                for market_id in market_ids:
                    market = self._session.get(RawMarket, market_id)
                    if market is None or not market.is_closed:
                        skip = True
                        break
                    resolved = _infer_resolution(market.outcome_prices[0])
                    if resolved is None:
                        skip = True
                        break
                    resolutions[market_id] = resolved

                if skip:
                    continue

                raw_payoff = sum(
                    _compute_leg_payoff(leg.side, leg.price, leg.quantity, resolutions[leg.market_id])
                    for leg in matrix.legs
                )
                actual_pnl = max(-1.0, min(1.0, raw_payoff / matrix.total_cost))

                closed = tracker.close_position(position_id, actual_pnl)
                if not closed:
                    continue

                autopsy.record(
                    candidate_id=candidate_id,
                    actual_resolution={mid: res for mid, res in resolutions.items()},
                    resolution_type=ResolutionType.CORRECT,
                    position_id=position_id,
                    labels=[],
                )

                settled.append(position_id)
                log.info("scanner: settled position %s pnl=%.4f", position_id, actual_pnl)

            except Exception as exc:
                log.warning("scanner: position %s failed: %s", str(position.id), exc)

        return settled
