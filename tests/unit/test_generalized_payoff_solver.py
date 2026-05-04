from __future__ import annotations

from datetime import datetime, timezone

from parallax.db.models import RawMarket
from parallax.shared.schemas import (
    IdentityResolutionStatus,
    LogicalRelationSchema,
    LogicalRelationSetSchema,
    RelationEvidenceResponse,
    RelationType,
)
from parallax.solver.fixtures import build_fixture_library
from parallax.solver.service import GeneralizedPayoffSolver


def _market(mid: str, platform: str, yes_price: float) -> RawMarket:
    return RawMarket(
        id=mid,
        platform=platform,
        market_id=mid.split(":")[-1],
        title=mid,
        description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        deadline=datetime(2026, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )


def _evidence(
    a_id: str,
    b_id: str,
    relation_type: RelationType,
    *,
    member_market_ids: list[str] | None = None,
    set_key: str | None = None,
) -> RelationEvidenceResponse:
    return RelationEvidenceResponse(
        from_market_id=a_id,
        to_market_id=b_id,
        relation_type=relation_type,
        confidence=0.95,
        created_by="test",
        proof_status="verified",
        tradeable_relation=True,
        identity_status=IdentityResolutionStatus.VERIFIED,
        identity_version="identity-v3",
        member_market_ids=member_market_ids or [],
        set_key=set_key,
    )


def test_equivalent_pair_has_serializable_proof_and_positive_worst_case():
    solver = GeneralizedPayoffSolver(friction_bps=10)
    markets = [_market("pm:a", "pm", 0.40), _market("kalshi:b", "kalshi", 0.55)]
    relation = LogicalRelationSchema(
        from_market_id="pm:a",
        to_market_id="kalshi:b",
        relation_type=RelationType.EQUIVALENT,
        proof_status="verified",
        tradeable_relation=True,
        confidence=0.95,
        created_by="test",
    )

    result = solver.solve(
        markets=markets,
        relation_evidence=_evidence("pm:a", "kalshi:b", RelationType.EQUIVALENT),
        relations=[relation],
    )

    assert result is not None
    assert result.payoff_matrix.worst_case_payoff > 0
    assert result.scenario_matrix.valid_states
    assert result.proof_object.constraint_fingerprint == result.constraint_fingerprint
    assert result.proof_object.model_dump(mode="json")["solver_version"] == result.solver_version


def test_exhaustive_partition_uses_relation_set_as_source_of_truth():
    solver = GeneralizedPayoffSolver(friction_bps=10)
    markets = [
        _market("pm:a", "pm", 0.40),
        _market("pm:b", "pm", 0.36),
        _market("pm:c", "pm", 0.35),
    ]
    relation_set = LogicalRelationSetSchema(
        set_key="pm:a|pm:b|pm:c",
        member_market_ids=["pm:a", "pm:b", "pm:c"],
        relation_type=RelationType.EXHAUSTIVE_PARTITION,
        proof_status="verified",
        tradeable_relation=True,
        confidence=0.95,
        created_by="test",
    )

    result = solver.solve(
        markets=markets,
        relation_evidence=_evidence(
            "pm:a",
            "pm:b",
            RelationType.EXHAUSTIVE_PARTITION,
            member_market_ids=["pm:a", "pm:b", "pm:c"],
            set_key="pm:a|pm:b|pm:c",
        ),
        relation_sets=[relation_set],
    )

    assert result is not None
    assert len(result.payoff_matrix.legs) == 3
    assert result.proof_object.relation_set_keys == ["pm:a|pm:b|pm:c"]
    assert all(len(state.assignments) == 3 for state in result.scenario_matrix.valid_states)


def test_identity_gate_blocks_tradeable_candidate():
    solver = GeneralizedPayoffSolver(friction_bps=10)
    markets = [_market("pm:a", "pm", 0.40), _market("kalshi:b", "kalshi", 0.55)]
    relation = LogicalRelationSchema(
        from_market_id="pm:a",
        to_market_id="kalshi:b",
        relation_type=RelationType.EQUIVALENT,
        proof_status="verified",
        tradeable_relation=True,
        confidence=0.95,
        created_by="test",
    )
    evidence = _evidence("pm:a", "kalshi:b", RelationType.EQUIVALENT)
    evidence.identity_status = IdentityResolutionStatus.AMBIGUOUS

    result = solver.solve(
        markets=markets,
        relation_evidence=evidence,
        relations=[relation],
    )

    assert result is None


def test_fixture_library_contains_named_two_and_three_leg_cases():
    library = build_fixture_library()
    keys = {fixture.case_key for fixture in library.fixtures}
    assert "equivalent-2-leg" in keys
    assert "mutex-3-leg" in keys
