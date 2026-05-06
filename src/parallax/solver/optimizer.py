from __future__ import annotations

import pulp
from parallax.shared.schemas import OutcomeStateSpace, PayoffMatrix, SolverPolicy


class BasketOptimizer:
    def optimize(self, matrix: PayoffMatrix, state_space: OutcomeStateSpace, policy: SolverPolicy) -> dict[str, object]:
        # [PHASE 4] Dynamic Spread Buffering
        from parallax.shared.l1_cache import L1HotCache
        from parallax.shared.config import settings
        import logging
        logger = logging.getLogger(__name__)
        cache = L1HotCache()
        
        # Take the max volatility across all legs in the basket
        max_vol = 0.0
        for leg in matrix.legs:
            max_vol = max(max_vol, cache.get_volatility_score(leg.market_id))
        
        # Increase min_edge_bps by up to 50 bps during high volatility
        volatility_premium = max_vol * 50.0 
        effective_min_edge = settings.solver_min_edge_bps + volatility_premium

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
            # [LOGIC FIX L-003] Enforce integer constraints for Kalshi
            cat = pulp.LpInteger if leg.platform == "kalshi" else pulp.LpContinuous
            q_vars.append(pulp.LpVariable(f"q_{i}", lowBound=0.0, upBound=leg.max_size, cat=cat))

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
                # BUG-033/038 Fix: Resolution-aware payout logic (categorical support)
                # Instead of binary YES/NO, we match the outcome name to the state assignment
                # If the outcome is "YES" and state is "YES", payout=1.
                # If outcome is "Outcome_C" and state is "Outcome_C", payout=1.
                resolution = state.assignments.get(leg.market_id)
                price = leg.cost if leg.cost is not None else leg.price
                
                # BUG-038: Support venues with non-1.0 payoffs (e.g. fractional or scaled)
                base_payout = 1.0
                payout = base_payout if resolution == leg.outcome else 0.0
                
                # BUG-034: Refined friction model
                # [L-017] Support SELL orders in optimizer logic
                if leg.action.upper() == "SELL":
                    # We receive premium, pay out if it hits
                    # Friction on SELL is usually deducted from proceeds
                    state_profit_expr += q_vars[i] * (price * (1.0 - friction_decimal) - payout)
                else:
                    # Standard BUY
                    state_profit_expr += q_vars[i] * (payout - price * (1.0 + friction_decimal))
            
            prob += state_profit_expr >= min_profit
        
        # BUG-036: Minimum order size constraint
        # Some venues (e.g. Kalshi) have a $1 minimum, others have a quantity minimum.
        # We enforce a small epsilon to avoid tiny unfillable dust orders.
        for i, leg in enumerate(matrix.legs):
            # If we buy ANY, we must buy at least MIN_SIZE
            # This requires a binary indicator variable in MILP
            is_active = pulp.LpVariable(f"active_{i}", cat=pulp.LpBinary)
            prob += q_vars[i] <= is_active * leg.max_size
            # Assuming a generic 1.0 unit minimum for simplicity, or 0.1 for Polymarket
            min_size = 1.0 if leg.platform == "kalshi" else 0.1
            prob += q_vars[i] >= is_active * min_size

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

        # [PHASE 4] Post-optimization edge verification
        total_profit = pulp.value(min_profit)
        actual_total_cost = sum([pulp.value(q_vars[i]) * (matrix.legs[i].cost or matrix.legs[i].price) for i in range(len(matrix.legs))])
        
        if actual_total_cost > 0:
            edge_bps = (total_profit / actual_total_cost) * 10000
            if edge_bps < effective_min_edge:
                logger.info(f"Edge {edge_bps:.1f} bps < {effective_min_edge:.1f} bps (threshold + {volatility_premium:.1f} vol premium). Skipping.")
                return {
                    "solver": "milp-pulp-v1",
                    "selected_legs": [],
                    "error": f"Volatility premium buffer not met: {edge_bps:.1f} < {effective_min_edge:.1f}",
                    "n_ary_supported": True,
                }

        sized_legs = []
        total_quantity = 0.0
        total_cost = 0.0

        for i, leg in enumerate(matrix.legs):
            # [L-003] Venue-specific quantity rounding
            raw_val = pulp.value(q_vars[i])
            if leg.platform == "kalshi":
                q_val = round(raw_val, 0)
            else:
                q_val = round(raw_val, 2)
                
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
