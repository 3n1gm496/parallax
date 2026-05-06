import msgspec
from datetime import datetime, timezone
from typing import Literal

ExecutionPath = Literal["primary_proof_based", "calibrated_model", "degraded_fallback", "offline_validation"]
ExecutionMode = Literal[
    "heuristic",
    "snapshot_based",
    "replay_based",
    "degraded",
    "primary_proof_based",
    "calibrated_model",
    "degraded_fallback",
    "offline_validation",
]


class OrderbookLevel(msgspec.Struct):
    price: float  # 0.0–1.0 (probability / dollar price per contract)
    size: float   # number of contracts


class OrderbookSide(msgspec.Struct):
    levels: list[OrderbookLevel] = msgspec.field(default_factory=list)

    @property
    def total_depth(self) -> float:
        return sum(level.size for level in self.levels)

    def depth_at_or_better(self, price: float, side: Literal["bid", "ask"]) -> float:
        if side == "bid":
            return sum(lv.size for lv in self.levels if lv.price >= price)
        return sum(lv.size for lv in self.levels if lv.price <= price)

    def vwap(self, size: float, *, side: Literal["bid", "ask"] = "ask") -> float | None:
        """VWAP to fill `size` contracts from this side of the book."""
        if not self.levels or size <= 0:
            return None
        reverse = side == "bid"
        sorted_levels = sorted(self.levels, key=lambda lv: lv.price, reverse=reverse)
        filled = 0.0
        cost = 0.0
        for level in sorted_levels:
            take = min(level.size, size - filled)
            cost += take * level.price
            filled += take
            if filled >= size:
                break
        if filled < size - 1e-9:
            return None
        return cost / filled

    def as_rust_levels(self) -> list[tuple[float, float]]:
        """Export as list of (price, size) tuples for parallax_core functions."""
        return [(lv.price, lv.size) for lv in self.levels]


class OrderbookSnapshot(msgspec.Struct):
    id: str
    platform: Literal["polymarket", "kalshi"]
    market_id: str
    outcome: str                  # "YES" or "NO"
    captured_at: datetime
    token_id: str | None = None  # Polymarket CLOB token id; None for Kalshi
    bids: OrderbookSide = msgspec.field(default_factory=OrderbookSide)
    asks: OrderbookSide = msgspec.field(default_factory=OrderbookSide)
    mid_price: float | None = None
    spread_bps: float | None = None

    @property
    def staleness_seconds(self) -> float:
        ts = self.captured_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())

    @property
    def is_stale(self) -> bool:
        return self.staleness_seconds > 60.0

    def to_rust_orderbook(self):
        """
        [PHASE 3] Optimized bridge to Rust. Uses batch updates to minimize
        Python-to-Rust call overhead.
        """
        try:
            import parallax_core  # type: ignore[import]
            ob = parallax_core.Orderbook(self.market_id, self.platform)
            
            # Direct batch update from level price/size list
            ob.batch_update_bids([(lv.price, lv.size) for lv in self.bids.levels])
            ob.batch_update_asks([(lv.price, lv.size) for lv in self.asks.levels])
            
            ts_ns = int(self.captured_at.timestamp() * 1_000_000_000)
            ob.set_last_update_ns(ts_ns)
            return ob
        except (ImportError, AttributeError):
            return None


class DepthAnalysis(msgspec.Struct):
    market_id: str
    outcome: str
    required_size: float
    available_depth: float
    is_supported: bool
    vwap_price: float | None = None
    price_impact_bps: float | None = None
    snapshot_id: str | None = None
