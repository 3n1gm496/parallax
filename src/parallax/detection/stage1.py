from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations
from parallax.db.models import RawMarket
from parallax.shared.schemas import RelationType


@dataclass(frozen=True)
class RelationSpec:
    from_market_id: str
    to_market_id: str
    relation_type: RelationType
    confidence: float
    evidence: dict


class Stage1ConstraintDetector:
    """Detect market relations using structural rules, without an LLM.

    Rules applied (in order):
    - Intra-group mutual exclusion: all markets sharing a group_id on the same
      platform are emitted as MUTUALLY_EXCLUSIVE pairs with high confidence,
      because Polymarket / similar platforms guarantee that exactly one outcome
      in a group resolves YES.
    """

    _INTRA_GROUP_CONFIDENCE = 0.95

    def detect(self, markets: list[RawMarket]) -> list[RelationSpec]:
        specs: list[RelationSpec] = []
        specs.extend(self._intra_group_pairs(markets))
        return specs

    def _intra_group_pairs(self, markets: list[RawMarket]) -> list[RelationSpec]:
        groups: dict[tuple[str, str], list[RawMarket]] = {}
        for m in markets:
            if m.group_id:
                key = (m.platform, m.group_id)
                groups.setdefault(key, []).append(m)

        specs: list[RelationSpec] = []
        for (platform, group_id), members in groups.items():
            if len(members) < 2:
                continue
            for a, b in combinations(members, 2):
                specs.append(
                    RelationSpec(
                        from_market_id=a.id,
                        to_market_id=b.id,
                        relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                        confidence=self._INTRA_GROUP_CONFIDENCE,
                        evidence={
                            "rule": "intra_group",
                            "platform": platform,
                            "group_id": group_id,
                        },
                    )
                )
        return specs
