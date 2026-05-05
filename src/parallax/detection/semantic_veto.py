from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from parallax.detection.schemas import RelationClassification
from parallax.detection.semantic import SemanticRelationAnalyzer
from parallax.shared.schemas import ContractSchema, RelationType


@dataclass(frozen=True)
class PartitionReviewResult:
    classification: RelationClassification
    pair_reviews: list[dict[str, object]]


class SemanticVeto:
    """Semantic adjudicator that can confirm, downgrade, or veto tradeability."""

    def __init__(self, analyzer: SemanticRelationAnalyzer) -> None:
        self._analyzer = analyzer

    async def review(
        self,
        contract_a: ContractSchema,
        contract_b: ContractSchema,
        *,
        proposed_relation: RelationType | None = None,
        hypothesis_context: str | None = None,
    ) -> RelationClassification | None:
        return await self._analyzer.classify(
            contract_a,
            contract_b,
            proposed_relation=proposed_relation,
            hypothesis_context=hypothesis_context,
        )

    async def review_partition(
        self,
        contracts: list[ContractSchema],
        *,
        member_market_ids: list[str],
        proposed_relation: RelationType = RelationType.EXHAUSTIVE_PARTITION,
    ) -> PartitionReviewResult | None:
        if len(contracts) < 2 or len(contracts) != len(member_market_ids):
            return None

        pair_reviews: list[dict[str, object]] = []
        pair_classifications: list[RelationClassification] = []
        for (idx_a, contract_a), (idx_b, contract_b) in combinations(enumerate(contracts), 2):
            classification = await self._analyzer.classify(
                contract_a,
                contract_b,
                proposed_relation=RelationType.MUTUALLY_EXCLUSIVE,
            )
            if classification is None:
                return None
            pair_classifications.append(classification)
            pair_reviews.append(
                {
                    "from_market_id": member_market_ids[idx_a],
                    "to_market_id": member_market_ids[idx_b],
                    "relation_type": classification.relation_type.value,
                    "confidence": classification.confidence,
                    "is_confirmed": classification.is_confirmed,
                    "tradeable_relation": classification.tradeable_relation,
                    "proof_status": classification.proof_status,
                    "comparison_axes": list(classification.comparison_axes),
                    "breaking_scenarios": [scenario.model_dump() for scenario in classification.breaking_scenarios],
                    "reasoning": classification.reasoning,
                }
            )

        comparison_axes = sorted(
            {
                axis
                for classification in pair_classifications
                for axis in classification.comparison_axes
            }
        )
        breaking_scenarios = [
            scenario
            for classification in pair_classifications
            for scenario in classification.breaking_scenarios
        ]
        all_confirmed = all(classification.is_confirmed for classification in pair_classifications)
        all_tradeable = all(classification.tradeable_relation for classification in pair_classifications)
        all_mutually_exclusive = all(
            classification.relation_type == RelationType.MUTUALLY_EXCLUSIVE
            for classification in pair_classifications
        )

        if all_mutually_exclusive and all_confirmed and not breaking_scenarios:
            proof_status = "verified"
            tradeable_relation = all_tradeable
            reasoning = "all pairwise semantic reviews confirm mutual exclusivity across the full partition set"
        elif breaking_scenarios or not all_mutually_exclusive:
            proof_status = "rejected"
            tradeable_relation = False
            reasoning = "at least one pairwise semantic review breaks exhaustive-partition semantics"
        else:
            proof_status = "needs_review"
            tradeable_relation = False
            reasoning = "pairwise semantic reviews are incomplete or insufficiently confirmed for set tradeability"

        classification = RelationClassification(
            relation_type=proposed_relation,
            confidence=min(classification.confidence for classification in pair_classifications),
            reasoning=reasoning,
            comparison_axes=comparison_axes,
            breaking_scenarios=breaking_scenarios,
            is_confirmed=proof_status == "verified",
            tradeable_relation=tradeable_relation,
            proof_status=proof_status,
        )
        return PartitionReviewResult(classification=classification, pair_reviews=pair_reviews)
