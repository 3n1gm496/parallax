from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parallax.db.models import RawMarket
from parallax.detection.hypothesis_generator import (
    RelationHypothesisGenerator,
    _compatible_deadline,
    _semantic_key,
)
from parallax.detection.proposal_generator import RelationProposal
from parallax.logic.relation_rules import RelationRuleEngine
from parallax.shared.schemas import CompiledPropositionSchema, RelationType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _market(platform: str, market_id: str, group_id: str | None = None) -> RawMarket:
    return RawMarket(
        id=f"{platform}:{market_id}",
        platform=platform,
        market_id=market_id,
        title=f"{platform} {market_id}",
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[0.5, 0.5],
        category="politics",
        group_id=group_id,
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=None,
        raw_payload={},
    )


def _prop(
    market_id: str,
    *,
    subject: str = "candidate_x",
    predicate: str = "wins_election",
    obj: str | None = None,
    family: str = "election:wins",
    partition_hint: bool = False,
    polarity: str = "positive",
    deadline: str = "2025-12-31T00:00:00+00:00",
    oracle: str | None = "official",
    threshold_value: str | None = None,
) -> CompiledPropositionSchema:
    return CompiledPropositionSchema(
        raw_market_id=market_id,
        canonical_subject=subject,
        canonical_predicate=predicate,
        canonical_object=obj,
        temporal_deadline=deadline,
        oracle_focus=oracle,
        oracle_scope=oracle,
        proposition_family=family,
        partition_hint=partition_hint,
        polarity=polarity,
        semantic_tags=[],
        compiler_confidence=0.9,
        threshold_value=threshold_value,
    )


def _gen() -> RelationHypothesisGenerator:
    return RelationHypothesisGenerator()


# ---------------------------------------------------------------------------
# 1. Duplicate / equivalent markets → EQUIVALENT hypothesis
# ---------------------------------------------------------------------------

def test_cross_platform_equivalent_markets_produce_equivalent_hypothesis():
    pm = _market("polymarket", "abc")
    ks = _market("kalshi", "xyz")
    props = {
        pm.id: _prop(pm.id, subject="candidate_x", predicate="wins_election", obj="general_2025"),
        ks.id: _prop(ks.id, subject="candidate_x", predicate="wins_election", obj="general_2025",
                     family="kalshi:election"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids={})
    assert len(proposals) == 1
    p = proposals[0]
    assert p.proposed_relation_type == RelationType.EQUIVALENT
    assert p.hypothesis_source == "hypothesis_generator"
    assert p.semantic_question is not None and "equivalent" in p.semantic_question.lower()
    assert p.confidence >= 0.7


# ---------------------------------------------------------------------------
# 2. Inverse wording → INVERSE hypothesis
# ---------------------------------------------------------------------------

def test_inverse_polarity_produces_inverse_hypothesis():
    pm = _market("polymarket", "abc")
    ks = _market("kalshi", "xyz")
    props = {
        pm.id: _prop(pm.id, subject="candidate_x", predicate="wins_election",
                     polarity="positive", family="pm:election"),
        ks.id: _prop(ks.id, subject="candidate_x", predicate="wins_election",
                     polarity="negative", family="kalshi:election"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids={})
    assert any(p.proposed_relation_type == RelationType.INVERSE for p in proposals)
    inv = next(p for p in proposals if p.proposed_relation_type == RelationType.INVERSE)
    assert "inverse" in inv.semantic_question.lower()


# ---------------------------------------------------------------------------
# 3. Two candidates in same election → MUTUALLY_EXCLUSIVE
# ---------------------------------------------------------------------------

def test_partition_hint_pair_produces_mutually_exclusive():
    pm_a = _market("polymarket", "candA")
    pm_b = _market("polymarket", "candB")
    props = {
        pm_a.id: _prop(pm_a.id, subject="election_2025", predicate="winner_is",
                       obj="candidate_a", partition_hint=True, family="pm:election_2025"),
        pm_b.id: _prop(pm_b.id, subject="election_2025", predicate="winner_is",
                       obj="candidate_b", partition_hint=True, family="pm:election_2025"),
    }
    # Different frames (different market IDs, no shared group)
    proposals = _gen().generate(markets=[pm_a, pm_b], propositions=props, frame_ids={})
    me = [p for p in proposals if p.proposed_relation_type == RelationType.MUTUALLY_EXCLUSIVE]
    assert len(me) >= 1
    assert "mutually exclusive" in me[0].semantic_question.lower()


# ---------------------------------------------------------------------------
# 4. n election outcomes → exhaustive partition via RelationRuleEngine
# ---------------------------------------------------------------------------

def test_n_election_outcomes_produce_exhaustive_partition_in_rule_engine():
    rule_engine = RelationRuleEngine()
    props = [
        _prop(f"pm:{c}", subject="election_2025", predicate="winner_is",
              obj=f"candidate_{c}", partition_hint=True, family="pm:election_2025",
              deadline="2025-12-31T00:00:00+00:00", oracle="official")
        for c in ["a", "b", "c"]
    ]
    result = rule_engine.classify_partition_set(props)
    assert result is not None
    assert result.relation_type == RelationType.EXHAUSTIVE_PARTITION
    assert result.tradeable_relation is True
    assert result.proof_status == "verified"
    assert result.requires_semantic_review is True


# ---------------------------------------------------------------------------
# 5. Stricter deadline → SUBSET/SUPERSET direction
# ---------------------------------------------------------------------------

def test_stricter_threshold_produces_subset_hypothesis():
    pm = _market("polymarket", "strict")
    ks = _market("kalshi", "loose")
    props = {
        pm.id: _prop(pm.id, subject="inflation_rate", predicate="exceeds",
                     obj="threshold_percent", threshold_value="0.06",  # 6% — stricter
                     family="pm:inflation"),
        ks.id: _prop(ks.id, subject="inflation_rate", predicate="exceeds",
                     obj="threshold_percent", threshold_value="0.04",  # 4% — looser
                     family="kalshi:inflation"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids={})
    # 6% exceeding is harder than 4% → pm market is SUBSET of kalshi market
    subset_proposals = [p for p in proposals if p.proposed_relation_type in
                        (RelationType.SUBSET, RelationType.SUPERSET)]
    assert len(subset_proposals) >= 1


def test_same_frame_pairs_can_still_generate_hypotheses():
    """Markets already in same frame can still produce stronger semantic hypotheses."""
    pm = _market("polymarket", "m1")
    ks = _market("kalshi", "m2")
    shared_frame = "frame-99"
    frame_ids = {pm.id: shared_frame, ks.id: shared_frame}
    props = {
        pm.id: _prop(pm.id, subject="event_x", predicate="happens", family="pm:event"),
        ks.id: _prop(ks.id, subject="event_x", predicate="happens", family="kalshi:event"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids=frame_ids)
    assert len(proposals) >= 1
    assert any(p.frame_id == shared_frame for p in proposals)


# ---------------------------------------------------------------------------
# 6. Different source same event → SAME_EVENT_DIFFERENT_SOURCE
# ---------------------------------------------------------------------------

def test_different_oracle_same_event_produces_same_event_different_source():
    pm = _market("polymarket", "m1")
    ks = _market("kalshi", "m2")
    props = {
        pm.id: _prop(pm.id, subject="gdp_growth", predicate="exceeds_2pct",
                     obj="q4_2025", oracle="bls_official", family="pm:gdp"),
        ks.id: _prop(ks.id, subject="gdp_growth", predicate="exceeds_2pct",
                     obj="q4_2025", oracle="fed_estimate", family="kalshi:gdp"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids={})
    source_hyp = [p for p in proposals if p.proposed_relation_type == RelationType.SAME_EVENT_DIFFERENT_SOURCE]
    assert len(source_hyp) >= 1


# ---------------------------------------------------------------------------
# 7. Correlated-only markets do not become tradeable
# ---------------------------------------------------------------------------

def test_unrelated_subject_predicate_produces_no_hypothesis():
    pm = _market("polymarket", "m1")
    ks = _market("kalshi", "m2")
    props = {
        pm.id: _prop(pm.id, subject="bitcoin_price", predicate="exceeds_100k",
                     family="pm:crypto"),
        ks.id: _prop(ks.id, subject="sp500_level", predicate="exceeds_5000",
                     family="kalshi:equity"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids={})
    assert len(proposals) == 0


def test_hypothesis_proposals_always_have_tradeable_false_initially():
    """Hypotheses start non-tradeable — LogicEngine/SemanticVeto must confirm."""
    pm = _market("polymarket", "abc")
    ks = _market("kalshi", "xyz")
    props = {
        pm.id: _prop(pm.id, subject="candidate_x", predicate="wins_election",
                     obj="race_2025", family="pm:election"),
        ks.id: _prop(ks.id, subject="candidate_x", predicate="wins_election",
                     obj="race_2025", family="kalshi:election"),
    }
    proposals = _gen().generate(markets=[pm, ks], propositions=props, frame_ids={})
    # evidence dict does not set tradeable_relation=True (that's for LogicEngine to decide)
    for p in proposals:
        assert p.evidence.get("tradeable_relation", False) is False


# ---------------------------------------------------------------------------
# 8. Semantic veto blocks false equivalence
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_semantic_veto_rejects_false_equivalence():
    from parallax.detection.schemas import RelationClassification
    from parallax.detection.semantic import SemanticRelationAnalyzer
    from parallax.detection.semantic_veto import SemanticVeto
    from parallax.shared.schemas import ContractSchema, Counterexample

    breaking = [Counterexample(
        scenario_description="Oracle A says YES; Oracle B says NO because of different rounding",
        resolution_a="YES",
        resolution_b="NO",
        why_different="Oracle divergence",
    )]
    false_classification = RelationClassification(
        relation_type=RelationType.EQUIVALENT,
        confidence=0.4,
        reasoning="oracles diverge",
        comparison_axes=["oracle"],
        breaking_scenarios=breaking,
        is_confirmed=False,
        tradeable_relation=False,
        proof_status="rejected",
    )

    analyzer = MagicMock(spec=SemanticRelationAnalyzer)
    analyzer.classify = AsyncMock(return_value=false_classification)
    veto = SemanticVeto(analyzer)

    contract = ContractSchema(
        yes_conditions=["A wins"],
        no_conditions=["A loses"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.9,
        canonical_subject="candidate_x",
        canonical_predicate="wins_election",
        canonical_object="race_2025",
        temporal_deadline="2025-12-31T00:00:00+00:00",
        oracle_focus="official",
        proposition_family="election:wins",
    )
    result = await veto.review(
        contract, contract,
        proposed_relation=RelationType.EQUIVALENT,
        hypothesis_context="Hypothesis: these two markets are equivalent.",
    )
    assert result is not None
    assert result.tradeable_relation is False
    # Verify the hypothesis_context was passed to the analyzer
    call_kwargs = analyzer.classify.call_args.kwargs
    assert call_kwargs.get("hypothesis_context") == "Hypothesis: these two markets are equivalent."


# ---------------------------------------------------------------------------
# 9. Semantic proof receives typed hypothesis (not generic proposed_relation only)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_semantic_analyzer_receives_hypothesis_context():
    from parallax.detection.schemas import RelationClassification
    from parallax.detection.semantic import SemanticRelationAnalyzer
    from parallax.detection.semantic_veto import SemanticVeto

    classification = RelationClassification(
        relation_type=RelationType.EQUIVALENT,
        confidence=0.85,
        reasoning="semantically equivalent",
        comparison_axes=["yes_conditions"],
        breaking_scenarios=[],
        is_confirmed=True,
        tradeable_relation=True,
        proof_status="verified",
    )
    analyzer = MagicMock(spec=SemanticRelationAnalyzer)
    analyzer.classify = AsyncMock(return_value=classification)
    veto = SemanticVeto(analyzer)

    from parallax.shared.schemas import ContractSchema
    contract = ContractSchema(
        yes_conditions=["X wins"],
        no_conditions=["X loses"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.9,
        canonical_subject="candidate_x",
        canonical_predicate="wins_election",
        canonical_object=None,
        temporal_deadline="2025-12-31T00:00:00+00:00",
        oracle_focus="official",
        proposition_family="election:wins",
    )
    typed_question = "Hypothesis: these markets are equivalent cross-platform."
    await veto.review(
        contract, contract,
        proposed_relation=RelationType.EQUIVALENT,
        hypothesis_context=typed_question,
    )
    kwargs = analyzer.classify.call_args.kwargs
    assert kwargs["hypothesis_context"] == typed_question


# ---------------------------------------------------------------------------
# 10. Relation sets generated for n-ary alternatives (via RelationRuleEngine)
# ---------------------------------------------------------------------------

def test_exhaustive_partition_set_requires_partition_hint_and_unique_objects():
    rule_engine = RelationRuleEngine()

    # Without partition_hint → no exhaustive partition
    props_no_hint = [
        _prop(f"pm:{c}", subject="election_2025", predicate="winner_is",
              obj=f"candidate_{c}", partition_hint=False, family="pm:election_2025")
        for c in ["a", "b", "c"]
    ]
    result = rule_engine.classify_partition_set(props_no_hint)
    assert result is None

    # With partition_hint and unique objects → exhaustive partition
    props_with_hint = [
        _prop(f"pm:{c}", subject="election_2025", predicate="winner_is",
              obj=f"candidate_{c}", partition_hint=True, family="pm:election_2025")
        for c in ["a", "b", "c"]
    ]
    result = rule_engine.classify_partition_set(props_with_hint)
    assert result is not None
    assert result.relation_type == RelationType.EXHAUSTIVE_PARTITION
    assert result.tradeable_relation is True
    assert result.proof_status == "verified"


# ---------------------------------------------------------------------------
# 11. Cross-platform EQUIVALENT passes through LogicEngine correctly
# ---------------------------------------------------------------------------

def test_cross_platform_equivalent_hypothesis_passes_logic_engine():
    from parallax.logic.logic_engine import LogicEngine

    engine = LogicEngine()
    prop_a = _prop("pm:abc", subject="candidate_x", predicate="wins_election",
                   obj="race_2025", family="pm:election")
    prop_b = _prop("kalshi:xyz", subject="candidate_x", predicate="wins_election",
                   obj="race_2025", family="kalshi:election")
    proposal = RelationProposal(
        from_market_id="pm:abc",
        to_market_id="kalshi:xyz",
        proposed_relation_type=RelationType.EQUIVALENT,
        confidence=0.82,
        frame_id=None,
        evidence={"hypothesis_source": "hypothesis_generator"},
        semantic_question="Hypothesis: equivalent cross-platform markets.",
        hypothesis_source="hypothesis_generator",
    )
    decision = engine.adjudicate(proposal, prop_a, prop_b)
    # Cross-platform relaxed equivalence: needs semantic review but stays EQUIVALENT
    assert decision.relation_type == RelationType.EQUIVALENT
    assert decision.requires_semantic_review is True


# ---------------------------------------------------------------------------
# 12. Production gates unchanged: same_event_family stays non-tradeable
# ---------------------------------------------------------------------------

def test_same_event_family_remains_not_tradeable():
    RelationRuleEngine()
    prop_a = _prop("pm:m1", subject="s", predicate="p", obj="o", family="fam")
    prop_b = _prop("pm:m2", subject="s", predicate="p", obj="o2", family="fam",
                   partition_hint=False)
    proposal = RelationProposal(
        from_market_id="pm:m1",
        to_market_id="pm:m2",
        proposed_relation_type=RelationType.SAME_EVENT_FAMILY,
        confidence=0.9,
        frame_id="frame-1",
        evidence={},
    )
    from parallax.logic.logic_engine import LogicEngine
    engine = LogicEngine()
    decision = engine.adjudicate(proposal, prop_a, prop_b)
    assert decision.tradeable_relation is False


# ---------------------------------------------------------------------------
# Helpers tests
# ---------------------------------------------------------------------------

def test_compatible_deadline_same_value():
    assert _compatible_deadline("2025-12-31T00:00:00+00:00", "2025-12-31T00:00:00+00:00") is True


def test_compatible_deadline_within_48h():
    assert _compatible_deadline("2025-12-31T00:00:00+00:00", "2026-01-01T12:00:00+00:00") is True


def test_compatible_deadline_beyond_48h():
    assert _compatible_deadline("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00") is False


def test_compatible_deadline_none_is_compatible():
    assert _compatible_deadline(None, "2025-12-31T00:00:00+00:00") is True
    assert _compatible_deadline("2025-12-31T00:00:00+00:00", None) is True


def test_semantic_key_normalizes():
    prop = _prop("pm:x", subject="  Candidate X  ", predicate="WINS_ELECTION")
    key = _semantic_key(prop)
    assert key == "candidate x\x00wins_election"


def test_semantic_key_empty_subject_returns_empty():
    prop = _prop("pm:x", subject="", predicate="wins")
    assert _semantic_key(prop) == ""
