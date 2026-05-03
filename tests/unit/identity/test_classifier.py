from __future__ import annotations

from parallax.identity.classifier import PairClassifier
from parallax.shared.schemas import IdentityType


def _classify(**kwargs):
    defaults = dict(
        lexical_score=0.0,
        predicate_match=False,
        entity_overlap=0,
        deadline_delta_hours=0.0,
        oracle_mismatch=False,
        source_mismatch=False,
        platform_group_match=False,
        subset_signal=False,
        superset_signal=False,
        embedding_score=None,
    )
    defaults.update(kwargs)
    return PairClassifier().classify(**defaults)


class TestPairClassifier:
    def test_platform_group_match_high_score_is_duplicate(self):
        assert _classify(platform_group_match=True, lexical_score=0.9, predicate_match=True) == IdentityType.DUPLICATE_MARKET

    def test_high_score_no_mismatches_is_same_event(self):
        assert _classify(lexical_score=0.9, predicate_match=True, entity_overlap=3, deadline_delta_hours=2.0) == IdentityType.SAME_EVENT

    def test_high_score_oracle_mismatch_is_same_event_diff_oracle(self):
        assert _classify(
            lexical_score=0.85,
            predicate_match=True,
            entity_overlap=3,
            oracle_mismatch=True,
            deadline_delta_hours=2.0,
        ) == IdentityType.SAME_EVENT_DIFF_ORACLE

    def test_high_score_source_mismatch_is_same_event_diff_source(self):
        assert _classify(
            lexical_score=0.85,
            predicate_match=True,
            entity_overlap=3,
            source_mismatch=True,
            deadline_delta_hours=2.0,
        ) == IdentityType.SAME_EVENT_DIFF_SOURCE

    def test_high_score_deadline_mismatch_is_same_event_diff_deadline(self):
        assert _classify(
            lexical_score=0.85,
            predicate_match=True,
            entity_overlap=3,
            deadline_delta_hours=72.0,
        ) == IdentityType.SAME_EVENT_DIFF_DEADLINE

    def test_medium_score_is_near_duplicate(self):
        assert _classify(lexical_score=0.60, predicate_match=True, entity_overlap=2, deadline_delta_hours=6.0) == IdentityType.NEAR_DUPLICATE

    def test_medium_score_subset_signal(self):
        assert _classify(
            lexical_score=0.60,
            predicate_match=True,
            entity_overlap=2,
            subset_signal=True,
            deadline_delta_hours=6.0,
        ) == IdentityType.SUBSET

    def test_medium_score_superset_signal(self):
        assert _classify(
            lexical_score=0.60,
            predicate_match=True,
            entity_overlap=2,
            superset_signal=True,
            deadline_delta_hours=6.0,
        ) == IdentityType.SUPERSET

    def test_low_score_with_entity_overlap_is_correlated(self):
        assert _classify(lexical_score=0.35, entity_overlap=3) == IdentityType.CORRELATED

    def test_low_score_no_overlap_is_false_equivalence(self):
        assert _classify(lexical_score=0.1, entity_overlap=0) == IdentityType.FALSE_EQUIVALENCE

    def test_embedding_score_overrides_lexical_for_same_event(self):
        assert _classify(
            lexical_score=0.4,
            embedding_score=0.92,
            predicate_match=True,
            entity_overlap=3,
            deadline_delta_hours=2.0,
        ) == IdentityType.SAME_EVENT

    def test_embedding_score_overrides_lexical_for_near_duplicate(self):
        assert _classify(
            lexical_score=0.3,
            embedding_score=0.65,
            predicate_match=True,
            entity_overlap=2,
            deadline_delta_hours=6.0,
        ) == IdentityType.NEAR_DUPLICATE
