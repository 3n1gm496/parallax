from __future__ import annotations

import pulp
from parallax.shared.schemas import OutcomeStateSpace, PayoffMatrix, SolverPolicy


class BasketOptimizer:
    def optimize(self, matrix: PayoffMatrix, state_space: OutcomeStateSpace, policy: SolverPolicy) -> dict[str, object]:
        if not matrix.legs:
            return {
                "solver": "milp-pulp-v1",
                "selected_legs": [],
                "capital_limit": policy.capital_limit,
                "total_quantity": 0.0,
                "total_cost": 0.0,
                "n_ary_supported": False,
            }

        # [Spietato Audit] Complexity Breaker: Prevent O(2^N) hang
        if len(state_space.valid_states) > 5000:
            return {
                "solver": "milp-pulp-v1",
                "selected_legs": [],
                "error": "State space complexity too high for real-time solver",
                "n_ary_supported": True,
            }

        prob = pulp.LpProblem("Arbitrage_Maximization", pulp.LpMaximize)

        q_vars = []
        for i, leg in enumerate(matrix.legs):
            q_vars.append(pulp.LpVariable(f"q_{i}", lowBound=0.0, upBound=leg.max_size))

        min_profit = pulp.LpVariable("min_profit")
        prob += min_profit

        # [Spietato Audit] Apply friction (fees) to the model
        friction_decimal = matrix.friction_bps / 10000.0

        # Budget constraint
        prob += pulp.lpSum(
            [q_vars[i] * (matrix.legs[i].cost if matrix.legs[i].cost is not None else matrix.legs[i].price) for i in range(len(matrix.legs))]
        ) <= policy.capital_limit

        # State constraints
        for state in state_space.valid_states:
            state_profit_expr = 0
            for i, leg in enumerate(matrix.legs):
                resolution = state.assignments.get(leg.market_id, "NO")
                price = leg.cost if leg.cost is not None else leg.price
                if leg.side == "YES":
                    payout = 1.0 if resolution == "YES" else 0.0
                else:
                    payout = 1.0 if resolution == "NO" else 0.0
                # [Spietato Audit] Profit formula now includes execution friction
                state_profit_expr += q_vars[i] * (payout - price - friction_decimal)
            
            prob += state_profit_expr >= min_profit

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        if pulp.LpStatus[prob.status] != "Optimal" or pulp.value(min_profit) <= 0.0:
            return {
                "solver": "milp-pulp-v1",
                "selected_legs": [],
                "capital_limit": policy.capital_limit,
                "total_quantity": 0.0,
                "total_cost": 0.0,
                "n_ary_supported": len(matrix.legs) > 2,
            }

        sized_legs = []
        total_quantity = 0.0
        total_cost = 0.0

        for i, leg in enumerate(matrix.legs):
            q_val = round(pulp.value(q_vars[i]), 4)
            if q_val < 0.0001:
                continue
            cost_val = leg.cost if leg.cost is not None else leg.price
            c_val = round(cost_val * q_val, 6)

            sized_legs.append(
                {
                    **leg.model_dump(),
                    "quantity": q_val,
                    "cost": c_val,
                }
            )
            total_quantity += q_val
            total_cost += c_val

        return {
            "solver": "milp-pulp-v1",
            "selected_legs": sized_legs,
            "capital_limit": policy.capital_limit,
            "total_quantity": round(total_quantity, 4),
            "total_cost": round(total_cost, 6),
            "n_ary_supported": len(matrix.legs) > 2,
        }
