from __future__ import annotations

from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import RelationType


def test_relation_classification_schema():
    rc = RelationClassification(
        relation_type=RelationType.EQUIVALENT,
        confidence=0.9,
        reasoning="Both markets resolve YES when X happens before Dec 31.",
        breaking_scenarios=[],
        is_confirmed=True,
    )
    assert rc.relation_type == RelationType.EQUIVALENT
    assert rc.is_confirmed is True
