# ─────────────────────────────────────────────────────────────────────────────
# src/parallax/cache/schemas.py
#
# Strongly-typed schemas for the Hot Cache layer.
# These are the "compiled execution recipes" that the Rust hot path consumes.
# They represent the output of the Cold Path (NLP + Graph → compiled baskets).
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True, frozen=True)
class CachedLeg:
    """
    A single leg of an arbitrage basket pre-compiled for execution.
    Using __slots__ + frozen=True means this is effectively immutable
    and uses minimal memory (no __dict__ overhead).
    """
    market_id: str
    platform: str          # "kalshi" | "polymarket"
    side: str              # "YES" | "NO"
    action: str            # "BUY" | "SELL"
    token_id: str | None   # Polymarket CLOB token id; None for Kalshi
    max_price: float       # IOC limit price ceiling
    target_size: float     # Target position size in contracts


@dataclass(slots=True)
class CompiledArbitrageSet:
    """
    A fully compiled, pre-validated arbitrage opportunity ready for instant
    execution by the Hot Path engine.

    This is the unit of work that flows:
      Neo4j (Knowledge Graph) → HotCache (RAM/SharedMem) → Rust Solver (execution gate)

    Lifecycle:
      - Created by: SemanticAgent.compile_arbitrage_sets()
      - Stored in:  HotCache (L1 dict + L2 shared memory)
      - Consumed by: StreamScanner._rust_edge_exists() → ExecutionManager
      - Expired by: HotCache TTL eviction thread
    """
    set_id: str
    legs: list[CachedLeg]
    expected_edge_bps: float     # Expected net edge (after friction) in basis points
    min_confidence: float        # Semantic confidence score from the NLP agent
    compiled_at: datetime
    expires_at: datetime
    source: str = "semantic_agent"   # Who created this set

    @property
    def is_valid(self) -> bool:
        return (
            len(self.legs) >= 2
            and self.expected_edge_bps > 0
            and datetime.now(timezone.utc) < self.expires_at
        )

    @property
    def market_ids(self) -> list[str]:
        return [leg.market_id for leg in self.legs]

    def to_rust_args(self) -> dict:
        """
        Serialise into the argument structure expected by parallax_core.compute_arbitrage_edge().
        Called by the hot path immediately before placing an order.
        """
        legs_by_venue: dict[str, CachedLeg] = {}
        for leg in self.legs:
            legs_by_venue[leg.platform] = leg

        kalshi_leg   = legs_by_venue.get("kalshi")
        poly_leg     = legs_by_venue.get("polymarket")

        return {
            "a_ask":         kalshi_leg.max_price  if kalshi_leg  else 0.0,
            "b_ask":         poly_leg.max_price    if poly_leg    else 0.0,
            "a_ask_size":    kalshi_leg.target_size if kalshi_leg else 0.0,
            "b_ask_size":    poly_leg.target_size   if poly_leg   else 0.0,
        }
