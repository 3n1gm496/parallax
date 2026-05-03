from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator

from parallax.shared.schemas import Counterexample, Probability, RelationType, _coerce_json_list


class RelationClassification(BaseModel):
    relation_type: RelationType
    confidence: Probability
    reasoning: str
    comparison_axes: list[str]
    breaking_scenarios: list[Counterexample]
    is_confirmed: bool
    tradeable_relation: bool = False
    proof_status: str = "verified"

    @field_validator("comparison_axes", "breaking_scenarios", mode="before")
    @classmethod
    def _normalize_list_like_fields(cls, value: Any) -> Any:
        return _coerce_json_list(value)
