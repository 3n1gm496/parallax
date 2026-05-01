from __future__ import annotations

from sqlalchemy.orm import Session

from parallax.db.models import CompiledContract, RawMarket
from parallax.detection.stage1 import Stage1ConstraintDetector, RelationSpec
from parallax.detection.stage2 import Stage2LLMDetector
from parallax.graph.repository import GraphRepository
from parallax.shared.schemas import ContractSchema, RelationType

_STAGE2_TYPES = {RelationType.EQUIVALENT, RelationType.DUPLICATE, RelationType.SUBSET, RelationType.SUPERSET}
_MIN_STAGE2_CONFIDENCE = 0.7


class ProverService:
    """Orchestrate relation detection: Stage 1 constraint rules, Stage 2 LLM confirmation."""

    _CREATED_BY_STAGE1 = "stage1_constraint"
    _CREATED_BY_STAGE2 = "stage2_llm"

    def __init__(
        self,
        session: Session,
        graph_repo: GraphRepository,
        stage2_classifier: Stage2LLMDetector | None = None,
    ) -> None:
        self._session = session
        self._graph_repo = graph_repo
        self._detector = Stage1ConstraintDetector()
        self._stage2 = stage2_classifier

    async def run(self, markets: list[RawMarket]) -> int:
        specs = self._detector.detect(markets)
        added = 0
        for spec in specs:
            if self._graph_repo.relation_exists(
                spec.from_market_id, spec.to_market_id, spec.relation_type
            ):
                continue

            if spec.relation_type in _STAGE2_TYPES:
                stored = await self._run_stage2(spec)
            else:
                stored = self._store_relation(spec, created_by=self._CREATED_BY_STAGE1)

            if stored:
                added += 1
        return added

    async def _run_stage2(self, spec: RelationSpec) -> bool:
        if self._stage2 is None:
            return False
        contract_a = self._get_contract(spec.from_market_id)
        contract_b = self._get_contract(spec.to_market_id)
        if contract_a is None or contract_b is None:
            return False

        classification = await self._stage2.classify(contract_a, contract_b)
        if classification is None:
            return False
        if not classification.is_confirmed:
            return False
        if classification.confidence < _MIN_STAGE2_CONFIDENCE:
            return False

        evidence = {
            **spec.evidence,
            "stage2_reasoning": classification.reasoning,
            "stage2_confidence": classification.confidence,
            "breaking_scenarios": len(classification.breaking_scenarios),
        }
        self._graph_repo.add_relation(
            from_market_id=spec.from_market_id,
            to_market_id=spec.to_market_id,
            relation_type=classification.relation_type,
            confidence=classification.confidence,
            evidence=evidence,
            created_by=self._CREATED_BY_STAGE2,
        )
        return True

    def _store_relation(self, spec: RelationSpec, created_by: str) -> bool:
        self._graph_repo.add_relation(
            from_market_id=spec.from_market_id,
            to_market_id=spec.to_market_id,
            relation_type=spec.relation_type,
            confidence=spec.confidence,
            evidence=spec.evidence,
            created_by=created_by,
        )
        return True

    def _get_contract(self, market_id: str) -> ContractSchema | None:
        row = (
            self._session.query(CompiledContract)
            .filter_by(raw_market_id=market_id)
            .order_by(CompiledContract.compiled_at.desc())
            .first()
        )
        return ContractSchema.model_validate(row.contract_json) if row else None
