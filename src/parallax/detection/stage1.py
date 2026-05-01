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
      platform are emitted as MUTUALLY_EXCLUSIVE pairs with high confidence.
    - Cross-platform price inversion: markets on different platforms with similar
      deadlines (within 7 days) and YES prices summing to < 0.97 are EQUIVALENT
      candidates for Stage 2 confirmation.
    """

    _INTRA_GROUP_CONFIDENCE = 0.95
    _CROSS_PLATFORM_PRICE_SUM_THRESHOLD = 0.97
    _CROSS_PLATFORM_DEADLINE_DAYS = 7
    _CROSS_PLATFORM_CONFIDENCE = 0.5

    def detect(self, markets: list[RawMarket]) -> list[RelationSpec]:
        specs: list[RelationSpec] = []
        specs.extend(self._intra_group_pairs(markets))
        specs.extend(self._cross_platform_price_inversion(markets))
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

    def _cross_platform_price_inversion(self, markets: list[RawMarket]) -> list[RelationSpec]:
        specs: list[RelationSpec] = []
        for a, b in combinations(markets, 2):
            if a.platform == b.platform:
                continue
            if not a.outcome_prices or not b.outcome_prices:
                continue
            p_a = a.outcome_prices[0]
            p_b = b.outcome_prices[0]
            if not isinstance(p_a, (int, float)) or not isinstance(p_b, (int, float)):
                continue
            if p_a + p_b >= self._CROSS_PLATFORM_PRICE_SUM_THRESHOLD:
                continue
            if a.deadline is None or b.deadline is None:
                continue
            delta = abs((a.deadline - b.deadline).total_seconds())
            if delta > self._CROSS_PLATFORM_DEADLINE_DAYS * 86400:
                continue
            specs.append(RelationSpec(
                from_market_id=a.id,
                to_market_id=b.id,
                relation_type=RelationType.EQUIVALENT,
                confidence=self._CROSS_PLATFORM_CONFIDENCE,
                evidence={
                    "rule": "cross_platform_price_inversion",
                    "price_sum": round(p_a + p_b, 4),
                    "deadline_delta_hours": round(delta / 3600, 1),
                },
            ))
        return specs
