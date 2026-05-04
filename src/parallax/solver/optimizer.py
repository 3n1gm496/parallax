from __future__ import annotations

from parallax.shared.schemas import Leg, PayoffMatrix, SolverPolicy


class BasketOptimizer:
    def optimize(self, matrix: PayoffMatrix, policy: SolverPolicy) -> dict[str, object]:
        total_quantity = sum(leg.quantity for leg in matrix.legs)
        return {
            "solver": "fallback",
            "selected_legs": [leg.model_dump() for leg in matrix.legs],
            "capital_limit": policy.capital_limit,
            "total_quantity": total_quantity,
            "total_cost": matrix.total_cost,
        }
