from __future__ import annotations

from sqlalchemy.orm import Session

from parallax.calibration.service import CalibrationService
from parallax.config import settings
from parallax.shared.schemas import SolverPolicy

SOLVER_VERSION = "generalized-payoff-v1"


def build_solver_policy(*, friction_bps: int | None = None, session: Session | None = None) -> SolverPolicy:
    effective_friction_bps = settings.friction_bps if friction_bps is None else friction_bps
    policy_key = "default"
    metadata: dict[str, object] = {"source": "settings"}

    if session is not None:
        active_policy = CalibrationService(session).active_policy()
        if active_policy is not None:
            solver_penalties = active_policy.solver_penalties or {}
            identity_penalty = float(solver_penalties.get("identity_penalty", 0.0) or 0.0)
            execution_penalty = float(solver_penalties.get("execution_penalty", 0.0) or 0.0)
            effective_friction_bps += int(round((identity_penalty + execution_penalty) * 100))
            policy_key = active_policy.policy_version
            metadata = {
                "source": "active_policy",
                "policy_version": active_policy.policy_version,
                "solver_penalties": solver_penalties,
            }

    return SolverPolicy(
        policy_key=policy_key,
        solver_version=SOLVER_VERSION,
        min_profit_after_friction=effective_friction_bps / 10_000,
        max_quotes_staleness_seconds=settings.court_max_quote_staleness_seconds,
        max_leg_count_for_custom_enumerator=8,
        require_verified_identity_for_tradeable=True,
        require_proof_for_persistence=True,
        capital_limit=1.0,
        require_executable_pricing_when_available=True,
        metadata=metadata,
    )
