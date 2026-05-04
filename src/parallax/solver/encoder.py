from __future__ import annotations

from dataclasses import dataclass

from parallax.db.models import RawMarket
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    RelationEvidenceResponse,
    ScenarioConstraintModel,
)


@dataclass(slots=True)
class EncodedSolverInput:
    markets: list[RawMarket]
    constraints: list[ScenarioConstraintModel]
    identity_status: IdentityResolutionStatus
    identity_version: str
    relation_types: list[str]
    relation_set_keys: list[str]
    execution_context: dict[str, object]


class RelationConstraintEncoder:
    def encode(
        self,
        *,
        markets: list[RawMarket],
        relation_evidence: RelationEvidenceResponse | None,
        relation_sets: list[LogicalRelationSetSchema] | None = None,
        relations: list[LogicalRelationSchema] | None = None,
        execution_context: dict[str, object] | None = None,
    ) -> EncodedSolverInput:
        constraints: list[ScenarioConstraintModel] = []
        relation_set_keys: list[str] = []
        relation_types: list[str] = []
        execution = execution_context or {}

        for relation_set in relation_sets or []:
            constraints.append(
                ScenarioConstraintModel(
                    constraint_key=relation_set.set_key,
                    relation_type=relation_set.relation_type,
                    market_ids=list(relation_set.member_market_ids),
                    proof_status=relation_set.proof_status,
                    tradeable_relation=relation_set.tradeable_relation,
                    identity_status=(
                        relation_evidence.identity_status if relation_evidence else IdentityResolutionStatus.UNRESOLVED
                    ),
                    identity_version=relation_evidence.identity_version if relation_evidence else "identity-v2",
                    set_key=relation_set.set_key,
                    frame_id=relation_set.frame_id,
                    provenance={
                        "created_by": relation_set.created_by,
                        "confidence": relation_set.confidence,
                        "evidence": relation_set.evidence,
                    },
                    execution_context=execution,
                )
            )
            relation_set_keys.append(relation_set.set_key)
            relation_types.append(relation_set.relation_type.value)

        for relation in relations or []:
            key = "|".join(sorted([relation.from_market_id, relation.to_market_id, relation.relation_type.value]))
            constraints.append(
                ScenarioConstraintModel(
                    constraint_key=key,
                    relation_type=relation.relation_type,
                    market_ids=[relation.from_market_id, relation.to_market_id],
                    proof_status=relation.proof_status,
                    tradeable_relation=relation.tradeable_relation,
                    identity_status=(
                        relation_evidence.identity_status if relation_evidence else IdentityResolutionStatus.UNRESOLVED
                    ),
                    identity_version=relation_evidence.identity_version if relation_evidence else "identity-v2",
                    set_key=None,
                    frame_id=relation.frame_id,
                    provenance={
                        "created_by": relation.created_by,
                        "confidence": relation.confidence,
                        "evidence": relation.evidence,
                    },
                    execution_context=execution,
                )
            )
            relation_types.append(relation.relation_type.value)

        if relation_evidence is not None and not constraints:
            key = relation_evidence.set_key or "|".join(
                sorted([relation_evidence.from_market_id, relation_evidence.to_market_id, relation_evidence.relation_type.value])
            )
            constraints.append(
                ScenarioConstraintModel(
                    constraint_key=key,
                    relation_type=relation_evidence.relation_type,
                    market_ids=list(
                        relation_evidence.member_market_ids
                        or [relation_evidence.from_market_id, relation_evidence.to_market_id]
                    ),
                    proof_status=relation_evidence.proof_status,  # type: ignore[arg-type]
                    tradeable_relation=relation_evidence.tradeable_relation,
                    identity_status=relation_evidence.identity_status,
                    identity_version=relation_evidence.identity_version,
                    set_key=relation_evidence.set_key,
                    frame_id=relation_evidence.frame_id,
                    provenance={
                        "confidence": relation_evidence.confidence,
                        "created_by": relation_evidence.created_by,
                        "identity_provenance": relation_evidence.identity_provenance,
                        "relation_signals": relation_evidence.relation_signals,
                    },
                    execution_context=execution,
                )
            )
            relation_types.append(relation_evidence.relation_type.value)
            if relation_evidence.set_key:
                relation_set_keys.append(relation_evidence.set_key)

        return EncodedSolverInput(
            markets=markets,
            constraints=constraints,
            identity_status=relation_evidence.identity_status if relation_evidence else IdentityResolutionStatus.UNRESOLVED,
            identity_version=relation_evidence.identity_version if relation_evidence else "identity-v2",
            relation_types=sorted(set(relation_types)),
            relation_set_keys=sorted(set(relation_set_keys)),
            execution_context=execution,
        )
