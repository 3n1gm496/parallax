from datetime import datetime, timezone
from unittest.mock import MagicMock
from parallax.db.models import RawMarket
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


def _market_empty_prices(mid: str, platform: str) -> RawMarket:
    return RawMarket(
        id=mid,
        platform=platform,
        market_id=mid.split(":")[-1],
        title=f"Title {mid}",
        description="",
        resolution_criteria="",
        outcomes=[],
        outcome_prices=[],
        group_id=None,
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
    def _make_service(self, relations: list[dict], friction_bps: int = 10):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.get_relations.return_value = relations
        svc = DivergenceService(session, graph_repo, friction_bps=friction_bps)
        svc._candidate_repo = MagicMock()
        svc._candidate_repo.candidate_exists.return_value = False
        svc._candidate_repo.create.return_value = MagicMock()
        return svc, session

    def test_no_markets_finds_nothing(self):
        svc, _ = self._make_service([])
        assert svc.scan([]) == 0

    def test_mutually_exclusive_mispriced_creates_candidate(self):
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 1
        svc._candidate_repo.create.assert_called_once()

    def test_mutually_exclusive_fairly_priced_no_candidate(self):
        a = _market("pm:a", "pm", 0.50)
        b = _market("pm:b", "pm", 0.50)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 0
        svc._candidate_repo.create.assert_not_called()

    def test_mutually_exclusive_payoff_math_no_double_friction(self):
        """worst_case_payoff = gross - friction once; SimulatorService must not re-apply."""
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel], friction_bps=10)
        captured = {}
        svc._candidate_repo.create = MagicMock(side_effect=lambda **kw: captured.update(kw) or MagicMock())
        svc.scan([a, b])
        matrix = captured["payoff_matrix"]
        # total_cost = (1-0.60) + (1-0.55) = 0.85 (capital deployed: both NO legs)
        # gross = 0.60 + 0.55 - 1.0 = 0.15
        # friction = 0.85 * 10/10000 = 0.00085; net = 0.14915
        assert abs(matrix.total_cost - 0.85) < 1e-9
        assert abs(matrix.worst_case_payoff - 0.14915) < 1e-9
        # Both scenarios have identical payoff (direction-neutral)
        assert all(abs(s.payoff - matrix.worst_case_payoff) < 1e-9 for s in matrix.scenarios)

    def test_equivalent_divergence_creates_candidate(self):
        a = _market("pm:a", "pm", 0.40)
        b = _market("kalshi:b", "kalshi", 0.55)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        svc, session = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 1

    def test_equivalent_payoff_is_direction_neutral(self):
        """Both YES and NO scenarios return the same payoff for truly equivalent markets."""
        a = _market("pm:a", "pm", 0.40)
        b = _market("kalshi:b", "kalshi", 0.55)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        svc, session = self._make_service([rel], friction_bps=10)
        captured = {}
        svc._candidate_repo.create = MagicMock(side_effect=lambda **kw: captured.update(kw) or MagicMock())
        svc.scan([a, b])
        matrix = captured["payoff_matrix"]
        # total_cost = buy_price + (1 - sell_price) = 0.40 + 0.45 = 0.85
        assert abs(matrix.total_cost - 0.85) < 1e-9
        # gross = sell - buy = 0.55 - 0.40 = 0.15; friction = 0.85 * 10/10000 = 0.00085; net ≈ 0.14915
        expected_net = 0.15 - 0.85 * 10 / 10_000
        assert abs(matrix.worst_case_payoff - expected_net) < 1e-9
        # Both scenarios have the same payoff
        assert len(matrix.scenarios) == 2
        payoffs = [s.payoff for s in matrix.scenarios]
        assert abs(payoffs[0] - payoffs[1]) < 1e-9
        # No breaking scenario for riskless equivalent spread
        assert not any(s.is_breaking for s in matrix.scenarios)

    def test_equivalent_no_spread_no_candidate(self):
        a = _market("pm:a", "pm", 0.50)
        b = _market("kalshi:b", "kalshi", 0.505)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        svc, session = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 0

    def test_cross_run_deduplication(self):
        """No new candidate created if one already exists in DB for this pair."""
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel])
        svc._candidate_repo.candidate_exists.return_value = True
        count = svc.scan([a, b])
        assert count == 0
        svc._candidate_repo.create.assert_not_called()

    def test_duplicate_relations_not_double_counted(self):
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel])
        svc._graph_repo.get_relations.side_effect = lambda mid: [rel]
        count = svc.scan([a, b])
        assert count == 1

    def test_empty_outcome_prices_skipped(self):
        """Markets with no outcome_prices must not raise IndexError."""
        a = _market_empty_prices("pm:a", "pm")
        b = _market_empty_prices("pm:b", "pm")
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 0

    def test_none_outcome_price_skipped(self):
        """Markets with a None element in outcome_prices must not raise TypeError."""
        a = _market("pm:a", "pm", 0.60)
        b = _market("pm:b", "pm", 0.55)
        a.outcome_prices = [None, 0.40]
        rel = _rel("pm:a", "pm:b", RelationType.MUTUALLY_EXCLUSIVE)
        svc, _ = self._make_service([rel])
        count = svc.scan([a, b])
        assert count == 0
