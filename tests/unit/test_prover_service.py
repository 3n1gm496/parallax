from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

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
        svc = ProverService(session, graph_repo, stage2_classifier=None)
        return svc, graph_repo

    @pytest.mark.anyio
    async def test_no_markets_adds_nothing(self):
        svc, graph_repo = self._make_service()
        count = await svc.run([])
        assert count == 0
        graph_repo.add_relation.assert_not_called()

    @pytest.mark.anyio
    async def test_two_markets_same_group_adds_one_relation(self):
        svc, graph_repo = self._make_service(relation_exists=False)
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1")]
        count = await svc.run(markets)
        assert count == 1
        graph_repo.add_relation.assert_called_once()
        kwargs = graph_repo.add_relation.call_args.kwargs
        assert kwargs["relation_type"] == RelationType.MUTUALLY_EXCLUSIVE
        assert kwargs["created_by"] == "stage1_constraint"

    @pytest.mark.anyio
    async def test_existing_relation_skipped(self):
        svc, graph_repo = self._make_service(relation_exists=True)
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1")]
        count = await svc.run(markets)
        assert count == 0
        graph_repo.add_relation.assert_not_called()

    @pytest.mark.anyio
    async def test_three_markets_adds_three_new_relations(self):
        svc, graph_repo = self._make_service(relation_exists=False)
        markets = [
            _market("pm", "a", "g1"),
            _market("pm", "b", "g1"),
            _market("pm", "c", "g1"),
        ]
        count = await svc.run(markets)
        assert count == 3
        assert graph_repo.add_relation.call_count == 3


class TestProverServiceStage2:
    def _make_prover(self, stage1_specs, classifier_result):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        detector = MagicMock()
        detector.detect.return_value = stage1_specs
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=classifier_result)
        svc = ProverService(session, graph_repo, stage2_classifier=classifier)
        svc._detector = detector
        return svc, graph_repo

    @pytest.mark.anyio
    async def test_mutually_exclusive_stored_without_stage2(self):
        from parallax.detection.stage1 import RelationSpec
        spec = RelationSpec(
            from_market_id="pm:a",
            to_market_id="pm:b",
            relation_type=RelationType.MUTUALLY_EXCLUSIVE,
            confidence=0.95,
            evidence={"rule": "intra_group"},
        )
        svc, graph_repo = self._make_prover([spec], classifier_result=None)
        count = await svc.run([])
        graph_repo.add_relation.assert_called_once()
        svc._stage2.classify.assert_not_called()

    @pytest.mark.anyio
    async def test_equivalent_requires_stage2_confirmation(self):
        from parallax.detection.stage1 import RelationSpec
        from parallax.detection.schemas import RelationClassification
        from parallax.shared.schemas import ContractSchema

        spec = RelationSpec(
            from_market_id="pm:a",
            to_market_id="kalshi:b",
            relation_type=RelationType.EQUIVALENT,
            confidence=0.6,
            evidence={"rule": "cross_platform_price_inversion"},
        )
        confirmed = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.88,
            reasoning="Both resolve YES when X happens.",
            breaking_scenarios=[],
            is_confirmed=True,
        )
        svc, graph_repo = self._make_prover([spec], classifier_result=confirmed)

        contract = ContractSchema(
            yes_conditions=["X happens"],
            no_conditions=["X does not happen"],
            exclusions=[], ambiguity_terms=[], counterexamples=[],
            compiler_confidence=0.85,
        )
        svc._get_contract = MagicMock(return_value=contract)

        count = await svc.run([])
        svc._stage2.classify.assert_called_once()
        graph_repo.add_relation.assert_called_once()

    @pytest.mark.anyio
    async def test_equivalent_not_stored_when_stage2_unconfirmed(self):
        from parallax.detection.stage1 import RelationSpec
        from parallax.detection.schemas import RelationClassification
        from parallax.shared.schemas import ContractSchema, Counterexample

        spec = RelationSpec(
            from_market_id="pm:a",
            to_market_id="kalshi:b",
            relation_type=RelationType.EQUIVALENT,
            confidence=0.6,
            evidence={"rule": "cross_platform_price_inversion"},
        )
        unconfirmed = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.4,
            reasoning="Deadlines differ.",
            breaking_scenarios=[Counterexample(
                scenario_description="X happens after cutoff",
                resolution_a="NO", resolution_b="YES",
                why_different="Different deadlines",
            )],
            is_confirmed=False,
        )
        svc, graph_repo = self._make_prover([spec], classifier_result=unconfirmed)
        contract = ContractSchema(
            yes_conditions=["X"], no_conditions=["not X"],
            exclusions=[], ambiguity_terms=[], counterexamples=[],
            compiler_confidence=0.85,
        )
        svc._get_contract = MagicMock(return_value=contract)
        count = await svc.run([])
        graph_repo.add_relation.assert_not_called()
        assert count == 0
