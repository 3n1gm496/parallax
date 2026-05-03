from unittest.mock import MagicMock

from parallax.candidates.evidence import load_relation_evidence


def test_load_relation_evidence_prefers_nary_relation_set():
    session = MagicMock()
    relation_set = MagicMock(
        set_key="pm:a|pm:b|pm:c",
        member_market_ids=["pm:a", "pm:b", "pm:c"],
        relation_type="exhaustive_partition",
        proof_status="verified",
        tradeable_relation=True,
        confidence=0.81,
        created_by="semantic_relation_analyzer",
        frame_id=None,
        evidence={
            "evidence_version": "relation-analysis-v1",
            "comparison_axes": ["yes_conditions"],
            "semantic_pair_reviews": [{"from_market_id": "pm:a", "to_market_id": "pm:b"}],
            "proof_status": "verified",
            "tradeable_relation": True,
            "member_market_ids": ["pm:a", "pm:b", "pm:c"],
        },
    )
    session.query.return_value.filter.return_value.first.return_value = relation_set
    session.query.return_value.filter.return_value.all.return_value = []

    result = load_relation_evidence(session, ["pm:a", "pm:b", "pm:c"])

    assert result is not None
    assert result.relation_type.value == "exhaustive_partition"
    assert result.set_key == "pm:a|pm:b|pm:c"
    assert result.member_market_ids == ["pm:a", "pm:b", "pm:c"]
    assert result.tradeable_relation is True
