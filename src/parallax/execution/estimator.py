from __future__ import annotations

from dataclasses import dataclass

from parallax.execution.schemas import DepthAnalysis, OrderbookSnapshot


@dataclass
class ExecutablePrice:
    """Result of a depth-aware price estimation for one leg."""

    market_id: str
    outcome: str
    side: str           # "buy" or "sell"
    required_size: float
    vwap_price: float | None
    available_depth: float
    is_supported: bool
    price_impact_bps: float | None
    snapshot_id: str | None

    def to_depth_analysis(self) -> DepthAnalysis:
        return DepthAnalysis(
            market_id=self.market_id,
            outcome=self.outcome,
            required_size=self.required_size,
            available_depth=self.available_depth,
            is_supported=self.is_supported,
            vwap_price=self.vwap_price,
            price_impact_bps=self.price_impact_bps,
            snapshot_id=self.snapshot_id,
        )


class DepthAwareExecutablePriceEstimator:
    """Estimate executable price from an orderbook snapshot using VWAP."""

    def estimate(
        self,
        snapshot: OrderbookSnapshot,
        side: str,          # "buy" (lift asks) or "sell" (hit bids)
        size: float,
    ) -> ExecutablePrice:
        book_side = snapshot.asks if side == "buy" else snapshot.bids
        ob_side_str = "ask" if side == "buy" else "bid"

        available = book_side.total_depth
        vwap = book_side.vwap(size, side=ob_side_str)
        is_supported = vwap is not None

        mid = snapshot.mid_price
        impact_bps: float | None = None
        if vwap is not None and mid is not None and mid > 0:
            impact_bps = abs(vwap - mid) / mid * 10000

        return ExecutablePrice(
            market_id=snapshot.market_id,
            outcome=snapshot.outcome,
            side=side,
            required_size=size,
            vwap_price=vwap,
            available_depth=available,
            is_supported=is_supported,
            price_impact_bps=impact_bps,
            snapshot_id=snapshot.id,
        )
