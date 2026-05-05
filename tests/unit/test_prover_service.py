from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import parallax.prover.service as prover_service

from parallax.db.models import RawMarket
from parallax.detection.proposal_generator import RelationProposal
from parallax.prover.service import RelationAnalysisService
from parallax.shared.schemas import (
    CompiledPropositionSchema,
    ContractSchema,
    Counterexample,
    IdentityResolutionStatus,
    RelationType,
)


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


def _contract() -> ContractSchema:
    return ContractSchema(
        yes_conditions=["X happens"],
        no_conditions=["X does not happen"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.85,
        canonical_subject="event",
        canonical_predicate="happens_before",
        canonical_object="x",
        temporal_deadline="2025-12-31T00:00:00+00:00",
        oracle_focus="official",
        proposition_family="event:happens_before",
    )


def _proposition(
    market_id: str,
    *,
    obj: str,
    family: str = "event:happens_before",
    partition_hint: bool = False,
) -> CompiledPropositionSchema:
    return CompiledPropositionSchema(
        raw_market_id=market_id,
        canonical_subject="event",
        canonical_predicate="happens_before",
        canonical_object=obj,
        temporal_deadline="2025-12-31T00:00:00+00:00",
        oracle_focus="official",
        proposition_family=family,
        partition_hint=partition_hint,
        semantic_tags=[],
        compiler_confidence=0.9,
    )


class TestRelationAnalysisService:
    def _make_service(self, relation_exists: bool = False):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = relation_exists
        service = RelationAnalysisService(session, graph_repo, semantic_analyzer=None)
        prover_service.load_identity_provenance = MagicMock(
            return_value={
                "canonical_event_id": "event-1",
                "identity_status": IdentityResolutionStatus.VERIFIED.value,
                "identity_confidence": 1.0,
                "identity_version": "identity-v2",
                "links": {},
            }
        )
        service._frame_builder = MagicMock()
        service._frame_builder.build_for_markets.return_value = {
            "pm:a": "frame-1",
            "pm:b": "frame-1",
        }
        service._get_market = MagicMock(side_effect=[_market("pm", "a", "g1"), _market("pm", "b", "g1")])
        service._get_contract = MagicMock(return_value=_contract())
        service._get_proposition = MagicMock(
            side_effect=[
                _proposition("pm:a", obj="candidate-a"),
                _proposition("pm:b", obj="candidate-b"),
            ]
        )
        return service, graph_repo

    @pytest.mark.anyio
    async def test_no_markets_adds_nothing(self):
        service, graph_repo = self._make_service()
        service._frame_builder.build_for_markets.return_value = {}
        service._get_proposition = MagicMock(return_value=None)
        count = await service.run([])
        assert count == 0
        graph_repo.add_relation.assert_not_called()

    @pytest.mark.anyio
    async def test_same_group_is_downgraded_to_same_event_independent(self):
        service, graph_repo = self._make_service()
        count = await service.run([_market("pm", "a", "g1"), _market("pm", "b", "g1")])
        assert count == 1
        kwargs = graph_repo.add_relation.call_args.kwargs
        assert kwargs["relation_type"] == RelationType.SAME_EVENT_INDEPENDENT
        assert kwargs["created_by"] == "logic_engine"
        assert kwargs["evidence"]["tradeable_relation"] is False

    @pytest.mark.anyio
    async def test_existing_relation_is_skipped(self):
        service, graph_repo = self._make_service(relation_exists=True)
        count = await service.run([_market("pm", "a", "g1"), _market("pm", "b", "g1")])
        assert count == 0
        graph_repo.add_relation.assert_not_called()

    @pytest.mark.anyio
    async def test_hypothesis_proposal_can_override_frame_fallback(self):
        service, graph_repo = self._make_service()
        service._proposal_generator.generate = MagicMock(
            return_value=[
                RelationProposal(
                    from_market_id="pm:a",
                    to_market_id="pm:b",
                    proposed_relation_type=RelationType.SAME_EVENT_FAMILY,
                    confidence=0.95,
                    frame_id="frame-1",
                    evidence={"rule": "same_frame_signature"},
                    hypothesis_source="frame",
                )
            ]
        )
        service._hypothesis_generator.generate = MagicMock(
            return_value=[
                RelationProposal(
                    from_market_id="pm:a",
                    to_market_id="pm:b",
                    proposed_relation_type=RelationType.SAME_EVENT_DIFFERENT_SOURCE,
                    confidence=0.6,
                    frame_id="frame-1",
                    evidence={"hypothesis_source": "hypothesis_generator", "same_frame": True},
                    semantic_question="Hypothesis: same event, different source?",
                    hypothesis_source="hypothesis_generator",
                )
            ]
        )
        count = await service.run([_market("pm", "a", "g1"), _market("pm", "b", "g1")])
        assert count == 1
        kwargs = graph_repo.add_relation.call_args.kwargs
        assert kwargs["relation_type"] == RelationType.SAME_EVENT_DIFFERENT_SOURCE
        assert kwargs["created_by"] == "logic_engine"


class TestRelationAnalysisWithSemanticReview:
    def _make_service(self, classification):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        analyzer = MagicMock()
        analyzer.classify = AsyncMock(return_value=classification)
        service = RelationAnalysisService(session, graph_repo, semantic_analyzer=analyzer)
        prover_service.load_identity_provenance = MagicMock(
            return_value={
                "canonical_event_id": "event-1",
                "identity_status": IdentityResolutionStatus.VERIFIED.value,
                "identity_confidence": 0.92,
                "identity_version": "identity-v2",
                "links": {},
            }
        )
        service._frame_builder = MagicMock()
        service._frame_builder.build_for_markets.return_value = {
            "pm:a": "frame-1",
            "kalshi:b": "frame-1",
        }
        service._get_market = MagicMock(side_effect=[_market("pm", "a", "g1"), _market("kalshi", "b", "g1")])
        service._get_contract = MagicMock(return_value=_contract())
        service._get_proposition = MagicMock(
            side_effect=[
                _proposition("pm:a", obj="same-object"),
                _proposition("kalshi:b", obj="same-object"),
            ]
        )
        return service, graph_repo, analyzer

    @pytest.mark.anyio
    async def test_equivalent_relation_uses_semantic_analyzer(self):
        from parallax.detection.schemas import RelationClassification

        classification = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.88,
            reasoning="Both resolve YES when X happens.",
            comparison_axes=["yes_conditions", "no_conditions", "deadline"],
            breaking_scenarios=[],
            is_confirmed=True,
            tradeable_relation=True,
            proof_status="verified",
        )
        service, graph_repo, analyzer = self._make_service(classification)

        count = await service.run([_market("pm", "a", "g1"), _market("kalshi", "b", "g1")])

        assert count == 1
        analyzer.classify.assert_awaited_once()
        evidence = graph_repo.add_relation.call_args.kwargs["evidence"]
        assert evidence["semantic_confidence"] == 0.88
        assert evidence["structural_relation_type"] == RelationType.EQUIVALENT.value
        assert evidence["tradeable_relation"] is True
        assert evidence["proof_status"] == "verified"

    @pytest.mark.anyio
    async def test_unconfirmed_relation_persists_abstention_reason(self):
        from parallax.detection.schemas import RelationClassification

        classification = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.4,
            reasoning="Deadlines differ.",
            comparison_axes=["deadline"],
            breaking_scenarios=[
                Counterexample(
                    scenario_description="Late cutoff",
                    resolution_a="NO",
                    resolution_b="YES",
                    why_different="Different deadlines",
                )
            ],
            is_confirmed=False,
            tradeable_relation=False,
            proof_status="rejected",
        )
        service, graph_repo, _ = self._make_service(classification)

        count = await service.run([_market("pm", "a", "g1"), _market("kalshi", "b", "g1")])

        assert count == 1
        evidence = graph_repo.add_relation.call_args.kwargs["evidence"]
        assert evidence["is_confirmed"] is False
        assert evidence["tradeable_relation"] is False
        assert evidence["proof_status"] == "rejected"
        assert "abstention_reason" in evidence


class TestExhaustivePartitionPersistence:
    @pytest.mark.anyio
    async def test_partition_sets_persist_exhaustive_partition_relations(self):
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        graph_repo.add_relation.return_value = "rel-1"
        graph_repo.add_review.return_value = "review-1"
        service = RelationAnalysisService(session, graph_repo, semantic_analyzer=None)
        prover_service.load_identity_provenance = MagicMock(
            return_value={
                "canonical_event_id": "event-1",
                "identity_status": IdentityResolutionStatus.VERIFIED.value,
                "identity_confidence": 1.0,
                "identity_version": "identity-v2",
                "links": {},
            }
        )
        service._frame_builder = MagicMock()
        service._frame_builder.build_for_markets.return_value = {
            "pm:a": "frame-1",
            "pm:b": "frame-1",
            "pm:c": "frame-1",
        }
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1"), _market("pm", "c", "g1")]
        service._get_market = MagicMock(side_effect=markets + markets)
        service._get_contract = MagicMock(return_value=_contract())
        service._get_proposition = MagicMock(
            side_effect=[
                _proposition("pm:a", obj="candidate-a", partition_hint=True),
                _proposition("pm:b", obj="candidate-b", partition_hint=True),
                _proposition("pm:c", obj="candidate-c", partition_hint=True),
            ]
        )

        count = await service.run(markets)

        assert count >= 3
        graph_repo.add_relation_set.assert_called_once()
        relation_types = [call.kwargs["relation_type"] for call in graph_repo.add_relation.call_args_list]
        assert RelationType.EXHAUSTIVE_PARTITION in relation_types
        partition_calls = [
            call for call in graph_repo.add_relation.call_args_list
            if call.kwargs["relation_type"] == RelationType.EXHAUSTIVE_PARTITION
        ]
        assert partition_calls
        for call in partition_calls:
            assert call.kwargs["evidence"]["set_key"] == "pm:a|pm:b|pm:c"
            assert call.kwargs["evidence"]["counterexample_status"] == "none_found"

    @pytest.mark.anyio
    async def test_partition_semantic_review_covers_all_pairs(self):
        from parallax.detection.schemas import RelationClassification

        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        graph_repo.add_relation.return_value = "rel-1"
        graph_repo.add_review.return_value = "review-1"
        analyzer = MagicMock()
        analyzer.classify = AsyncMock(
            return_value=RelationClassification(
                relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                confidence=0.83,
                reasoning="Pair is mutually exclusive.",
                comparison_axes=["yes_conditions", "deadline"],
                breaking_scenarios=[],
                is_confirmed=True,
                tradeable_relation=True,
                proof_status="verified",
            )
        )
        service = RelationAnalysisService(session, graph_repo, semantic_analyzer=analyzer)
        prover_service.load_identity_provenance = MagicMock(
            return_value={
                "canonical_event_id": "event-1",
                "identity_status": IdentityResolutionStatus.VERIFIED.value,
                "identity_confidence": 0.91,
                "identity_version": "identity-v2",
                "links": {},
            }
        )
        service._frame_builder = MagicMock()
        service._frame_builder.build_for_markets.return_value = {
            "pm:a": "frame-1",
            "pm:b": "frame-1",
            "pm:c": "frame-1",
        }
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1"), _market("pm", "c", "g1")]
        service._get_market = MagicMock(side_effect=markets + markets + markets)
        service._get_contract = MagicMock(return_value=_contract())
        service._get_proposition = MagicMock(
            side_effect=[
                _proposition("pm:a", obj="candidate-a", partition_hint=True),
                _proposition("pm:b", obj="candidate-b", partition_hint=True),
                _proposition("pm:c", obj="candidate-c", partition_hint=True),
            ]
        )

        count = await service.run(markets)

        assert count >= 3
        assert analyzer.classify.await_count == 6
        graph_repo.add_relation_set.assert_called_once()
        relation_set_call = graph_repo.add_relation_set.call_args.kwargs
        assert relation_set_call["set_key"] == "pm:a|pm:b|pm:c"
        assert relation_set_call["relation_type"] == RelationType.EXHAUSTIVE_PARTITION
        partition_calls = [
            call for call in graph_repo.add_relation.call_args_list
            if call.kwargs["relation_type"] == RelationType.EXHAUSTIVE_PARTITION
        ]
        assert len(partition_calls) == 3
        for call in partition_calls:
            evidence = call.kwargs["evidence"]
            assert evidence["tradeable_relation"] is True
            assert evidence["proof_status"] == "verified"
            assert evidence["counterexample_status"] == "none_found"
            assert len(evidence["semantic_pair_reviews"]) == 3
        none_found_records = [
            call.args[0]
            for call in graph_repo.add_counterexample_record.call_args_list
            if call.args[0].status == "none_found" and call.args[0].set_key == "pm:a|pm:b|pm:c"
        ]
        assert len(none_found_records) == 3

    @pytest.mark.anyio
    async def test_partition_semantic_review_rejects_when_any_pair_breaks(self):
        from parallax.detection.schemas import RelationClassification

        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        graph_repo.add_relation.return_value = "rel-1"
        graph_repo.add_review.return_value = "review-1"
        analyzer = MagicMock()
        analyzer.classify = AsyncMock(
            side_effect=[
                RelationClassification(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.9,
                    reasoning="Pair is mutually exclusive.",
                    comparison_axes=["yes_conditions"],
                    breaking_scenarios=[],
                    is_confirmed=True,
                    tradeable_relation=True,
                    proof_status="verified",
                ),
                RelationClassification(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.88,
                    reasoning="Pair is mutually exclusive.",
                    comparison_axes=["yes_conditions"],
                    breaking_scenarios=[],
                    is_confirmed=True,
                    tradeable_relation=True,
                    proof_status="verified",
                ),
                RelationClassification(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.87,
                    reasoning="Pair is mutually exclusive.",
                    comparison_axes=["yes_conditions"],
                    breaking_scenarios=[],
                    is_confirmed=True,
                    tradeable_relation=True,
                    proof_status="verified",
                ),
                RelationClassification(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.86,
                    reasoning="Pair is mutually exclusive.",
                    comparison_axes=["yes_conditions"],
                    breaking_scenarios=[],
                    is_confirmed=True,
                    tradeable_relation=True,
                    proof_status="verified",
                ),
                RelationClassification(
                    relation_type=RelationType.RELATED_BUT_NOT_TRADEABLE,
                    confidence=0.34,
                    reasoning="This pair can co-resolve.",
                    comparison_axes=["resolution_criteria"],
                    breaking_scenarios=[
                        Counterexample(
                            scenario_description="A and C can both resolve YES.",
                            resolution_a="YES",
                            resolution_b="YES",
                            why_different="Outcomes are not disjoint",
                        )
                    ],
                    is_confirmed=False,
                    tradeable_relation=False,
                    proof_status="rejected",
                ),
                RelationClassification(
                    relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                    confidence=0.8,
                    reasoning="Pair is mutually exclusive.",
                    comparison_axes=["yes_conditions"],
                    breaking_scenarios=[],
                    is_confirmed=True,
                    tradeable_relation=True,
                    proof_status="verified",
                ),
            ]
        )
        service = RelationAnalysisService(session, graph_repo, semantic_analyzer=analyzer)
        prover_service.load_identity_provenance = MagicMock(
            return_value={
                "canonical_event_id": "event-1",
                "identity_status": IdentityResolutionStatus.VERIFIED.value,
                "identity_confidence": 0.91,
                "identity_version": "identity-v2",
                "links": {},
            }
        )
        service._frame_builder = MagicMock()
        service._frame_builder.build_for_markets.return_value = {
            "pm:a": "frame-1",
            "pm:b": "frame-1",
            "pm:c": "frame-1",
        }
        markets = [_market("pm", "a", "g1"), _market("pm", "b", "g1"), _market("pm", "c", "g1")]
        service._get_market = MagicMock(side_effect=markets + markets + markets)
        service._get_contract = MagicMock(return_value=_contract())
        service._get_proposition = MagicMock(
            side_effect=[
                _proposition("pm:a", obj="candidate-a", partition_hint=True),
                _proposition("pm:b", obj="candidate-b", partition_hint=True),
                _proposition("pm:c", obj="candidate-c", partition_hint=True),
            ]
        )

        count = await service.run(markets)

        assert count >= 3
        graph_repo.add_relation_set.assert_called_once()
        relation_set_call = graph_repo.add_relation_set.call_args.kwargs
        assert relation_set_call["relation_type"] == RelationType.EXHAUSTIVE_PARTITION
        assert relation_set_call["evidence"]["counterexample_status"] == "recorded"
        partition_calls = [
            call for call in graph_repo.add_relation.call_args_list
            if call.kwargs["relation_type"] == RelationType.EXHAUSTIVE_PARTITION
        ]
        assert len(partition_calls) == 3
        for call in partition_calls:
            evidence = call.kwargs["evidence"]
            assert evidence["tradeable_relation"] is False
            assert evidence["proof_status"] == "rejected"
            assert evidence["counterexample_status"] == "recorded"
            assert len(evidence["semantic_pair_reviews"]) == 3
        recorded = [
            call.args[0]
            for call in graph_repo.add_counterexample_record.call_args_list
            if call.args[0].status == "recorded"
        ]
        assert recorded

    @pytest.mark.anyio
    async def test_identity_gate_downgrades_tradeable_relation(self):
        from parallax.detection.schemas import RelationClassification

        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        analyzer = MagicMock()
        analyzer.classify = AsyncMock(
            return_value=RelationClassification(
                relation_type=RelationType.EQUIVALENT,
                confidence=0.88,
                reasoning="Both resolve the same.",
                comparison_axes=["yes_conditions"],
                breaking_scenarios=[],
                is_confirmed=True,
                tradeable_relation=True,
                proof_status="verified",
            )
        )
        service = RelationAnalysisService(session, graph_repo, semantic_analyzer=analyzer)
        prover_service.load_identity_provenance = MagicMock(
            return_value={
                "canonical_event_id": "event-1",
                "identity_status": IdentityResolutionStatus.AMBIGUOUS.value,
                "identity_confidence": 0.51,
                "identity_version": "identity-v2",
                "identity_blocking_reason": "top candidate too close to runner-up",
                "links": {},
            }
        )
        service._frame_builder = MagicMock()
        service._frame_builder.build_for_markets.return_value = {
            "pm:a": "frame-1",
            "kalshi:b": "frame-1",
        }
        service._get_market = MagicMock(side_effect=[_market("pm", "a", "g1"), _market("kalshi", "b", "g1")])
        service._get_contract = MagicMock(return_value=_contract())
        service._get_proposition = MagicMock(
            side_effect=[
                _proposition("pm:a", obj="same-object"),
                _proposition("kalshi:b", obj="same-object"),
            ]
        )

        count = await service.run([_market("pm", "a", "g1"), _market("kalshi", "b", "g1")])

        assert count == 1
        evidence = graph_repo.add_relation.call_args.kwargs["evidence"]
        assert evidence["identity_status"] == IdentityResolutionStatus.AMBIGUOUS.value
        assert evidence["tradeable_relation"] is False
        assert evidence["proof_status"] == "needs_review"
