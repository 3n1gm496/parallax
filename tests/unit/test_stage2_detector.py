from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import RelationType, ContractSchema, Counterexample


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


def _contract(yes=("X happens",), no=("X does not happen",), confidence=0.85):
    return ContractSchema(
        yes_conditions=list(yes),
        no_conditions=list(no),
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=confidence,
    )


def _tool_response(rc: RelationClassification) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = rc.model_dump()
    resp = MagicMock()
    resp.content = [block]
    return resp


class TestStage2LLMDetector:
    def _make_detector(self):
        from parallax.detection.stage2 import Stage2LLMDetector
        client = MagicMock()
        return Stage2LLMDetector(client), client

    @pytest.mark.anyio
    async def test_equivalent_confirmed_when_no_breaking_scenario(self):
        detector, client = self._make_detector()
        rc = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.92,
            reasoning="Both resolve YES/NO identically.",
            breaking_scenarios=[],
            is_confirmed=True,
        )
        client.messages.create = AsyncMock(return_value=_tool_response(rc))
        a, b = _contract(), _contract()
        result = await detector.classify(a, b)
        assert result.relation_type == RelationType.EQUIVALENT
        assert result.is_confirmed is True
        assert client.messages.create.call_count >= 1

    @pytest.mark.anyio
    async def test_equivalent_not_confirmed_when_breaking_scenario_found(self):
        detector, client = self._make_detector()
        breaking = Counterexample(
            scenario_description="X happens after deadline",
            resolution_a="NO",
            resolution_b="YES",
            why_different="Different deadline cutoffs",
        )
        rc = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.4,
            reasoning="Deadlines differ.",
            breaking_scenarios=[breaking],
            is_confirmed=False,
        )
        client.messages.create = AsyncMock(return_value=_tool_response(rc))
        result = await detector.classify(_contract(), _contract())
        assert result.is_confirmed is False
        assert len(result.breaking_scenarios) == 1

    @pytest.mark.anyio
    async def test_mutually_exclusive_skips_counterexample_requirement(self):
        detector, client = self._make_detector()
        rc = RelationClassification(
            relation_type=RelationType.MUTUALLY_EXCLUSIVE,
            confidence=0.95,
            reasoning="Outcomes are structurally mutually exclusive.",
            breaking_scenarios=[],
            is_confirmed=True,
        )
        client.messages.create = AsyncMock(return_value=_tool_response(rc))
        result = await detector.classify(_contract(), _contract())
        assert result.relation_type == RelationType.MUTUALLY_EXCLUSIVE
        assert result.is_confirmed is True

    @pytest.mark.anyio
    async def test_low_confidence_contract_skipped(self):
        detector, client = self._make_detector()
        client.messages.create = AsyncMock()
        low = _contract(confidence=0.2)
        result = await detector.classify(low, _contract())
        client.messages.create.assert_not_called()
        assert result is None
