from __future__ import annotations

from dataclasses import dataclass

from parallax.execution.schemas import OrderbookSnapshot


@dataclass
class FillSimulation:
    """Outcome of simulating a fill against live book depth."""

    market_id: str
    outcome: str
    side: str
    requested_size: float
    expected_fill_size: float
    fill_probability: float     # 0–1 estimate of full fill
    partial_fill_risk: float    # 0–1; high → payoff may invert on partial fill
    expected_price: float | None
    snapshot_id: str | None


class DepthAwareFillSimulator:
    """
    Estimate fill probability and partial fill risk using orderbook depth.

    Partial fill risk is elevated when available depth is between
    inversion_threshold and full size — meaning we might fill just enough
    to take a position but not enough to close the spread.
    """

    def __init__(self, inversion_threshold: float = 0.4) -> None:
        self._inversion_threshold = inversion_threshold

    def simulate(
        self,
        snapshot: OrderbookSnapshot,
        side: str,           # "buy" or "sell"
        size: float,
        worst_case_payoff: float = 0.0,
    ) -> FillSimulation:
        book_side = snapshot.asks if side == "buy" else snapshot.bids
        ob_side_str = "ask" if side == "buy" else "bid"

        available = book_side.total_depth
        fill_ratio = min(available / size, 1.0) if size > 0 else 0.0
        fill_probability = _fill_probability(fill_ratio)

        # Partial fill risk: high when we'd fill more than threshold but less than full
        if fill_ratio >= 1.0:
            partial_fill_risk = 0.0
        elif fill_ratio >= self._inversion_threshold:
            # Linear ramp: 0 at full fill, 1 at inversion threshold
            partial_fill_risk = 1.0 - (fill_ratio - self._inversion_threshold) / (
                1.0 - self._inversion_threshold
            )
        else:
            # Below inversion threshold: likely won't fill meaningfully
            partial_fill_risk = 0.0

        expected_price = book_side.vwap(min(available, size), side=ob_side_str)
        expected_fill = min(available, size)

        return FillSimulation(
            market_id=snapshot.market_id,
            outcome=snapshot.outcome,
            side=side,
            requested_size=size,
            expected_fill_size=expected_fill,
            fill_probability=fill_probability,
            partial_fill_risk=partial_fill_risk,
            expected_price=expected_price,
            snapshot_id=snapshot.id,
        )


def _fill_probability(fill_ratio: float) -> float:
    """Non-linear fill probability: near-full depth → high confidence."""
    if fill_ratio >= 1.0:
        return 0.95
    if fill_ratio >= 0.9:
        return 0.85
    if fill_ratio >= 0.7:
        return 0.70
    if fill_ratio >= 0.5:
        return 0.55
    return fill_ratio * 0.5
