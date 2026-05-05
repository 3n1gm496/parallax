from __future__ import annotations

from dataclasses import dataclass

from parallax.db.models import RawMarket
from parallax.execution.schemas import OrderbookSnapshot
from parallax.shared.schemas import (
    Leg,
    OpportunityType,
    OutcomeState,
    OutcomeStateSpace,
    PayoffMatrix,
    ProofObject,
    RelationType,
    Scenario,
    SolverPolicy,
)


@dataclass(slots=True)
class PayoffBuildResult:
    payoff_matrix: PayoffMatrix
    proof: ProofObject
    displayed_edge: float
    executable_edge: float
    executable_pricing_used: bool


class PayoffMatrixGenerator:
    def build(
        self,
        *,
        markets: list[RawMarket],
        relation_type: RelationType,
        state_space: OutcomeStateSpace,
        policy: SolverPolicy,
        solver_version: str,
        constraint_fingerprint: str,
        identity_version: str,
        relation_set_keys: list[str],
        assumptions: list[str],
        orderbooks: dict[str, OrderbookSnapshot] | None = None,
    ) -> PayoffBuildResult | None:
        if len(markets) < 2:
            return None
        if state_space.blocked_reason:
            return None

        if not orderbooks:
            return None

        legs, opportunity_type = self._build_legs(markets, relation_type, orderbooks)
        if not legs:
            return None
        total_cost = round(sum(leg.cost if leg.cost is not None else leg.price for leg in legs), 6)

        payoff_by_state: dict[str, float] = {}
        scenarios: list[Scenario] = []
        breaking_scenarios: list[Scenario] = []
        valid_states: list[OutcomeState] = list(state_space.valid_states)
        scenario_source_states = valid_states
        if relation_type in {RelationType.MUTUALLY_EXCLUSIVE, RelationType.EXHAUSTIVE, RelationType.EXHAUSTIVE_PARTITION}:
            filtered = [
                state
                for state in valid_states
                if sum(1 for assignment in state.assignments.values() if assignment == "YES") == 1
            ]
            if filtered:
                scenario_source_states = filtered

        for state in scenario_source_states:
            raw_payoff = self._state_payoff(state, legs)
            net_payoff = round(raw_payoff - self._friction(total_cost, policy), 6)
            payoff_by_state[state.state_id] = net_payoff
            is_breaking = net_payoff <= 0
            scenario = Scenario(
                name=state.state_id,
                description=state.explanation or self._describe_state(state),
                payoff=net_payoff,
                is_breaking=is_breaking,
            )
            scenarios.append(scenario)
            if is_breaking:
                breaking_scenarios.append(scenario)

        if not scenarios:
            return None
        worst_case = min(scenario.payoff for scenario in scenarios)
        best_case = max(scenario.payoff for scenario in scenarios)
        proof_status = "verified" if worst_case > 0 else "false_arbitrage"
        matrix = PayoffMatrix(
            legs=legs,
            total_cost=total_cost,
            scenarios=scenarios,
            worst_case_payoff=worst_case,
            best_case_payoff=best_case,
            breaking_scenario=breaking_scenarios[0] if breaking_scenarios else None,
            opportunity_type=opportunity_type,
            friction_bps=int(policy.min_profit_after_friction * 10_000),
        )
        state_space.breaking_state_ids = [scenario.name for scenario in breaking_scenarios]
        proof = ProofObject(
            solver_version=solver_version,
            constraint_fingerprint=constraint_fingerprint,
            policy_key=policy.policy_key,
            policy_version=policy.solver_version,
            identity_version=identity_version,
            proof_status=proof_status,
            relation_types=[relation_type],
            relation_set_keys=relation_set_keys,
            assumptions=assumptions,
            executable_pricing_used=bool(orderbooks),
            valid_states=valid_states,
            impossible_scenarios=state_space.impossible_states,
            breaking_scenarios=breaking_scenarios,
            payoff_by_state=payoff_by_state,
            audit_trail=[
                {"step": "enumerate", "valid_states": len(valid_states), "impossible_states": len(state_space.impossible_states)},
                {"step": "price", "displayed_edge": worst_case, "best_case": best_case, "executable_pricing_used": bool(orderbooks)},
            ],
        )
        return PayoffBuildResult(
            payoff_matrix=matrix,
            proof=proof,
            displayed_edge=worst_case,
            executable_edge=worst_case,
            executable_pricing_used=bool(orderbooks),
        )

    @staticmethod
    def _friction(total_cost: float, policy: SolverPolicy) -> float:
        return total_cost * policy.min_profit_after_friction

    def _build_legs(
        self,
        markets: list[RawMarket],
        relation_type: RelationType,
        orderbooks: dict[str, OrderbookSnapshot],
    ) -> tuple[list[Leg], OpportunityType]:
        for market in markets:
            if market.id not in orderbooks:
                return ([], OpportunityType.FALSE_ARBITRAGE)

        def _get_tranches(market_id: str, side: str, platform: str) -> list[Leg]:
            ob = orderbooks[market_id]
            tranches = []
            if side == "YES":
                for level in ob.asks.levels:
                    tranches.append(Leg(market_id=market_id, side="YES", price=level.price, quantity=level.size, cost=level.price, max_size=level.size, platform=platform))
            else:
                for level in ob.bids.levels:
                    price = 1.0 - level.price
                    tranches.append(Leg(market_id=market_id, side="NO", price=price, quantity=level.size, cost=price, max_size=level.size, platform=platform))
            return tranches

        if relation_type in {RelationType.EQUIVALENT, RelationType.DUPLICATE}:
            ordered = sorted(markets, key=lambda market: orderbooks[market.id].mid_price or 0.5)
            buyer = ordered[0]
            seller = ordered[-1]
            legs = _get_tranches(buyer.id, "YES", buyer.platform) + _get_tranches(seller.id, "NO", seller.platform)
            return legs, OpportunityType.DUPLICATE_DIVERGENCE

        if relation_type in {RelationType.MUTUALLY_EXCLUSIVE, RelationType.EXHAUSTIVE, RelationType.EXHAUSTIVE_PARTITION}:
            legs = []
            for market in markets:
                legs.extend(_get_tranches(market.id, "NO", market.platform))
            op_type = OpportunityType.EXHAUSTIVE_SET_MISPRICING if len(markets) > 2 else OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING
            return legs, op_type

        if relation_type in {RelationType.SUBSET, RelationType.SUPERSET, RelationType.PREREQUISITE, RelationType.INVERSE}:
            a, b = markets[0], markets[1]
            legs = _get_tranches(a.id, "YES", a.platform) + _get_tranches(b.id, "NO", b.platform)
            op_type = OpportunityType.ASYMMETRIC_STRUCTURAL_BET if relation_type != RelationType.INVERSE else OpportunityType.SETTLEMENT_YIELD
            return legs, op_type

        return ([], OpportunityType.FALSE_ARBITRAGE)

    def _state_payoff(self, state: OutcomeState, legs: list[Leg]) -> float:
        payoff = 0.0
        for leg in legs:
            resolution = state.assignments.get(leg.market_id, "NO")
            if leg.side == "YES":
                payoff += 1.0 - (leg.cost or leg.price) if resolution == "YES" else -(leg.cost or leg.price)
            else:
                payoff += 1.0 - (leg.cost or leg.price) if resolution == "NO" else -(leg.cost or leg.price)
        return payoff

    @staticmethod
    def _describe_state(state: OutcomeState) -> str:
        parts = [f"{market_id}={value}" for market_id, value in sorted(state.assignments.items())]
        return ", ".join(parts)
