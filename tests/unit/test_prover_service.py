from datetime import datetime, timezone
from unittest.mock import MagicMock, call
from parallax.db.models import RawMarket
from parallax.prover.service import ProverService
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


class TestProverService:
    def _make_service(self, relation_exists: bool = False):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = relation_exists
        svc = ProverService(session, graph_repo)
        return svc, graph_repo

    def test_no_markets_adds_nothing(self):
        svc, graph_repo = self._make_service()
        count = svc.run([])
        assert count == 0
        graph_repo.add_relation.assert_not_called()

    def test_two_markets_same_group_adds_one_relation(self):
        svc, graph_repo = self._make_service(relation_exists=False)
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1")]
        count = svc.run(markets)
        assert count == 1
        graph_repo.add_relation.assert_called_once()
        kwargs = graph_repo.add_relation.call_args.kwargs
        assert kwargs["relation_type"] == RelationType.MUTUALLY_EXCLUSIVE
        assert kwargs["created_by"] == "stage1_constraint"

    def test_existing_relation_skipped(self):
        svc, graph_repo = self._make_service(relation_exists=True)
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1")]
        count = svc.run(markets)
        assert count == 0
        graph_repo.add_relation.assert_not_called()

    def test_three_markets_adds_three_new_relations(self):
        svc, graph_repo = self._make_service(relation_exists=False)
        markets = [
            _market("pm", "a", "g1"),
            _market("pm", "b", "g1"),
            _market("pm", "c", "g1"),
        ]
        count = svc.run(markets)
        assert count == 3
        assert graph_repo.add_relation.call_count == 3
