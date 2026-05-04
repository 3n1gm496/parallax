from __future__ import annotations

from dataclasses import dataclass

from parallax.db.models import RawMarket
from parallax.shared.schemas import (
    Leg,
    OpportunityType,
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
        executable_prices: dict[str, float] | None = None,
    ) -> PayoffBuildResult | None:
        if len(markets) < 2:
            return None

        price_map = {
            market.id: float(market.outcome_prices[0])
            for market in markets
            if market.outcome_prices and isinstance(market.outcome_prices[0], (int, float))
        }
        if len(price_map) != len(markets):
            return None

        executable = executable_prices or {}
        if relation_type in {RelationType.EQUIVALENT, RelationType.DUPLICATE}:
            payoff = self._equivalent(markets, price_map, executable, policy)
            opportunity_type = OpportunityType.DUPLICATE_DIVERGENCE
        elif relation_type in {RelationType.MUTUALLY_EXCLUSIVE, RelationType.EXHAUSTIVE, RelationType.EXHAUSTIVE_PARTITION}:
            payoff = self._exclusivity(markets, price_map, executable, policy)
            opportunity_type = OpportunityType.EXHAUSTIVE_SET_MISPRICING if len(markets) > 2 else OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING
        elif relation_type in {RelationType.SUBSET, RelationType.SUPERSET, RelationType.PREREQUISITE, RelationType.INVERSE}:
            payoff = self._implication(markets, relation_type, price_map, executable, policy)
            opportunity_type = OpportunityType.ASYMMETRIC_STRUCTURAL_BET
        else:
            return None

        if payoff is None:
            return None

        payoff.opportunity_type = opportunity_type
        breaking = [scenario for scenario in payoff.scenarios if scenario.is_breaking]
        proof_status = "verified" if payoff.worst_case_payoff > 0 else "false_arbitrage"
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
            executable_pricing_used=bool(executable),
            impossible_scenarios=state_space.impossible_states,
            breaking_scenarios=breaking,
            audit_trail=[
                {"step": "enumerate", "valid_states": len(state_space.valid_states), "impossible_states": len(state_space.impossible_states)},
                {"step": "price", "displayed_edge": payoff.worst_case_payoff, "executable_pricing_used": bool(executable)},
            ],
        )
        displayed_edge = payoff.worst_case_payoff
        executable_edge = payoff.worst_case_payoff
        return PayoffBuildResult(
            payoff_matrix=payoff,
            proof=proof,
            displayed_edge=displayed_edge,
            executable_edge=executable_edge,
            executable_pricing_used=bool(executable),
        )

    @staticmethod
    def _friction(total_cost: float, policy: SolverPolicy) -> float:
        return total_cost * policy.min_profit_after_friction

    def _equivalent(
        self,
        markets: list[RawMarket],
        price_map: dict[str, float],
        executable_prices: dict[str, float],
        policy: SolverPolicy,
    ) -> PayoffMatrix | None:
        ordered = sorted(markets, key=lambda market: price_map[market.id])
        buyer = ordered[0]
        seller = ordered[-1]
        buy_price = executable_prices.get(buyer.id, price_map[buyer.id])
        sell_price = executable_prices.get(seller.id, price_map[seller.id])
        if abs(sell_price - buy_price) < 0.01:
            return None
        total_cost = buy_price + (1.0 - sell_price)
        net = (sell_price - buy_price) - self._friction(total_cost, policy)
        scenarios = [
            Scenario(name="Event resolves YES", description="YES leg wins", payoff=net, is_breaking=net <= 0),
            Scenario(name="Event resolves NO", description="NO leg wins", payoff=net, is_breaking=net <= 0),
        ]
        return PayoffMatrix(
            legs=[
                Leg(market_id=buyer.id, side="YES", price=buy_price, quantity=1.0, cost=buy_price, platform=buyer.platform),
                Leg(market_id=seller.id, side="NO", price=1.0 - sell_price, quantity=1.0, cost=1.0 - sell_price, platform=seller.platform),
            ],
            total_cost=total_cost,
            scenarios=scenarios,
            worst_case_payoff=net,
            best_case_payoff=net,
            breaking_scenario=scenarios[0] if net <= 0 else None,
            opportunity_type=OpportunityType.DUPLICATE_DIVERGENCE,
            friction_bps=int(policy.min_profit_after_friction * 10_000),
        )

    def _exclusivity(
        self,
        markets: list[RawMarket],
        price_map: dict[str, float],
        executable_prices: dict[str, float],
        policy: SolverPolicy,
    ) -> PayoffMatrix:
        no_prices = {market.id: 1.0 - executable_prices.get(market.id, price_map[market.id]) for market in markets}
        total_cost = sum(no_prices.values())
        gross = sum(executable_prices.get(market.id, price_map[market.id]) for market in markets) - 1.0
        net = gross - self._friction(total_cost, policy)
        legs = [
            Leg(market_id=market.id, side="NO", price=no_prices[market.id], quantity=1.0, cost=no_prices[market.id], platform=market.platform)
            for market in markets
        ]
        scenarios = [
            Scenario(
                name=f"{market.id} resolves YES",
                description="only one partition member resolves YES",
                payoff=net,
                is_breaking=net <= 0,
            )
            for market in markets
        ]
        return PayoffMatrix(
            legs=legs,
            total_cost=total_cost,
            scenarios=scenarios,
            worst_case_payoff=net,
            best_case_payoff=net,
            breaking_scenario=scenarios[0] if net <= 0 else None,
            opportunity_type=OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING,
            friction_bps=int(policy.min_profit_after_friction * 10_000),
        )

    def _implication(
        self,
        markets: list[RawMarket],
        relation_type: RelationType,
        price_map: dict[str, float],
        executable_prices: dict[str, float],
        policy: SolverPolicy,
    ) -> PayoffMatrix:
        a, b = markets[0], markets[1]
        a_yes = executable_prices.get(a.id, price_map[a.id])
        b_yes = executable_prices.get(b.id, price_map[b.id])
        total_cost = min(a_yes, b_yes) + (1.0 - max(a_yes, b_yes))
        net = abs(a_yes - b_yes) - self._friction(total_cost, policy)
        if relation_type == RelationType.INVERSE:
            scenarios = [
                Scenario(name="A YES / B NO", description="inverse pair resolves oppositely", payoff=net, is_breaking=net <= 0),
                Scenario(name="A NO / B YES", description="inverse pair resolves oppositely", payoff=net, is_breaking=net <= 0),
            ]
        else:
            scenarios = [
                Scenario(name="Implication holds", description="broader event covers narrower event", payoff=net, is_breaking=False),
                Scenario(name="Implication breaks", description="narrow event resolves while broad event fails", payoff=-total_cost, is_breaking=True),
            ]
        return PayoffMatrix(
            legs=[
                Leg(market_id=a.id, side="YES", price=a_yes, quantity=1.0, cost=a_yes, platform=a.platform),
                Leg(market_id=b.id, side="NO", price=1.0 - b_yes, quantity=1.0, cost=1.0 - b_yes, platform=b.platform),
            ],
            total_cost=total_cost,
            scenarios=scenarios,
            worst_case_payoff=min(s.payoff for s in scenarios),
            best_case_payoff=max(s.payoff for s in scenarios),
            breaking_scenario=next((scenario for scenario in scenarios if scenario.is_breaking), None),
            opportunity_type=OpportunityType.ASYMMETRIC_STRUCTURAL_BET,
            friction_bps=int(policy.min_profit_after_friction * 10_000),
        )
