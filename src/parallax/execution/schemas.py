from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

ExecutionMode = Literal["heuristic", "snapshot_based", "replay_based", "degraded"]


class OrderbookLevel(BaseModel):
    price: float  # 0.0–1.0 (probability / dollar price per contract)
    size: float   # number of contracts


class OrderbookSide(BaseModel):
    levels: list[OrderbookLevel] = Field(default_factory=list)

    @property
    def total_depth(self) -> float:
        return sum(level.size for level in self.levels)

    def depth_at_or_better(self, price: float, side: Literal["bid", "ask"]) -> float:
        if side == "bid":
            return sum(l.size for l in self.levels if l.price >= price)
        return sum(l.size for l in self.levels if l.price <= price)

    def vwap(self, size: float, *, side: Literal["bid", "ask"] = "ask") -> float | None:
        """VWAP to fill `size` contracts from this side of the book."""
        if not self.levels or size <= 0:
            return None
        reverse = side == "bid"
        sorted_levels = sorted(self.levels, key=lambda l: l.price, reverse=reverse)
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


class OrderbookSnapshot(BaseModel):
    id: str
    platform: Literal["polymarket", "kalshi"]
    market_id: str
    token_id: str | None = None  # Polymarket CLOB token id; None for Kalshi
    outcome: str                  # "YES" or "NO"
    captured_at: datetime
    bids: OrderbookSide = Field(default_factory=OrderbookSide)
    asks: OrderbookSide = Field(default_factory=OrderbookSide)
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


class DepthAnalysis(BaseModel):
    market_id: str
    outcome: str
    required_size: float
    available_depth: float
    is_supported: bool
    vwap_price: float | None = None
    price_impact_bps: float | None = None
    snapshot_id: str | None = None
