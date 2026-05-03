from datetime import datetime, timezone

from parallax.db.models import RawMarket
from parallax.detection.structural import StructuralRelationDetector
from parallax.shared.schemas import RelationType


def _market(platform: str, market_id: str, group_id: str | None = None) -> RawMarket:
    return RawMarket(
        id=f"{platform}:{market_id}",
        platform=platform,
        market_id=market_id,
        title=f"Title {market_id}",
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        group_id=group_id,
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )


def _cross_market(mid: str, platform: str, yes_price: float, deadline: datetime | None = None) -> RawMarket:
    return RawMarket(
        id=mid,
        platform=platform,
        market_id=mid.split(":")[-1],
        title=f"Title {mid}",
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        group_id=None,
        deadline=deadline or datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )


class TestStructuralRelationDetector:
    def setup_method(self) -> None:
        self.detector = StructuralRelationDetector()

    def test_no_markets_returns_empty(self):
        assert self.detector.detect([]) == []

    def test_intra_group_relation_is_emitted(self):
        candidates = self.detector.detect([_market("pm", "a", "g1"), _market("pm", "b", "g1")])
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.relation_type == RelationType.SAME_EVENT_FAMILY
        assert candidate.evidence["rule"] == "intra_group_same_event_family"

    def test_cross_platform_price_inversion_emits_equivalent_candidate(self):
        deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
        candidates = self.detector.detect(
            [
                _cross_market("pm:a", "polymarket", 0.40, deadline),
                _cross_market("kalshi:b", "kalshi", 0.45, deadline),
            ]
        )
        equivalent = [candidate for candidate in candidates if candidate.relation_type == RelationType.EQUIVALENT]
        assert len(equivalent) == 1
        assert equivalent[0].evidence["rule"] == "cross_platform_price_inversion"
