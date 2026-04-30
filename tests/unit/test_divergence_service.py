from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from parallax.db.models import RawMarket, OpportunityCandidate
from parallax.divergence.service import DivergenceService
from parallax.shared.schemas import RelationType
import uuid


def _market(mid: str, platform: str, yes_price: float, group_id: str | None = None) -> RawMarket:
    return RawMarket(
        id=mid,
        platform=platform,
        market_id=mid.split(":")[-1],
        title=f"Title {mid}",
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        group_id=group_id,
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )


def _rel(a_id: str, b_id: str, rtype: RelationType) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "from_market_id": a_id,
        "to_market_id": b_id,
        "relation_type": rtype.value,
        "confidence": 0.9,
        "evidence": {},
        "created_by": "test",
    }


class TestDivergenceService:
    def _make_service(self, relations: list[dict]):
        session = MagicMock()
        session.add = MagicMock()
        session.flush = MagicMock()
        graph_repo = MagicMock()
        graph_repo.get_relations.return_value = relations
        svc = DivergenceService(session, graph_repo, friction_bps=10)
        return svc, session

    def test_no_markets_finds_nothing(self):
        svc, _ = self._make_service([])
        assert svc.scan([]) == 0

    def test_mutually_exclusive_mispriced_creates_candidate(self):
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, session = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 1
        session.add.assert_called_once()

    def test_mutually_exclusive_fairly_priced_no_candidate(self):
        a = _market("pm:a", "pm", 0.50)
        b = _market("pm:b", "pm", 0.50)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, session = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 0
        session.add.assert_not_called()

    def test_equivalent_divergence_creates_candidate(self):
        a = _market("pm:a", "pm", 0.40)
        b = _market("kalshi:b", "kalshi", 0.55)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        svc, session = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 1

    def test_equivalent_no_spread_no_candidate(self):
        a = _market("pm:a", "pm", 0.50)
        b = _market("kalshi:b", "kalshi", 0.505)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        svc, session = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 0

    def test_duplicate_relations_not_double_counted(self):
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        # Both a and b return the same relation → should be deduped
        svc, session = self._make_service([rel])
        svc._graph_repo.get_relations.side_effect = lambda mid: [rel]
        count = svc.scan([a, b])
        assert count == 1
