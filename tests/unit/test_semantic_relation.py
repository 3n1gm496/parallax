from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import ContractSchema, Counterexample, RelationType


def _contract(yes=("X happens",), no=("X does not happen",), confidence=0.85):
    return ContractSchema(
        yes_conditions=list(yes),
        no_conditions=list(no),
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=confidence,
    )


def _tool_response(payload: RelationClassification | dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = payload.model_dump() if isinstance(payload, RelationClassification) else payload
    response = MagicMock()
    response.content = [block]
    return response


class TestSemanticRelationAnalyzer:
    def _make_analyzer(self):
        from parallax.detection.semantic import SemanticRelationAnalyzer

        client = MagicMock()
        return SemanticRelationAnalyzer(client), client

    @pytest.mark.anyio
    async def test_equivalent_confirmed_when_no_breaking_scenario(self):
        analyzer, client = self._make_analyzer()
        client.messages.create = AsyncMock(
            return_value=_tool_response(
                RelationClassification(
                    relation_type=RelationType.EQUIVALENT,
                    confidence=0.92,
                    reasoning="Both resolve YES/NO identically.",
                    comparison_axes=["yes_conditions", "no_conditions", "deadline"],
                    breaking_scenarios=[],
                    is_confirmed=True,
                )
            )
        )
        result = await analyzer.classify(_contract(), _contract())
        assert result is not None
        assert result.relation_type == RelationType.EQUIVALENT

    @pytest.mark.anyio
    async def test_invalid_confirmed_breaking_scenario_is_rejected(self):
        analyzer, client = self._make_analyzer()
        client.messages.create = AsyncMock(
            return_value=_tool_response(
                RelationClassification(
                    relation_type=RelationType.EQUIVALENT,
                    confidence=0.6,
                    reasoning="Invalid.",
                    comparison_axes=["deadline"],
                    breaking_scenarios=[
                        Counterexample(
                            scenario_description="Deadline drift",
                            resolution_a="YES",
                            resolution_b="NO",
                            why_different="Cutoff mismatch",
                        )
                    ],
                    is_confirmed=True,
                )
            )
        )
        assert await analyzer.classify(_contract(), _contract()) is None

