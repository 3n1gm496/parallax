from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations

from parallax.db.models import RawMarket
from parallax.detection.proposal_generator import RelationProposal
from parallax.shared.schemas import CompiledPropositionSchema, RelationType

HYPOTHESIS_EVIDENCE_VERSION = "hypothesis-v1"

# Per-type semantic question templates sent to the LLM when this hypothesis is reviewed
HYPOTHESIS_QUESTIONS: dict[RelationType, str] = {
    RelationType.EQUIVALENT: (
        "Hypothesis: Market A and Market B are logically equivalent — they describe the same event "
        "under the same conditions and must always resolve identically. If A resolves YES, B must "
        "resolve YES (and vice versa). "
        "Check: (1) Do resolution criteria differ in any way that could cause divergent outcomes? "
        "(2) Are deadlines compatible — could a timing difference produce a divergence? "
        "(3) Are oracles compatible — could different data sources resolve differently on the same event? "
        "(4) Could platform-specific rules (e.g. voiding, rounding, ambiguity handling) cause divergence? "
        "Set tradeable_relation=True only if the relationship is safe for arbitrage pricing after fees."
    ),
    RelationType.DUPLICATE: (
        "Hypothesis: Market A and Market B are duplicates — they describe the same event with only "
        "minor wording or timing differences that do not affect resolution. If A resolves YES, B must "
        "resolve YES. "
        "Check: (1) Is there any structural difference that could cause divergent resolution? "
        "(2) Are deadline differences material to resolution? "
        "(3) Are there any edge cases where the minor differences matter?"
    ),
    RelationType.INVERSE: (
        "Hypothesis: Market A and Market B are logical inverses — A resolves YES if and only if "
        "B resolves NO. "
        "Check: (1) Can both resolve YES simultaneously? "
        "(2) Can both resolve NO simultaneously? "
        "(3) Can either become AMBIGUOUS or voided independently, breaking the inverse? "
        "(4) Are deadlines and oracles compatible with a strict inverse relationship?"
    ),
    RelationType.MUTUALLY_EXCLUSIVE: (
        "Hypothesis: Market A and Market B are mutually exclusive outcomes of the same event — "
        "if A resolves YES, B must resolve NO. "
        "Check: (1) Can both resolve YES simultaneously? "
        "(2) Can both resolve NO — is that a valid outcome? "
        "(3) Does this exclusive partition hold under all realistic resolution scenarios?"
    ),
    RelationType.SUBSET: (
        "Hypothesis: Market A is a strict subset of Market B — A's YES condition is more restrictive. "
        "If A resolves YES, B must also resolve YES. "
        "Check: (1) Can A resolve YES while B resolves NO? "
        "(2) Is the subset direction correct, or is it actually the reverse? "
        "(3) Are deadlines compatible with the subset direction?"
    ),
    RelationType.SUPERSET: (
        "Hypothesis: Market A is a strict superset of Market B — B's YES condition is more restrictive. "
        "If B resolves YES, A must also resolve YES. "
        "Check: (1) Can B resolve YES while A resolves NO? "
        "(2) Is the superset direction correct?"
    ),
    RelationType.SAME_EVENT_DIFFERENT_DEADLINE: (
        "Hypothesis: Market A and Market B describe the same event but with different resolution deadlines. "
        "This creates legitimate asymmetry — this is NOT pure arbitrage. "
        "Check: (1) Could A resolve YES and B resolve NO due to the timing difference? "
        "(2) Is there any other structural difference beyond the deadline?"
    ),
    RelationType.SAME_EVENT_DIFFERENT_SOURCE: (
        "Hypothesis: Market A and Market B describe the same event but with different oracles or data sources. "
        "Oracle divergence is a real risk — this is NOT pure arbitrage. "
        "Check: (1) Could the oracles disagree on the same event? "
        "(2) Is there any other structural difference beyond the oracle or source?"
    ),
}

_DEFAULT_QUESTION = (
    "Determine whether Market A and Market B are semantically related and whether "
    "the proposed relationship is valid and tradeable."
)

# Tolerance for considering deadlines compatible (hours)
_DEADLINE_TOLERANCE_HOURS = 48


class RelationHypothesisGenerator:
    """
    Generates typed relation hypotheses by grouping markets across platforms.

    Unlike RelationProposalGenerator (which requires same frame/group_id),
    this pairs markets using proposition semantics — enabling cross-platform
    discovery of EQUIVALENT, INVERSE, MUTUALLY_EXCLUSIVE, SUBSET/SUPERSET,
    and SAME_EVENT_DIFFERENT_* relations.

    Markets already paired by the frame-based generator are still eligible when
    the semantic proposition looks stronger than the frame-level fallback.
    """

    _MAX_PAIRS_PER_GROUP = 50

    def generate(
        self,
        *,
        markets: list[RawMarket],
        propositions: dict[str, CompiledPropositionSchema],
        frame_ids: dict[str, str],
    ) -> list[RelationProposal]:
        """Return typed RelationProposal objects for semantic market pairs."""

        groups = _group_by_semantic_key(markets, propositions)
        proposals: list[RelationProposal] = []
        seen: set[tuple[str, str]] = set()

        for members in groups.values():
            if len(members) < 2:
                continue
            pairs = list(combinations(members, 2))
            if len(pairs) > self._MAX_PAIRS_PER_GROUP:
                pairs = pairs[: self._MAX_PAIRS_PER_GROUP]

            for market_a, market_b in pairs:
                pair_key = (
                    min(market_a.id, market_b.id),
                    max(market_a.id, market_b.id),
                )
                if pair_key in seen:
                    continue
                prop_a = propositions.get(market_a.id)
                prop_b = propositions.get(market_b.id)
                if prop_a is None or prop_b is None:
                    continue

                proposal = _hypothesize(market_a, market_b, prop_a, prop_b)
                if proposal is not None:
                    shared_frame_id = frame_ids.get(market_a.id) if _same_frame(market_a.id, market_b.id, frame_ids) else None
                    proposal = RelationProposal(
                        from_market_id=proposal.from_market_id,
                        to_market_id=proposal.to_market_id,
                        proposed_relation_type=proposal.proposed_relation_type,
                        confidence=proposal.confidence,
                        frame_id=shared_frame_id,
                        evidence={
                            **proposal.evidence,
                            "same_frame": shared_frame_id is not None,
                            "frame_id": shared_frame_id,
                        },
                        semantic_question=proposal.semantic_question,
                        hypothesis_source=proposal.hypothesis_source,
                    )
                    proposals.append(proposal)
                    seen.add(pair_key)

        return proposals


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hypothesize(
    market_a: RawMarket,
    market_b: RawMarket,
    prop_a: CompiledPropositionSchema,
    prop_b: CompiledPropositionSchema,
) -> RelationProposal | None:
    """Return a typed RelationProposal for the pair, or None if no hypothesis applies."""

    cross_platform = market_a.platform != market_b.platform

    same_subject = _norm(prop_a.canonical_subject) == _norm(prop_b.canonical_subject)
    same_predicate = _norm(prop_a.canonical_predicate) == _norm(prop_b.canonical_predicate)

    # No hypothesis without matching subject+predicate
    if not (same_subject and same_predicate):
        return None

    obj_a = _norm(prop_a.canonical_object or "")
    obj_b = _norm(prop_b.canonical_object or "")
    same_object = obj_a == obj_b
    both_have_object = bool(prop_a.canonical_object) and bool(prop_b.canonical_object)

    deadline_a = prop_a.temporal_deadline
    deadline_b = prop_b.temporal_deadline
    same_deadline = deadline_a == deadline_b
    compatible_deadline = _compatible_deadline(deadline_a, deadline_b)

    oracle_a = (prop_a.oracle_scope or "").strip().lower()
    oracle_b = (prop_b.oracle_scope or "").strip().lower()
    same_oracle = oracle_a == oracle_b
    compatible_oracle = not oracle_a or not oracle_b or oracle_a == oracle_b

    polarity_a = prop_a.polarity
    polarity_b = prop_b.polarity
    opposite_polarity = (
        polarity_a != polarity_b
        and polarity_a != "unknown"
        and polarity_b != "unknown"
    )

    partition_pair = prop_a.partition_hint and prop_b.partition_hint

    def _make(
        relation_type: RelationType,
        confidence: float,
        signals: list[str],
        counterexamples: list[str],
    ) -> RelationProposal:
        evidence: dict = {
            "hypothesis_source": "hypothesis_generator",
            "evidence_version": HYPOTHESIS_EVIDENCE_VERSION,
            "cross_platform": cross_platform,
            "platform_a": market_a.platform,
            "platform_b": market_b.platform,
            "deterministic_signals": signals,
        }
        question = HYPOTHESIS_QUESTIONS.get(relation_type, _DEFAULT_QUESTION)
        return RelationProposal(
            from_market_id=market_a.id,
            to_market_id=market_b.id,
            proposed_relation_type=relation_type,
            confidence=confidence,
            frame_id=None,
            evidence=evidence,
            semantic_question=question,
            hypothesis_source="hypothesis_generator",
        )

    base_signals: list[str] = ["same_canonical_subject_predicate"]
    if cross_platform:
        base_signals.append("cross_platform")
    if same_object:
        base_signals.append("same_canonical_object")
    if compatible_deadline:
        base_signals.append("compatible_deadline")
    if compatible_oracle:
        base_signals.append("compatible_oracle")

    # INVERSE: same subject/predicate, opposite polarity
    if opposite_polarity and compatible_deadline:
        signals = base_signals + ["opposite_polarity"]
        return _make(
            RelationType.INVERSE,
            confidence=0.78,
            signals=signals,
            counterexamples=[
                "Both markets become AMBIGUOUS/voided if the event is cancelled",
                "Oracle rounding causes both to resolve YES or both NO",
            ],
        )

    # SUBSET/SUPERSET (checked before EQUIVALENT): same object, different numeric threshold
    if same_object and prop_a.threshold_value and prop_b.threshold_value:
        try:
            val_a = float(prop_a.threshold_value)
            val_b = float(prop_b.threshold_value)
            if abs(val_a - val_b) > 1e-9:
                # Higher threshold value = stricter condition (e.g. "exceeds 6%" vs "exceeds 4%")
                rel = RelationType.SUBSET if val_a > val_b else RelationType.SUPERSET
                return _make(
                    rel,
                    confidence=0.65,
                    signals=base_signals + ["different_threshold"],
                    counterexamples=[
                        "Threshold direction is incorrect",
                        "Conditions are not strictly nested",
                    ],
                )
        except (ValueError, TypeError):
            pass

    # EQUIVALENT: same object, compatible deadline and oracle
    if same_object and compatible_deadline and compatible_oracle:
        if same_deadline and same_oracle:
            # Perfect structural match across platforms
            return _make(
                RelationType.EQUIVALENT,
                confidence=0.82 if cross_platform else 0.75,
                signals=base_signals,
                counterexamples=[
                    "Platform-specific resolution criteria differ in edge cases",
                    "Oracle divergence causes independent resolution",
                ],
            )
        if not same_deadline and same_oracle:
            return _make(
                RelationType.SAME_EVENT_DIFFERENT_DEADLINE,
                confidence=0.65,
                signals=base_signals,
                counterexamples=["Deadline difference is material to resolution"],
            )
        if same_deadline and not same_oracle:
            return _make(
                RelationType.SAME_EVENT_DIFFERENT_SOURCE,
                confidence=0.65,
                signals=base_signals + ["different_oracle"],
                counterexamples=["Oracles disagree on the same event"],
            )
        # compatible but neither same deadline nor same oracle
        return _make(
            RelationType.SAME_EVENT_DIFFERENT_DEADLINE,
            confidence=0.60,
            signals=base_signals,
            counterexamples=["Deadline or oracle divergence causes different resolution"],
        )

    # SAME_EVENT_DIFFERENT_DEADLINE: same object, compatible oracle, non-compatible deadline
    if same_object and compatible_oracle and deadline_a and deadline_b and not compatible_deadline:
        return _make(
            RelationType.SAME_EVENT_DIFFERENT_DEADLINE,
            confidence=0.58,
            signals=base_signals,
            counterexamples=["Deadline difference is material to resolution"],
        )

    # SAME_EVENT_DIFFERENT_SOURCE: same object, same deadline, incompatible oracle
    if same_object and same_deadline and not compatible_oracle:
        return _make(
            RelationType.SAME_EVENT_DIFFERENT_SOURCE,
            confidence=0.62,
            signals=base_signals + ["different_oracle"],
            counterexamples=["Oracles disagree on the same event"],
        )

    # MUTUALLY_EXCLUSIVE: different objects, partition_hint, compatible deadline
    if both_have_object and not same_object and partition_pair and compatible_deadline:
        return _make(
            RelationType.MUTUALLY_EXCLUSIVE,
            confidence=0.70,
            signals=base_signals + ["partition_hint_pair", "distinct_objects"],
            counterexamples=[
                "Both resolve YES if the event is ambiguous",
                "Both resolve NO if the underlying event does not occur",
            ],
        )

    return None


def _norm(text: str) -> str:
    return text.strip().lower() if text else ""


def _semantic_key(prop: CompiledPropositionSchema) -> str:
    subject = _norm(prop.canonical_subject)
    predicate = _norm(prop.canonical_predicate)
    if not subject or not predicate:
        return ""
    return f"{subject}\x00{predicate}"


def _group_by_semantic_key(
    markets: list[RawMarket],
    propositions: dict[str, CompiledPropositionSchema],
) -> dict[str, list[RawMarket]]:
    groups: dict[str, list[RawMarket]] = {}
    for market in markets:
        prop = propositions.get(market.id)
        if prop is None:
            continue
        key = _semantic_key(prop)
        if not key:
            continue
        groups.setdefault(key, []).append(market)
    return groups


def _same_frame(id_a: str, id_b: str, frame_ids: dict[str, str]) -> bool:
    fa = frame_ids.get(id_a)
    fb = frame_ids.get(id_b)
    return fa is not None and fb is not None and fa == fb


def _compatible_deadline(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    if a == b:
        return True
    try:
        dt_a = datetime.fromisoformat(a)
        dt_b = datetime.fromisoformat(b)
        if dt_a.tzinfo is None:
            dt_a = dt_a.replace(tzinfo=timezone.utc)
        if dt_b.tzinfo is None:
            dt_b = dt_b.replace(tzinfo=timezone.utc)
        return abs((dt_a - dt_b).total_seconds()) <= _DEADLINE_TOLERANCE_HOURS * 3600
    except (ValueError, TypeError):
        return False
