from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from parallax.db.models import RawMarket
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    OutcomeStateSpace,
    PayoffMatrix,
    ProofObject,
    RelationEvidenceResponse,
    RelationType,
    SolverAuditRecord,
)
from parallax.solver.classifier import FalseArbitrageClassifier
from parallax.solver.encoder import RelationConstraintEncoder
from parallax.solver.optimizer import BasketOptimizer
from parallax.solver.payoff import PayoffMatrixGenerator
from parallax.solver.policy import SOLVER_VERSION, build_solver_policy
from parallax.solver.state_space import OutcomeStateSpaceBuilder


@dataclass(slots=True)
class SolverResult:
    payoff_matrix: PayoffMatrix
    scenario_matrix: OutcomeStateSpace
    proof_object: ProofObject
    solver_version: str
    constraint_fingerprint: str
    basket: dict[str, object]
    false_arbitrage_label: str | None
    audit_record: SolverAuditRecord


class GeneralizedPayoffSolver:
    def __init__(self, *, friction_bps: int | None = None) -> None:
        self._policy = build_solver_policy(friction_bps=friction_bps)
        self._encoder = RelationConstraintEncoder()
        self._state_space = OutcomeStateSpaceBuilder()
        self._payoff = PayoffMatrixGenerator()
        self._optimizer = BasketOptimizer()
        self._classifier = FalseArbitrageClassifier()

    @property
    def solver_version(self) -> str:
        return SOLVER_VERSION

    def solve(
        self,
        *,
        markets: list[RawMarket],
        relation_evidence: RelationEvidenceResponse | None,
        relation_sets: list[LogicalRelationSetSchema] | None = None,
        relations: list[LogicalRelationSchema] | None = None,
        executable_prices: dict[str, float] | None = None,
    ) -> SolverResult | None:
        encoded = self._encoder.encode(
            markets=markets,
            relation_evidence=relation_evidence,
            relation_sets=relation_sets,
            relations=relations,
            execution_context={"executable_prices": executable_prices or {}},
        )
        if not encoded.constraints:
            return None
        if (
            self._policy.require_verified_identity_for_tradeable
            and encoded.identity_status != IdentityResolutionStatus.VERIFIED
        ):
            return None

        market_ids = [market.id for market in markets]
        state_space = self._state_space.enumerate(market_ids=market_ids, constraints=encoded.constraints)
        primary_relation = encoded.constraints[0].relation_type
        fingerprint = self._fingerprint(markets, encoded.constraints, encoded.identity_version)
        payoff_result = self._payoff.build(
            markets=markets,
            relation_type=primary_relation,
            state_space=state_space,
            policy=self._policy,
            solver_version=self.solver_version,
            constraint_fingerprint=fingerprint,
            identity_version=encoded.identity_version,
            relation_set_keys=encoded.relation_set_keys,
            assumptions=self._assumptions(encoded.identity_status, relation_evidence),
            executable_prices=executable_prices,
        )
        if payoff_result is None:
            return None

        false_label = self._classifier.classify(
            identity_status=encoded.identity_status,
            proof=payoff_result.proof,
            displayed_edge=payoff_result.displayed_edge,
            executable_edge=payoff_result.executable_edge,
            executable_pricing_used=payoff_result.executable_pricing_used,
        )
        payoff_result.proof.false_arbitrage_label = false_label
        if false_label is not None:
            payoff_result.proof.proof_status = "false_arbitrage"
        basket = self._optimizer.optimize(payoff_result.payoff_matrix, self._policy)
        audit = SolverAuditRecord(
            constraint_fingerprint=fingerprint,
            solver_version=self.solver_version,
            policy_key=self._policy.policy_key,
            status="false_arbitrage" if false_label else "solved",
            trace={
                "market_ids": market_ids,
                "relation_types": encoded.relation_types,
                "relation_set_keys": encoded.relation_set_keys,
                "valid_states": len(state_space.valid_states),
                "impossible_states": len(state_space.impossible_states),
                "false_arbitrage_label": false_label,
            },
        )
        return SolverResult(
            payoff_matrix=payoff_result.payoff_matrix,
            scenario_matrix=state_space,
            proof_object=payoff_result.proof,
            solver_version=self.solver_version,
            constraint_fingerprint=fingerprint,
            basket=basket,
            false_arbitrage_label=false_label,
            audit_record=audit,
        )

    @staticmethod
    def _assumptions(
        identity_status: IdentityResolutionStatus,
        relation_evidence: RelationEvidenceResponse | None,
    ) -> list[str]:
        assumptions = [f"identity_status={identity_status.value}"]
        if relation_evidence is not None:
            assumptions.append(f"proof_status={relation_evidence.proof_status}")
            assumptions.append(f"tradeable_relation={relation_evidence.tradeable_relation}")
        return assumptions

    @staticmethod
    def _fingerprint(
        markets: list[RawMarket],
        constraints: list,
        identity_version: str,
    ) -> str:
        payload = {
            "markets": sorted(market.id for market in markets),
            "constraints": [
                {
                    "key": constraint.constraint_key,
                    "relation_type": constraint.relation_type.value,
                    "market_ids": sorted(constraint.market_ids),
                    "proof_status": constraint.proof_status,
                    "tradeable_relation": constraint.tradeable_relation,
                }
                for constraint in constraints
            ],
            "identity_version": identity_version,
            "solver_version": SOLVER_VERSION,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
