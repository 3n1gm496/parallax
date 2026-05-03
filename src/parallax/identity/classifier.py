from __future__ import annotations

from parallax.shared.schemas import IdentityType

_DUPLICATE_THRESHOLD = 0.80
_SAME_EVENT_THRESHOLD = 0.85
_DIFF_TYPE_THRESHOLD = 0.75
_NEAR_DUPLICATE_THRESHOLD = 0.55
_CORRELATED_THRESHOLD = 0.30
_CORRELATED_ENTITY_MIN = 2


class PairClassifier:
    def classify(
        self,
        *,
        lexical_score: float,
        predicate_match: bool,
        entity_overlap: int,
        deadline_delta_hours: float,
        oracle_mismatch: bool,
        source_mismatch: bool,
        platform_group_match: bool,
        subset_signal: bool,
        superset_signal: bool,
        embedding_score: float | None = None,
    ) -> IdentityType:
        effective = embedding_score if embedding_score is not None else lexical_score

        if platform_group_match and effective >= _DUPLICATE_THRESHOLD:
            return IdentityType.DUPLICATE_MARKET

        if (
            effective >= _SAME_EVENT_THRESHOLD
            and predicate_match
            and not oracle_mismatch
            and not source_mismatch
            and deadline_delta_hours <= 6
        ):
            return IdentityType.SAME_EVENT

        if effective >= _DIFF_TYPE_THRESHOLD and predicate_match:
            if oracle_mismatch:
                return IdentityType.SAME_EVENT_DIFF_ORACLE
            if source_mismatch:
                return IdentityType.SAME_EVENT_DIFF_SOURCE
            if deadline_delta_hours > 24:
                return IdentityType.SAME_EVENT_DIFF_DEADLINE

        if effective >= _NEAR_DUPLICATE_THRESHOLD:
            if subset_signal:
                return IdentityType.SUBSET
            if superset_signal:
                return IdentityType.SUPERSET
            return IdentityType.NEAR_DUPLICATE

        if effective >= _CORRELATED_THRESHOLD and entity_overlap >= _CORRELATED_ENTITY_MIN:
            return IdentityType.CORRELATED

        return IdentityType.FALSE_EQUIVALENCE
