from __future__ import annotations

from parallax.config import settings
from parallax.shared.schemas import SolverPolicy

SOLVER_VERSION = "generalized-payoff-v1"


def build_solver_policy(*, friction_bps: int | None = None) -> SolverPolicy:
    effective_friction_bps = settings.friction_bps if friction_bps is None else friction_bps
    return SolverPolicy(
        policy_key="default",
        solver_version=SOLVER_VERSION,
        min_profit_after_friction=effective_friction_bps / 10_000,
        max_quotes_staleness_seconds=settings.court_max_quote_staleness_seconds,
        max_leg_count_for_custom_enumerator=8,
        require_verified_identity_for_tradeable=True,
        require_proof_for_persistence=True,
        capital_limit=1.0,
        require_executable_pricing_when_available=True,
        metadata={"source": "settings"},
    )
