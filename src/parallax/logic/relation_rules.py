from __future__ import annotations

from dataclasses import dataclass

from parallax.shared.schemas import CompiledPropositionSchema, RelationType


@dataclass(frozen=True)
class RelationRuleResult:
    relation_type: RelationType
    confidence: float
    proof_status: str
    tradeable_relation: bool
    reasoning: str
    evidence: dict[str, object]
    requires_semantic_review: bool = False


class RelationRuleEngine:
    def classify_pair(
        self,
        *,
        proposed_relation: RelationType,
        proposition_a: CompiledPropositionSchema,
        proposition_b: CompiledPropositionSchema,
    ) -> RelationRuleResult:
        same_signature = self._same_signature(proposition_a, proposition_b)
        same_scope = self._same_scope(proposition_a, proposition_b)
        same_subject = proposition_a.canonical_subject == proposition_b.canonical_subject
        same_predicate = proposition_a.canonical_predicate == proposition_b.canonical_predicate
        same_object = proposition_a.canonical_object == proposition_b.canonical_object
        a_prefix = self._normalized_object(proposition_a)
        b_prefix = self._normalized_object(proposition_b)
        overlapping_exclusions = bool(
            set(proposition_a.resolution_exclusions).intersection(proposition_b.resolution_exclusions)
        )

        if proposed_relation == RelationType.EQUIVALENT:
            if same_signature:
                return RelationRuleResult(
                    relation_type=RelationType.EQUIVALENT,
                    confidence=0.9,
                    proof_status="verified",
                    tradeable_relation=True,
                    reasoning="strict proposition signature match",
                    evidence={"logic_rule": "strict_equivalence"},
                    requires_semantic_review=True,
                )
            return RelationRuleResult(
                relation_type=RelationType.RELATED_BUT_NOT_TRADEABLE,
                confidence=0.2,
                proof_status="rejected",
                tradeable_relation=False,
                reasoning="equivalence proposal fails strict proposition signature match",
                evidence={"logic_rule": "reject_equivalence"},
            )

        if proposed_relation == RelationType.MUTUALLY_EXCLUSIVE:
            exclusive_partition = (
                same_scope
                and same_subject
                and same_predicate
                and proposition_a.partition_hint
                and proposition_b.partition_hint
                and proposition_a.canonical_object != proposition_b.canonical_object
            )
            if exclusive_partition:
                return RelationRuleResult(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.74,
                    proof_status="needs_review",
                    tradeable_relation=False,
                    reasoning="same scoped proposition family with distinct partition members",
                    evidence={"logic_rule": "exclusive_partition_candidate"},
                    requires_semantic_review=True,
                )
            return RelationRuleResult(
                relation_type=RelationType.SAME_EVENT_INDEPENDENT,
                confidence=0.72,
                proof_status="verified",
                tradeable_relation=False,
                reasoning="same event family without exclusive partition proof",
                evidence={"logic_rule": "downgrade_nonexclusive_same_frame"},
            )

        if (
            same_scope
            and same_subject
            and same_predicate
            and proposition_a.partition_hint
            and proposition_b.partition_hint
            and not same_object
        ):
            if a_prefix and b_prefix and a_prefix != b_prefix:
                return RelationRuleResult(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.68,
                    proof_status="needs_review",
                    tradeable_relation=False,
                    reasoning="distinct object branches within same scoped proposition family",
                    evidence={"logic_rule": "branch_exclusivity_candidate"},
                    requires_semantic_review=True,
                )

        if same_scope and same_subject and same_predicate and same_object and overlapping_exclusions:
            return RelationRuleResult(
                relation_type=RelationType.RELATED_BUT_NOT_TRADEABLE,
                confidence=0.45,
                proof_status="needs_review",
                tradeable_relation=False,
                reasoning="shared object but incompatible exclusions prevent direct tradeability proof",
                evidence={"logic_rule": "exclusion_conflict"},
                requires_semantic_review=True,
            )

        return RelationRuleResult(
            relation_type=RelationType.SAME_EVENT_FAMILY,
            confidence=0.9 if same_scope else 0.5,
            proof_status="verified",
            tradeable_relation=False,
            reasoning="same event frame without stronger proof",
            evidence={"logic_rule": "same_event_family"},
        )

    def classify_partition_set(
        self,
        propositions: list[CompiledPropositionSchema],
    ) -> RelationRuleResult | None:
        if len(propositions) < 2:
            return None
        head = propositions[0]
        same_scope = all(self._same_scope(head, proposition) for proposition in propositions[1:])
        same_subject = all(head.canonical_subject == proposition.canonical_subject for proposition in propositions[1:])
        same_predicate = all(head.canonical_predicate == proposition.canonical_predicate for proposition in propositions[1:])
        partition_flags = all(proposition.partition_hint for proposition in propositions)
        object_values = [proposition.canonical_object for proposition in propositions if proposition.canonical_object]
        unique_objects = len(object_values) == len(set(object_values)) == len(propositions)

        if same_scope and same_subject and same_predicate and partition_flags and unique_objects:
            return RelationRuleResult(
                relation_type=RelationType.EXHAUSTIVE_PARTITION,
                confidence=0.78,
                proof_status="needs_review",
                tradeable_relation=False,
                reasoning="n-ary partition candidate with aligned scope and disjoint outcomes",
                evidence={
                    "logic_rule": "partition_set_candidate",
                    "member_count": len(propositions),
                    "objects": object_values,
                },
                requires_semantic_review=True,
            )
        return None

    @staticmethod
    def _same_signature(a: CompiledPropositionSchema, b: CompiledPropositionSchema) -> bool:
        return (
            a.canonical_subject == b.canonical_subject
            and a.canonical_predicate == b.canonical_predicate
            and a.canonical_object == b.canonical_object
            and RelationRuleEngine._same_scope(a, b)
        )

    @staticmethod
    def _same_scope(a: CompiledPropositionSchema, b: CompiledPropositionSchema) -> bool:
        return (
            a.proposition_family == b.proposition_family
            and a.time_scope == b.time_scope
            and a.oracle_scope == b.oracle_scope
        )

    @staticmethod
    def _normalized_object(proposition: CompiledPropositionSchema) -> str | None:
        value = (proposition.canonical_object or "").strip().lower()
        if not value:
            return None
        return value.split(":")[0].split("/")[0]
