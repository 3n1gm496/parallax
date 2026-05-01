from __future__ import annotations

from pydantic import BaseModel

from parallax.shared.schemas import Counterexample, RelationType


class RelationClassification(BaseModel):
    relation_type: RelationType
    confidence: float
    reasoning: str
    breaking_scenarios: list[Counterexample]
    is_confirmed: bool
