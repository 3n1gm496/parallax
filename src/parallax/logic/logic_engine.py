from __future__ import annotations

from dataclasses import dataclass

from parallax.detection.proposal_generator import RelationProposal
from parallax.logic.relation_rules import RelationRuleEngine
from parallax.shared.schemas import CompiledPropositionSchema, RelationType


@dataclass(frozen=True)
class LogicalRelationDecision:
    relation_type: RelationType
    proof_status: str
    tradeable_relation: bool
    confidence: float
    reasoning: str
    requires_semantic_review: bool
    evidence: dict


class LogicEngine:
    def __init__(self) -> None:
        self._rules = RelationRuleEngine()

    def adjudicate(
        self,
        proposal: RelationProposal,
        proposition_a: CompiledPropositionSchema,
        proposition_b: CompiledPropositionSchema,
    ) -> LogicalRelationDecision:
        result = self._rules.classify_pair(
            proposed_relation=proposal.proposed_relation_type,
            proposition_a=proposition_a,
            proposition_b=proposition_b,
        )
        return LogicalRelationDecision(
            relation_type=result.relation_type,
            proof_status=result.proof_status,
            tradeable_relation=result.tradeable_relation,
            confidence=max(proposal.confidence, result.confidence),
            reasoning=result.reasoning,
            requires_semantic_review=result.requires_semantic_review,
            evidence=dict(result.evidence),
        )

    def adjudicate_partition(self, propositions: list[CompiledPropositionSchema]) -> LogicalRelationDecision | None:
        result = self._rules.classify_partition_set(propositions)
        if result is None:
            return None
        return LogicalRelationDecision(
            relation_type=result.relation_type,
            proof_status=result.proof_status,
            tradeable_relation=result.tradeable_relation,
            confidence=result.confidence,
            reasoning=result.reasoning,
            requires_semantic_review=result.requires_semantic_review,
            evidence=dict(result.evidence),
        )
