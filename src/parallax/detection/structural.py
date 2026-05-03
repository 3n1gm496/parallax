from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from parallax.db.models import RawMarket
from parallax.shared.schemas import RelationType


@dataclass(frozen=True)
class RelationCandidate:
    from_market_id: str
    to_market_id: str
    relation_type: RelationType
    confidence: float
    evidence: dict


class StructuralRelationDetector:
    """Detect relation candidates using low-risk structural rules.

    Same-group markets are treated as belonging to the same event family only.
    They are not promoted to mutually exclusive without stronger proof.
    """

    _INTRA_GROUP_CONFIDENCE = 0.95
    _CROSS_PLATFORM_PRICE_SUM_THRESHOLD = 0.97
    _CROSS_PLATFORM_DEADLINE_DAYS = 7
    _CROSS_PLATFORM_CONFIDENCE = 0.5

    def detect(self, markets: list[RawMarket]) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        candidates.extend(self._intra_group_pairs(markets))
        candidates.extend(self._cross_platform_price_inversion(markets))
        return candidates

    def _intra_group_pairs(self, markets: list[RawMarket]) -> list[RelationCandidate]:
        groups: dict[tuple[str, str], list[RawMarket]] = {}
        for market in markets:
            if market.group_id:
                groups.setdefault((market.platform, market.group_id), []).append(market)

        candidates: list[RelationCandidate] = []
        for (platform, group_id), members in groups.items():
            if len(members) < 2:
                continue
            for market_a, market_b in combinations(members, 2):
                candidates.append(
                    RelationCandidate(
                        from_market_id=market_a.id,
                        to_market_id=market_b.id,
                        relation_type=RelationType.SAME_EVENT_FAMILY,
                        confidence=self._INTRA_GROUP_CONFIDENCE,
                        evidence={"rule": "intra_group_same_event_family", "platform": platform, "group_id": group_id},
                    )
                )
        return candidates

    def _cross_platform_price_inversion(self, markets: list[RawMarket]) -> list[RelationCandidate]:
        candidates: list[RelationCandidate] = []
        for market_a, market_b in combinations(markets, 2):
            if market_a.platform == market_b.platform:
                continue
            if not market_a.outcome_prices or not market_b.outcome_prices:
                continue
            price_a = market_a.outcome_prices[0]
            price_b = market_b.outcome_prices[0]
            if not isinstance(price_a, (int, float)) or not isinstance(price_b, (int, float)):
                continue
            if price_a + price_b >= self._CROSS_PLATFORM_PRICE_SUM_THRESHOLD:
                continue
            if market_a.deadline is None or market_b.deadline is None:
                continue
            delta = abs((market_a.deadline - market_b.deadline).total_seconds())
            if delta > self._CROSS_PLATFORM_DEADLINE_DAYS * 86400:
                continue
            candidates.append(
                RelationCandidate(
                    from_market_id=market_a.id,
                    to_market_id=market_b.id,
                    relation_type=RelationType.EQUIVALENT,
                    confidence=self._CROSS_PLATFORM_CONFIDENCE,
                    evidence={
                        "rule": "cross_platform_price_inversion",
                        "price_sum": round(price_a + price_b, 4),
                        "deadline_delta_hours": round(delta / 3600, 1),
                    },
                )
            )
        return candidates
