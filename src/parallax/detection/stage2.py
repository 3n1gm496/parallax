from __future__ import annotations

import json

import anthropic

from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import ContractSchema

_MODEL = "claude-sonnet-4-6"
_MIN_CONTRACT_CONFIDENCE = 0.5

_COMPARISON_SYSTEM = """You are a prediction-market semantic analyst.

Given two compiled prediction market contracts, determine whether they are semantically related
and classify their relationship. You must:

1. Compare yes_conditions, no_conditions, exclusions, and ambiguity_terms for both markets.
2. Classify the relationship as one of: equivalent, duplicate, subset, superset, mutually_exclusive, unrelated.
3. For equivalent or subset claims: generate at least one concrete counterexample — a real-world
   scenario where the two markets resolve differently. If you cannot construct a valid counterexample
   after careful analysis, set is_confirmed=True and breaking_scenarios=[].
4. Set is_confirmed=False if you found any breaking scenario.

Be conservative: prefer 'unrelated' over 'equivalent' when uncertain."""

_TOOL = {
    "name": "classify_relation",
    "description": "Output the semantic relation classification between two prediction market contracts.",
    "input_schema": RelationClassification.model_json_schema(),
}


class Stage2LLMDetector:
    """Classify the semantic relation between two compiled contracts using an LLM."""

    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def classify(
        self,
        contract_a: ContractSchema,
        contract_b: ContractSchema,
    ) -> RelationClassification | None:
        if (
            contract_a.compiler_confidence < _MIN_CONTRACT_CONFIDENCE
            or contract_b.compiler_confidence < _MIN_CONTRACT_CONFIDENCE
        ):
            return None

        user_content = (
            f"## Market A Contract\n{json.dumps(contract_a.model_dump(), indent=2)}\n\n"
            f"## Market B Contract\n{json.dumps(contract_b.model_dump(), indent=2)}"
        )

        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": _COMPARISON_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "classify_relation"},
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        return RelationClassification.model_validate(tool_block.input)
