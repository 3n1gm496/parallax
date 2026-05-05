from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from parallax.db.models import RawMarket
from parallax.execution.schemas import OrderbookSnapshot
from sqlalchemy.orm import Session
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    OutcomeStateSpace,
    PayoffMatrix,
    ProofObject,
    RelationEvidenceResponse,
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


@dataclass(slots=True)
class SolverDiagnostics:
    solver_called: bool = False
    solver_skip_reason: str | None = None
    solver_none_reason: str | None = None
    valid_state_count: int = 0
    impossible_state_count: int = 0
    displayed_edge: float | None = None
    executable_edge: float | None = None
    proof_status: str | None = None
    false_arbitrage_label: str | None = None
    executable_pricing_used: bool = False
    relation_types: list[str] = field(default_factory=list)
    relation_set_keys: list[str] = field(default_factory=list)
    identity_status: IdentityResolutionStatus = IdentityResolutionStatus.UNRESOLVED
    identity_version: str = "identity-v2"


@dataclass(slots=True)
class SolverDecision:
    result: SolverResult | None
    diagnostics: SolverDiagnostics


class GeneralizedPayoffSolver:
    def __init__(self, *, friction_bps: int | None = None, session: Session | None = None) -> None:
        self._policy = build_solver_policy(friction_bps=friction_bps, session=session)
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
        orderbooks: dict[str, OrderbookSnapshot] | None = None,
    ) -> SolverResult | None:
        return self.solve_with_trace(
            markets=markets,
            relation_evidence=relation_evidence,
            relation_sets=relation_sets,
            relations=relations,
            orderbooks=orderbooks,
        ).result

    def solve_with_trace(
        self,
        *,
        markets: list[RawMarket],
        relation_evidence: RelationEvidenceResponse | None,
        relation_sets: list[LogicalRelationSetSchema] | None = None,
        relations: list[LogicalRelationSchema] | None = None,
        orderbooks: dict[str, OrderbookSnapshot] | None = None,
    ) -> SolverDecision:
        encoded = self._encoder.encode(
            markets=markets,
            relation_evidence=relation_evidence,
            relation_sets=relation_sets,
            relations=relations,
            execution_context={"orderbooks": orderbooks or {}},
        )
        diagnostics = SolverDiagnostics(
            solver_called=True,
            relation_types=list(encoded.relation_types),
            relation_set_keys=list(encoded.relation_set_keys),
            identity_status=encoded.identity_status,
            identity_version=encoded.identity_version,
        )
        if not encoded.constraints:
            diagnostics.solver_none_reason = "no_constraints_encoded"
            return SolverDecision(result=None, diagnostics=diagnostics)
        if (
            self._policy.require_verified_identity_for_tradeable
            and (
                encoded.identity_status != IdentityResolutionStatus.VERIFIED
                or not encoded.identity_version.startswith("identity-v3")
            )
        ):
            diagnostics.solver_none_reason = "identity_policy_rejected"
            return SolverDecision(result=None, diagnostics=diagnostics)

        market_ids = [market.id for market in markets]
        state_space = self._state_space.enumerate(market_ids=market_ids, constraints=encoded.constraints)
        diagnostics.valid_state_count = len(state_space.valid_states)
        diagnostics.impossible_state_count = len(state_space.impossible_states)
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
            orderbooks=orderbooks,
        )
        if payoff_result is None:
            diagnostics.solver_none_reason = "payoff_builder_returned_none"
            return SolverDecision(result=None, diagnostics=diagnostics)

        false_label = self._classifier.classify(
            identity_status=encoded.identity_status,
            proof=payoff_result.proof,
            displayed_edge=payoff_result.displayed_edge,
            executable_edge=payoff_result.executable_edge,
            executable_pricing_used=payoff_result.executable_pricing_used,
        )
        diagnostics.displayed_edge = payoff_result.displayed_edge
        diagnostics.executable_edge = payoff_result.executable_edge
        diagnostics.proof_status = payoff_result.proof.proof_status
        diagnostics.false_arbitrage_label = false_label
        diagnostics.executable_pricing_used = payoff_result.executable_pricing_used
        payoff_result.proof.false_arbitrage_label = false_label
        if false_label is not None:
            payoff_result.proof.proof_status = "false_arbitrage"
            diagnostics.proof_status = "false_arbitrage"
        basket = self._optimizer.optimize(payoff_result.payoff_matrix, state_space, self._policy)
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
        result = SolverResult(
            payoff_matrix=payoff_result.payoff_matrix,
            scenario_matrix=state_space,
            proof_object=payoff_result.proof,
            solver_version=self.solver_version,
            constraint_fingerprint=fingerprint,
            basket=basket,
            false_arbitrage_label=false_label,
            audit_record=audit,
        )
        return SolverDecision(result=result, diagnostics=diagnostics)

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
