from __future__ import annotations

import json

import anthropic

from parallax.config import settings
from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import ContractSchema, RelationType

_MODEL = "claude-sonnet-4-6"
_COUNTEREXAMPLE_REQUIRED_TYPES = {
    RelationType.EQUIVALENT,
    RelationType.DUPLICATE,
    RelationType.SUBSET,
    RelationType.SUPERSET,
}

_COMPARISON_SYSTEM = """You are a prediction-market semantic analyst.

Given two compiled prediction market contracts, determine whether they are semantically related
and classify their relationship. You must:

1. Compare yes_conditions, no_conditions, exclusions, and ambiguity_terms for both markets.
2. Classify the relationship as one of: equivalent, duplicate, subset, superset, mutually_exclusive, same_event_family, same_event_independent, related_but_not_tradeable, unrelated.
3. Explicitly state the comparison axes you used in `comparison_axes`. At minimum, include any
   combination of yes_conditions, no_conditions, exclusions, ambiguity_terms, deadline, oracle,
   and source when those fields matter to the decision.
4. For equivalent or subset claims: generate at least one concrete counterexample — a real-world
   scenario where the two markets resolve differently. If you cannot construct a valid counterexample
   after careful analysis, set is_confirmed=True and breaking_scenarios=[].
5. Set is_confirmed=False if you found any breaking scenario.
6. Set tradeable_relation=True only when the logical relationship is strong enough to support arbitrage-style pricing checks after fees and execution.
7. Set proof_status to one of verified, rejected, needs_review.

Be conservative: prefer 'unrelated' over 'equivalent' when uncertain."""

_TOOL = {
    "name": "classify_relation",
    "description": "Output the semantic relation classification between two prediction market contracts.",
    "input_schema": RelationClassification.model_json_schema(),
}


class SemanticRelationAnalyzer:
    """Classify semantic relations between compiled contracts using Anthropic."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        min_contract_confidence: float | None = None,
    ) -> None:
        self._client = client
        self._min_contract_confidence = (
            settings.compiler_min_confidence if min_contract_confidence is None else min_contract_confidence
        )

    async def classify(
        self,
        contract_a: ContractSchema,
        contract_b: ContractSchema,
        *,
        proposed_relation: RelationType | None = None,
    ) -> RelationClassification | None:
        if (
            contract_a.compiler_confidence < self._min_contract_confidence
            or contract_b.compiler_confidence < self._min_contract_confidence
        ):
            return None

        proposal_text = f"\n\n## Proposed relation\n{proposed_relation.value}" if proposed_relation is not None else ""
        user_content = (
            f"## Market A Contract\n{json.dumps(contract_a.model_dump(), indent=2)}\n\n"
            f"## Market B Contract\n{json.dumps(contract_b.model_dump(), indent=2)}"
            f"{proposal_text}"
        )

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=[{"type": "text", "text": _COMPARISON_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_content}],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "classify_relation"},
        )
        tool_block = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_block is None:
            return None

        classification = RelationClassification.model_validate(tool_block.input)
        if not self._is_valid_classification(classification):
            return None
        return classification

    @staticmethod
    def _is_valid_classification(classification: RelationClassification) -> bool:
        requires_counterexample = classification.relation_type in _COUNTEREXAMPLE_REQUIRED_TYPES
        has_breaking_scenarios = bool(classification.breaking_scenarios)
        has_axes = bool(classification.comparison_axes)

        if classification.is_confirmed and has_breaking_scenarios:
            return False
        if requires_counterexample and not classification.is_confirmed and not has_breaking_scenarios:
            return False
        if classification.relation_type not in {
            RelationType.MUTUALLY_EXCLUSIVE,
            RelationType.SAME_EVENT_FAMILY,
            RelationType.SAME_EVENT_INDEPENDENT,
            RelationType.RELATED_BUT_NOT_TRADEABLE,
        } and not has_axes:
            return False
        return True
