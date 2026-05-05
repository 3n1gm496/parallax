from datetime import datetime, timezone
from unittest.mock import MagicMock
import parallax.divergence.service as divergence_service
from parallax.db.models import RawMarket
from parallax.divergence.service import DivergenceService
from parallax.shared.schemas import IdentityResolutionStatus, RelationEvidenceResponse, RelationType
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
        "evidence": {"proof_status": "verified", "tradeable_relation": True},
        "created_by": "test",
        "proof_status": "verified",
        "tradeable_relation": True,
    }


def _relation_evidence(rel: dict, *, identity_status: IdentityResolutionStatus = IdentityResolutionStatus.VERIFIED):
    evidence = rel.get("evidence", {})
    return RelationEvidenceResponse(
        from_market_id=rel["from_market_id"],
        to_market_id=rel["to_market_id"],
        relation_type=RelationType(rel["relation_type"]),
        confidence=rel["confidence"],
        created_by=rel["created_by"],
        proof_status="verified",
        tradeable_relation=True,
        identity_status=identity_status,
        identity_version="identity-v3-runtime",
        semantic_confidence=evidence.get("semantic_confidence"),
        relation_signals=evidence.get("relation_signals", {}),
    )


class TestDivergenceService:
    def _make_service(self, relations: list[dict], friction_bps: int = 10):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.get_relations.return_value = relations
        svc = DivergenceService(session, graph_repo, friction_bps=friction_bps)
        svc._candidate_repo = MagicMock()
        svc._candidate_repo.candidate_exists.return_value = False
        svc._candidate_repo.create.return_value = MagicMock()
        divergence_service.load_relation_evidence = MagicMock(
            side_effect=lambda _session, market_ids: next(
                (
                    _relation_evidence(rel)
                    for rel in relations
                    if {rel["from_market_id"], rel["to_market_id"]} == set(market_ids)
                ),
                None,
            )
        )
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
        assert "risk_scores" in svc._candidate_repo.create.call_args.kwargs

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
        # Synthetic OB: spread=0.5%, bids at mid-0.0025
        # NO-legs use bid side: cost_A = 1-(0.60-0.0025)=0.4025, cost_B = 1-(0.55-0.0025)=0.4525
        # total_cost = 0.4025 + 0.4525 = 0.855
        # gross = (0.5975 + 0.5475) - 1.0 = 0.145  (each NO leg pays 1 if the other resolves YES)
        # friction = 0.855 * 10/10000 = 0.000855; net ≈ 0.144145
        _spread = 0.005
        bid_a = 0.60 - _spread / 2   # 0.5975
        bid_b = 0.55 - _spread / 2   # 0.5475
        cost_a = round(1.0 - bid_a, 6)  # 0.4025
        cost_b = round(1.0 - bid_b, 6)  # 0.4525
        expected_total = round(cost_a + cost_b, 6)
        friction = round(expected_total * 10 / 10_000, 6)
        expected_net = round(bid_a + bid_b - 1.0 - friction, 6)
        assert abs(matrix.total_cost - expected_total) < 1e-4
        assert abs(matrix.worst_case_payoff - expected_net) < 1e-4

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
        # Synthetic OB spread=0.5%: buyer YES uses ask (mid+0.0025), seller NO uses bids
        # ask_a=0.4025, bid_b=0.5475 → NO-cost_b = 1-0.5475 = 0.4525
        # total_cost = 0.4025 + 0.4525 = 0.855
        # gross = 0.5475 - 0.4025 = 0.145; friction = 0.855*10/10000 = 0.000855; net≈0.144145
        _spread = 0.005
        ask_a = 0.40 + _spread / 2    # 0.4025
        bid_b = 0.55 - _spread / 2    # 0.5475
        cost_b_no = round(1.0 - bid_b, 6)  # 0.4525
        expected_total = round(ask_a + cost_b_no, 6)
        friction = round(expected_total * 10 / 10_000, 6)
        expected_net = round(bid_b - ask_a - friction, 6)
        assert abs(matrix.total_cost - expected_total) < 1e-4
        assert abs(matrix.worst_case_payoff - expected_net) < 1e-4
        # Both scenarios have the same payoff
        assert len(matrix.scenarios) == 2
        payoffs = [s.payoff for s in matrix.scenarios]
        assert abs(payoffs[0] - payoffs[1]) < 1e-4
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

    def test_equivalent_candidate_gets_nonempty_risk_score(self):
        a = _market("pm:a", "pm", 0.40)
        b = _market("kalshi:b", "kalshi", 0.55)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        rel["evidence"] = {"semantic_confidence": 0.8}
        svc, _ = self._make_service([rel])

        svc.scan([a, b])

        risk_scores = svc._candidate_repo.create.call_args.kwargs["risk_scores"]
        assert set(risk_scores) == {
            "oracle_risk",
            "deadline_risk",
            "semantic_risk",
            "execution_risk",
            "liquidity_risk",
            "cancellation_risk",
            "source_trust_risk",
            "composite",
            "policy_version",
        }
        assert risk_scores["policy_version"] == "risk-v2"

    def test_relation_signals_raise_risk_score_components(self):
        a = _market("pm:a", "pm", 0.40)
        b = _market("kalshi:b", "kalshi", 0.55)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        rel["evidence"] = {
            "semantic_confidence": 0.8,
            "relation_signals": {
                "oracle_mismatch": True,
                "deadline_mismatch": True,
                "ambiguity_level": "high",
            },
        }
        svc, _ = self._make_service([rel])

        svc.scan([a, b])

        risk_scores = svc._candidate_repo.create.call_args.kwargs["risk_scores"]
        assert risk_scores["oracle_risk"] >= 0.5
        assert risk_scores["deadline_risk"] >= 0.15
        assert risk_scores["semantic_risk"] >= 0.3
        assert risk_scores["source_trust_risk"] >= 0.3

    def test_ambiguous_identity_blocks_candidate_generation(self):
        a = _market("pm:a", "pm", 0.40)
        b = _market("kalshi:b", "kalshi", 0.55)
        rel = _rel("pm:a", "kalshi:b", RelationType.EQUIVALENT)
        svc, _ = self._make_service([rel])
        divergence_service.load_relation_evidence = MagicMock(
            return_value=_relation_evidence(rel, identity_status=IdentityResolutionStatus.AMBIGUOUS)
        )

        count = svc.scan([a, b])

        assert count == 0
        svc._candidate_repo.create.assert_not_called()
