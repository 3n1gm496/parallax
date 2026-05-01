from datetime import datetime, timezone
from parallax.db.models import RawMarket
from parallax.detection.stage1 import Stage1ConstraintDetector
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


class TestStage1ConstraintDetector:
    def setup_method(self):
        self.detector = Stage1ConstraintDetector()

    def test_no_markets_returns_empty(self):
        assert self.detector.detect([]) == []

    def test_single_market_no_group_returns_empty(self):
        assert self.detector.detect([_market("pm", "a")]) == []

    def test_single_market_with_group_returns_empty(self):
        assert self.detector.detect([_market("pm", "a", group_id="g1")]) == []

    def test_two_markets_same_group_same_platform(self):
        markets = [
            _market("pm", "a", group_id="g1"),
            _market("pm", "b", group_id="g1"),
        ]
        specs = self.detector.detect(markets)
        assert len(specs) == 1
        s = specs[0]
        assert s.relation_type == RelationType.MUTUALLY_EXCLUSIVE
        assert {s.from_market_id, s.to_market_id} == {"pm:a", "pm:b"}
        assert s.confidence == 0.95
        assert s.evidence["rule"] == "intra_group"
        assert s.evidence["group_id"] == "g1"

    def test_three_markets_same_group_produces_three_pairs(self):
        markets = [
            _market("pm", "a", group_id="g1"),
            _market("pm", "b", group_id="g1"),
            _market("pm", "c", group_id="g1"),
        ]
        specs = self.detector.detect(markets)
        assert len(specs) == 3

    def test_markets_different_groups_are_independent(self):
        markets = [
            _market("pm", "a", group_id="g1"),
            _market("pm", "b", group_id="g2"),
        ]
        specs = self.detector.detect(markets)
        assert len(specs) == 0

    def test_markets_same_group_different_platforms_are_independent(self):
        markets = [
            _market("pm", "a", group_id="g1"),
            _market("kalshi", "b", group_id="g1"),
        ]
        specs = self.detector.detect(markets)
        assert len(specs) == 0

    def test_markets_without_group_id_are_ignored(self):
        markets = [
            _market("pm", "a", group_id=None),
            _market("pm", "b", group_id=None),
        ]
        specs = self.detector.detect(markets)
        assert len(specs) == 0
