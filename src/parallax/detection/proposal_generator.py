from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from parallax.db.models import RawMarket
from parallax.shared.schemas import CompiledPropositionSchema, RelationType


@dataclass(frozen=True)
class RelationProposal:
    from_market_id: str
    to_market_id: str
    proposed_relation_type: RelationType
    confidence: float
    frame_id: str | None
    evidence: dict


class RelationProposalGenerator:
    def generate(
        self,
        *,
        markets: list[RawMarket],
        propositions: dict[str, CompiledPropositionSchema],
        frame_ids: dict[str, str],
    ) -> list[RelationProposal]:
        proposals: list[RelationProposal] = []
        grouped: dict[str, list[RawMarket]] = {}
        for market in markets:
            frame_id = frame_ids.get(market.id)
            if frame_id is None:
                continue
            grouped.setdefault(frame_id, []).append(market)

        for frame_id, members in grouped.items():
            for market_a, market_b in combinations(members, 2):
                prop_a = propositions.get(market_a.id)
                prop_b = propositions.get(market_b.id)
                if prop_a is None or prop_b is None:
                    continue
                relation_type, confidence, evidence = self._propose_relation(prop_a, prop_b)
                proposals.append(
                    RelationProposal(
                        from_market_id=market_a.id,
                        to_market_id=market_b.id,
                        proposed_relation_type=relation_type,
                        confidence=confidence,
                        frame_id=frame_id,
                        evidence=evidence,
                    )
                )
        return proposals

    def _propose_relation(
        self,
        proposition_a: CompiledPropositionSchema,
        proposition_b: CompiledPropositionSchema,
    ) -> tuple[RelationType, float, dict]:
        same_family = proposition_a.proposition_family == proposition_b.proposition_family
        same_predicate = proposition_a.canonical_predicate == proposition_b.canonical_predicate
        same_temporal = proposition_a.temporal_deadline == proposition_b.temporal_deadline
        same_oracle = proposition_a.oracle_focus == proposition_b.oracle_focus
        same_subject = proposition_a.canonical_subject == proposition_b.canonical_subject
        same_object = proposition_a.canonical_object == proposition_b.canonical_object
        distinct_outcome = proposition_a.canonical_object != proposition_b.canonical_object

        if same_family and same_predicate and same_temporal and same_oracle and same_subject and same_object:
            return RelationType.EQUIVALENT, 0.8, {"rule": "matching_proposition_signature"}

        if (
            same_family
            and same_predicate
            and same_temporal
            and same_oracle
            and distinct_outcome
            and proposition_a.partition_hint
            and proposition_b.partition_hint
        ):
            return RelationType.MUTUALLY_EXCLUSIVE, 0.65, {"rule": "partition_hint_signature"}

        if same_family and same_temporal:
            return RelationType.SAME_EVENT_FAMILY, 0.95, {"rule": "same_frame_signature"}

        return RelationType.RELATED_BUT_NOT_TRADEABLE, 0.4, {"rule": "weak_frame_overlap"}
