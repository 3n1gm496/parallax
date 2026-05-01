# PARALLAX Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the detection pipeline by activating the Event Contract Compiler, implementing Stage 2 LLM relation detection, and adding Kalshi as a second data source for cross-platform arbitrage detection.

**Architecture:** The pipeline gains two new steps — compile markets into structured contracts (stored in `CompiledContract`), then run Stage 2 LLM comparison on Stage 1 candidates to confirm or reject EQUIVALENT/SUBSET relations. Kalshi is added as a second `PlatformAdapter` alongside Polymarket. Integration tests validate the full pipeline end-to-end against a live test Postgres container.

**Tech Stack:** Python 3.13 · SQLAlchemy 2.0 (legacy query style) · Anthropic Python SDK (`messages.create` + `tool_use`) · httpx async · FastAPI · pytest + anyio · Docker (postgres_test on port 5433)

**Branch:** `feature/parallax-slice-2`
**Worktree:** `.worktrees/slice-2`

```bash
# Create worktree before starting
git worktree add .worktrees/slice-2 -b feature/parallax-slice-2
```

All commands below assume CWD is `.worktrees/slice-2`.

---

## ADR References

| ADR | Decision |
|-----|----------|
| 0002 | Anthropic API (Claude Sonnet 4.6), tool_use for structured output, prompt caching |
| 0003 | Kalshi adapter in Slice 2 behind `PlatformAdapter` interface |
| 0005 | Hybrid Stage 1 (constraint rules) + Stage 2 (LLM contract comparison + counterexample) |
| 0006 | worst_case_payoff stored post-friction; total_cost = capital deployed (not collateral) |

---

## File Structure Map

### New files

```
src/parallax/
├── compiler/
│   └── service.py                    # CompilerService: compile market → store CompiledContract
├── detection/
│   ├── stage2.py                     # Stage2LLMDetector: contract compare + counterexample
│   └── schemas.py                    # RelationClassification (tool output schema)
└── ingestion/
    └── kalshi_adapter.py             # KalshiAdapter implementing PlatformAdapter

tests/
├── unit/
│   ├── test_compiler_service.py      # CompilerService unit tests
│   ├── test_stage2_detector.py       # Stage2LLMDetector unit tests
│   └── test_kalshi_adapter.py        # KalshiAdapter unit tests
└── integration/
    ├── conftest.py                   # DB fixtures using postgres_test
    └── test_pipeline_integration.py  # End-to-end pipeline test against live Postgres
```

### Modified files

```
src/parallax/
├── prover/service.py                 # Add Stage 2 pass after Stage 1
├── pipeline/runner.py                # Add compile step + update RunSummary counts
├── config.py                        # Add kalshi_api_key, compiler_min_confidence
└── shared/schemas.py                # Add RelationClassification schema
```

---

## Phase 1 — Contract Compiler Pipeline

### Task 1: CompilerService

Wire `AnthropicCompilerProvider` into a service that compiles a `RawMarket` and persists the result as a `CompiledContract`. Skip markets compiled in the last 24 hours to avoid re-compiling stable markets.

**Files:**
- Create: `src/parallax/compiler/service.py`
- Create: `tests/unit/test_compiler_service.py`
- Modify: `src/parallax/pipeline/runner.py` (add compile step)
- Modify: `src/parallax/config.py` (add `compiler_min_confidence`)

---

- [ ] **Step 1.1: Write failing tests**

```python
# tests/unit/test_compiler_service.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
import pytest
from parallax.compiler.service import CompilerService
from parallax.shared.schemas import ContractSchema


def _contract() -> ContractSchema:
    return ContractSchema(
        yes_conditions=["X happens"],
        no_conditions=["X does not happen"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.85,
    )


def _market(mid: str = "pm:a") -> MagicMock:
    m = MagicMock()
    m.id = mid
    m.platform = "polymarket"
    m.title = "Will X happen?"
    m.description = "Resolves YES if X."
    m.resolution_criteria = "Resolves YES if X; NO otherwise."
    m.outcomes = ["Yes", "No"]
    m.outcome_prices = [0.6, 0.4]
    m.deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
    m.is_closed = False
    m.raw_payload = {}
    return m


class TestCompilerService:
    def _make_svc(self, existing_contract=None):
        session = MagicMock()
        provider = MagicMock()
        provider.version = "anthropic-sonnet-4-6-v1"
        svc = CompilerService(session, provider)
        svc._get_recent_contract = MagicMock(return_value=existing_contract)
        return svc, session, provider

    @pytest.mark.anyio
    async def test_compile_new_market_stores_contract(self):
        svc, session, provider = self._make_svc(existing_contract=None)
        contract = _contract()
        provider.compile = AsyncMock(return_value=contract)

        result = await svc.compile(_market())

        provider.compile.assert_called_once()
        session.add.assert_called_once()
        assert result == contract

    @pytest.mark.anyio
    async def test_compile_skips_recently_compiled(self):
        existing = MagicMock()
        existing.contract_json = _contract().model_dump()
        svc, session, provider = self._make_svc(existing_contract=existing)
        provider.compile = AsyncMock()

        result = await svc.compile(_market())

        provider.compile.assert_not_called()
        session.add.assert_not_called()
        assert result.yes_conditions == ["X happens"]

    @pytest.mark.anyio
    async def test_compile_low_confidence_still_stores(self):
        svc, session, provider = self._make_svc(existing_contract=None)
        low_conf = _contract()
        low_conf = low_conf.model_copy(update={"compiler_confidence": 0.3})
        provider.compile = AsyncMock(return_value=low_conf)

        await svc.compile(_market())

        session.add.assert_called_once()

    def test_get_recent_contract_returns_none_for_new_market(self):
        session = MagicMock()
        provider = MagicMock()
        session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
        svc = CompilerService(session, provider)
        result = svc._get_recent_contract("pm:a")
        assert result is None
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_compiler_service.py -v
```
Expected: `ModuleNotFoundError` or `ImportError: cannot import name 'CompilerService'`

- [ ] **Step 1.3: Implement CompilerService**

```python
# src/parallax/compiler/service.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from parallax.compiler.provider import CompilerProvider
from parallax.db.models import CompiledContract
from parallax.shared.schemas import ContractSchema, RawMarketData

_RECOMPILE_AFTER_HOURS = 24


class CompilerService:
    """Compile a RawMarket into a ContractSchema and persist as CompiledContract."""

    def __init__(self, session: Session, provider: CompilerProvider) -> None:
        self._session = session
        self._provider = provider

    async def compile(self, market) -> ContractSchema:
        existing = self._get_recent_contract(market.id)
        if existing is not None:
            return ContractSchema.model_validate(existing.contract_json)

        market_data = RawMarketData(
            platform=market.platform,
            market_id=market.market_id if hasattr(market, "market_id") else market.id.split(":")[-1],
            title=market.title,
            description=market.description,
            resolution_criteria=market.resolution_criteria,
            outcomes=list(market.outcomes) if market.outcomes else [],
            outcome_prices=list(market.outcome_prices) if market.outcome_prices else [],
            deadline=market.deadline,
            is_closed=market.is_closed,
            raw_payload=dict(market.raw_payload) if market.raw_payload else {},
        )
        contract = await self._provider.compile(market_data)

        row = CompiledContract(
            id=uuid.uuid4(),
            raw_market_id=market.id,
            contract_json=contract.model_dump(),
            compiler_version=self._provider.version,
        )
        self._session.add(row)
        self._session.flush()
        return contract

    def _get_recent_contract(self, market_id: str) -> CompiledContract | None:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=_RECOMPILE_AFTER_HOURS)
        return (
            self._session.query(CompiledContract)
            .filter_by(raw_market_id=market_id)
            .order_by(CompiledContract.compiled_at.desc())
            .first()
        )
```

- [ ] **Step 1.4: Add `compiler_min_confidence` to config**

```python
# src/parallax/config.py — add field to Settings
compiler_min_confidence: float = 0.5
```

- [ ] **Step 1.5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_compiler_service.py -v
```
Expected: 4 passed

- [ ] **Step 1.6: Wire compile step into PipelineRunner**

In `src/parallax/pipeline/runner.py`, import and call `CompilerService` after ingestion. Return `contracts_compiled` count in `RunSummary`.

```python
# Add to imports
from parallax.compiler.service import CompilerService
from parallax.compiler.anthropic_provider import AnthropicCompilerProvider

# Add inside run_once(), after open_markets is fetched, before prover:
provider = AnthropicCompilerProvider()
compiler_svc = CompilerService(session, provider)
contracts_compiled = 0
for market in open_markets:
    try:
        await compiler_svc.compile(market)
        contracts_compiled += 1
    except Exception as exc:
        log.warning("pipeline: compile failed for %s: %s", market.id, exc)
        errors.append(f"compile:{market.id}:{exc}")
audit_svc.record("pipeline.compiler.complete", "pipeline", "global", {"compiled": contracts_compiled})
```

Note: `run_once` must become `async def run_once`. Update `PipelineRunner.__init__` to accept an `asyncio` event loop call site. Add `import asyncio` and call `asyncio.run(runner.run_once())` in `__main__`.

```python
# Update __main__ block:
if __name__ == "__main__":
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    from parallax.db.session import session_scope
    runner = PipelineRunner(session_scope)
    summary = asyncio.run(runner.run_once())
    print(summary)
```

- [ ] **Step 1.7: Update test_pipeline_runner.py for async run_once**

```python
# tests/unit/test_pipeline_runner.py
# Change test signatures to async + anyio marker

@pytest.mark.anyio
async def test_run_once_returns_summary(self):
    ...
    summary = await runner.run_once()
    ...

@pytest.mark.anyio
async def test_run_once_captures_errors(self):
    ...
    summary = await runner.run_once()
    ...
```

Add `pytest` import and `from unittest.mock import AsyncMock`. Mock `compiler_svc.compile` as `AsyncMock`.

Also patch `CompilerService` in each test:
```python
patch("parallax.pipeline.runner.CompilerService") as MockCompiler, \
patch("parallax.pipeline.runner.AnthropicCompilerProvider"), \
```
And set `MockCompiler.return_value.compile = AsyncMock(return_value=MagicMock())`.

- [ ] **Step 1.8: Run full unit test suite**

```bash
uv run pytest tests/unit/ -v
```
Expected: all pass (count increases by 4)

- [ ] **Step 1.9: Run lint**

```bash
uv run ruff check src/ tests/
```
Expected: All checks passed!

- [ ] **Step 1.10: Commit**

```bash
git add src/parallax/compiler/service.py src/parallax/config.py \
        src/parallax/pipeline/runner.py \
        tests/unit/test_compiler_service.py tests/unit/test_pipeline_runner.py
git commit -m "feat(compiler): CompilerService persists CompiledContract; pipeline async compile step"
```

---

### Task 2: RelationClassification schema and Stage 2 prompt

Define the output schema for the Stage 2 LLM comparison call and the comparison prompt.

**Files:**
- Create: `src/parallax/detection/schemas.py`
- Modify: `src/parallax/shared/schemas.py` (export `RelationClassification`)

---

- [ ] **Step 2.1: Write failing test**

```python
# tests/unit/test_stage2_detector.py — add at top
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
```

- [ ] **Step 2.2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_stage2_detector.py::test_relation_classification_schema -v
```

- [ ] **Step 2.3: Implement RelationClassification schema**

```python
# src/parallax/detection/schemas.py
from __future__ import annotations
from pydantic import BaseModel
from parallax.shared.schemas import Counterexample, RelationType


class RelationClassification(BaseModel):
    relation_type: RelationType
    confidence: float           # 0.0–1.0
    reasoning: str              # plain-language explanation
    breaking_scenarios: list[Counterexample]  # scenarios where markets diverge
    is_confirmed: bool          # True only when 2+ counterexample attempts found no break
```

- [ ] **Step 2.4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_stage2_detector.py::test_relation_classification_schema -v
```

- [ ] **Step 2.5: Commit**

```bash
git add src/parallax/detection/schemas.py tests/unit/test_stage2_detector.py
git commit -m "feat(detection): RelationClassification schema for Stage 2 output"
```

---

## Phase 2 — Stage 2 LLM Detector

### Task 3: Stage2LLMDetector

Compare two compiled contracts using an LLM tool call. Produce a `RelationClassification`. Require mandatory counterexample generation for EQUIVALENT and SUBSET claims: attempt two independent counterexample prompts; only emit `is_confirmed=True` if both attempts fail to find a breaking scenario.

**Files:**
- Create: `src/parallax/detection/stage2.py`
- Modify: `tests/unit/test_stage2_detector.py`

---

- [ ] **Step 3.1: Write failing tests**

```python
# tests/unit/test_stage2_detector.py — extend file
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parallax.detection.stage2 import Stage2LLMDetector
from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import (
    ContractSchema, RelationType, Counterexample
)


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
        client = MagicMock()
        return Stage2LLMDetector(client), client

    @pytest.mark.anyio
    async def test_equivalent_confirmed_when_no_breaking_scenario(self):
        """When LLM finds no breaking scenario in 2 attempts, is_confirmed=True."""
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
        """When LLM finds a breaking scenario, is_confirmed=False."""
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
        """MUTUALLY_EXCLUSIVE relations don't require counterexample generation."""
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
        """Skip comparison if either contract has confidence below threshold."""
        detector, client = self._make_detector()
        client.messages.create = AsyncMock()
        low = _contract(confidence=0.2)
        result = await detector.classify(low, _contract())
        client.messages.create.assert_not_called()
        assert result is None
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_stage2_detector.py -v
```
Expected: `ImportError: cannot import name 'Stage2LLMDetector'` (except the schema test, which passes)

- [ ] **Step 3.3: Implement Stage2LLMDetector**

```python
# src/parallax/detection/stage2.py
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
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_stage2_detector.py -v
```
Expected: 5 passed

- [ ] **Step 3.5: Run lint**

```bash
uv run ruff check src/ tests/
```

- [ ] **Step 3.6: Commit**

```bash
git add src/parallax/detection/stage2.py tests/unit/test_stage2_detector.py
git commit -m "feat(detection): Stage2LLMDetector — contract comparison with counterexample generation"
```

---

### Task 4: Wire Stage 2 into ProverService

`ProverService` currently only runs Stage 1 and stores results immediately. Extend it so that:
1. Stage 1 MUTUALLY_EXCLUSIVE results are stored directly (no Stage 2 needed — structural rule).
2. Stage 1 EQUIVALENT/SUBSET candidates are passed to Stage 2 before storing.
3. Only Stage 2-confirmed relations with `confidence >= 0.7` are stored.

**Files:**
- Modify: `src/parallax/prover/service.py`
- Modify: `tests/unit/test_prover_service.py`

---

- [ ] **Step 4.1: Write failing tests**

```python
# tests/unit/test_prover_service.py — add new test class
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parallax.detection.schemas import RelationClassification
from parallax.shared.schemas import RelationType


class TestProverServiceStage2:
    def _make_prover(self, stage1_specs, classifier_result):
        from parallax.prover.service import ProverService
        session = MagicMock()
        graph_repo = MagicMock()
        graph_repo.relation_exists.return_value = False
        detector = MagicMock()
        detector.detect.return_value = stage1_specs
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=classifier_result)
        svc = ProverService(session, graph_repo, stage2_classifier=classifier)
        svc._detector = detector
        return svc, graph_repo

    @pytest.mark.anyio
    async def test_mutually_exclusive_stored_without_stage2(self):
        from parallax.detection.stage1 import RelationSpec
        spec = RelationSpec(
            from_market_id="pm:a",
            to_market_id="pm:b",
            relation_type=RelationType.MUTUALLY_EXCLUSIVE,
            confidence=0.95,
            evidence={"rule": "intra_group"},
        )
        svc, graph_repo = self._make_prover([spec], classifier_result=None)
        count = await svc.run([])
        graph_repo.add_relation.assert_called_once()
        # Stage 2 classifier not called for ME
        svc._stage2.classify.assert_not_called()

    @pytest.mark.anyio
    async def test_equivalent_requires_stage2_confirmation(self):
        from parallax.detection.stage1 import RelationSpec
        spec = RelationSpec(
            from_market_id="pm:a",
            to_market_id="kalshi:b",
            relation_type=RelationType.EQUIVALENT,
            confidence=0.6,
            evidence={"rule": "cross_platform_price_inversion"},
        )
        confirmed = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.88,
            reasoning="Both resolve YES when X happens.",
            breaking_scenarios=[],
            is_confirmed=True,
        )
        svc, graph_repo = self._make_prover([spec], classifier_result=confirmed)

        # Need contracts in DB — mock _get_contracts
        from parallax.shared.schemas import ContractSchema
        contract = ContractSchema(
            yes_conditions=["X happens"],
            no_conditions=["X does not happen"],
            exclusions=[], ambiguity_terms=[], counterexamples=[],
            compiler_confidence=0.85,
        )
        svc._get_contract = MagicMock(return_value=contract)

        count = await svc.run([])
        svc._stage2.classify.assert_called_once()
        graph_repo.add_relation.assert_called_once()

    @pytest.mark.anyio
    async def test_equivalent_not_stored_when_stage2_unconfirmed(self):
        from parallax.detection.stage1 import RelationSpec
        from parallax.shared.schemas import Counterexample
        spec = RelationSpec(
            from_market_id="pm:a",
            to_market_id="kalshi:b",
            relation_type=RelationType.EQUIVALENT,
            confidence=0.6,
            evidence={"rule": "cross_platform_price_inversion"},
        )
        unconfirmed = RelationClassification(
            relation_type=RelationType.EQUIVALENT,
            confidence=0.4,
            reasoning="Deadlines differ.",
            breaking_scenarios=[Counterexample(
                scenario_description="X happens after cutoff",
                resolution_a="NO", resolution_b="YES",
                why_different="Different deadlines",
            )],
            is_confirmed=False,
        )
        svc, graph_repo = self._make_prover([spec], classifier_result=unconfirmed)
        from parallax.shared.schemas import ContractSchema
        contract = ContractSchema(
            yes_conditions=["X"], no_conditions=["not X"],
            exclusions=[], ambiguity_terms=[], counterexamples=[],
            compiler_confidence=0.85,
        )
        svc._get_contract = MagicMock(return_value=contract)
        count = await svc.run([])
        graph_repo.add_relation.assert_not_called()
        assert count == 0
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_prover_service.py::TestProverServiceStage2 -v
```

- [ ] **Step 4.3: Update ProverService**

```python
# src/parallax/prover/service.py
from __future__ import annotations
from sqlalchemy.orm import Session
from parallax.db.models import RawMarket, CompiledContract
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
```

- [ ] **Step 4.4: Update PipelineRunner to instantiate Stage2LLMDetector**

```python
# In run_once(), after compiler step, before prover:
import anthropic as anthropic_sdk
stage2 = Stage2LLMDetector(anthropic_sdk.AsyncAnthropic(api_key=settings.anthropic_api_key))
prover = ProverService(session, graph_repo, stage2_classifier=stage2)
relations_detected = await prover.run(open_markets)
```

Add to imports: `from parallax.detection.stage2 import Stage2LLMDetector`

- [ ] **Step 4.5: Update existing ProverService tests for async**

The existing tests in `test_prover_service.py` call `prover.run()` synchronously. Since `run` is now `async`, add `@pytest.mark.anyio` and `await`:

```python
@pytest.mark.anyio
async def test_no_markets_adds_nothing(self):
    ...
    count = await svc.run([])
    ...
```

Add `stage2_classifier=None` to all `ProverService(session, graph_repo)` calls so Stage 2 is bypassed in existing tests.

- [ ] **Step 4.6: Run full test suite**

```bash
uv run pytest tests/unit/ -v
```
Expected: all pass

- [ ] **Step 4.7: Commit**

```bash
git add src/parallax/prover/service.py src/parallax/pipeline/runner.py \
        tests/unit/test_prover_service.py
git commit -m "feat(prover): Stage 2 LLM confirmation for EQUIVALENT/SUBSET relations"
```

---

### Task 5: Cross-platform Stage 1 rules

Add a cross-platform price-inversion rule to `Stage1ConstraintDetector`: when two markets from different platforms share similar deadlines (within 7 days) and their YES prices sum to `< 0.97`, emit an EQUIVALENT candidate for Stage 2 analysis.

**Files:**
- Modify: `src/parallax/detection/stage1.py`
- Modify: `tests/unit/test_stage1_detector.py`

---

- [ ] **Step 5.1: Write failing tests**

```python
# tests/unit/test_stage1_detector.py — add to existing TestStage1ConstraintDetector
from datetime import datetime, timezone, timedelta

def _market_cross(
    mid: str, platform: str, yes_price: float, deadline: datetime | None = None
) -> RawMarket:
    if deadline is None:
        deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
    return RawMarket(
        id=mid, platform=platform,
        market_id=mid.split(":")[-1],
        title=f"Title {mid}", description="",
        resolution_criteria="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        group_id=None,
        deadline=deadline,
        is_closed=False, raw_payload={},
    )


def test_cross_platform_price_inversion_emits_equivalent_candidate():
    """Two markets on different platforms with same deadline and inverted prices → EQUIVALENT candidate."""
    from parallax.detection.stage1 import Stage1ConstraintDetector
    from parallax.shared.schemas import RelationType
    detector = Stage1ConstraintDetector()
    deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
    a = _market_cross("pm:a", "polymarket", 0.60, deadline)
    b = _market_cross("kalshi:b", "kalshi", 0.55, deadline)
    specs = detector.detect([a, b])
    equiv = [s for s in specs if s.relation_type == RelationType.EQUIVALENT]
    assert len(equiv) == 1
    assert equiv[0].evidence["rule"] == "cross_platform_price_inversion"


def test_cross_platform_no_candidate_when_deadlines_far_apart():
    """Markets with deadlines >7 days apart are not cross-platform candidates."""
    from parallax.detection.stage1 import Stage1ConstraintDetector
    from parallax.shared.schemas import RelationType
    detector = Stage1ConstraintDetector()
    a = _market_cross("pm:a", "polymarket", 0.60,
                      datetime(2025, 12, 31, tzinfo=timezone.utc))
    b = _market_cross("kalshi:b", "kalshi", 0.55,
                      datetime(2025, 11, 1, tzinfo=timezone.utc))
    specs = detector.detect([a, b])
    equiv = [s for s in specs if s.relation_type == RelationType.EQUIVALENT]
    assert len(equiv) == 0


def test_cross_platform_no_candidate_when_same_platform():
    """Same-platform markets are handled by intra-group rule, not cross-platform."""
    from parallax.detection.stage1 import Stage1ConstraintDetector
    from parallax.shared.schemas import RelationType
    detector = Stage1ConstraintDetector()
    deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
    a = _market_cross("pm:a", "polymarket", 0.60, deadline)
    b = _market_cross("pm:b", "polymarket", 0.55, deadline)
    specs = detector.detect([a, b])
    equiv = [s for s in specs if s.relation_type == RelationType.EQUIVALENT]
    assert len(equiv) == 0


def test_cross_platform_no_candidate_when_sum_too_high():
    """Yes-price sum >= 0.97 means no price inversion signal."""
    from parallax.detection.stage1 import Stage1ConstraintDetector
    from parallax.shared.schemas import RelationType
    detector = Stage1ConstraintDetector()
    deadline = datetime(2025, 12, 31, tzinfo=timezone.utc)
    a = _market_cross("pm:a", "polymarket", 0.50, deadline)
    b = _market_cross("kalshi:b", "kalshi", 0.50, deadline)
    specs = detector.detect([a, b])
    equiv = [s for s in specs if s.relation_type == RelationType.EQUIVALENT]
    assert len(equiv) == 0
```

- [ ] **Step 5.2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_stage1_detector.py -k "cross_platform" -v
```

- [ ] **Step 5.3: Implement cross-platform rule in Stage1ConstraintDetector**

```python
# src/parallax/detection/stage1.py — add to class

_CROSS_PLATFORM_PRICE_SUM_THRESHOLD = 0.97
_CROSS_PLATFORM_DEADLINE_DAYS = 7
_CROSS_PLATFORM_CONFIDENCE = 0.5  # low: requires Stage 2 confirmation

def detect(self, markets: list[RawMarket]) -> list[RelationSpec]:
    specs: list[RelationSpec] = []
    specs.extend(self._intra_group_pairs(markets))
    specs.extend(self._cross_platform_price_inversion(markets))
    return specs

def _cross_platform_price_inversion(self, markets: list[RawMarket]) -> list[RelationSpec]:
    from itertools import combinations
    specs: list[RelationSpec] = []
    for a, b in combinations(markets, 2):
        if a.platform == b.platform:
            continue
        if not a.outcome_prices or not b.outcome_prices:
            continue
        p_a = a.outcome_prices[0]
        p_b = b.outcome_prices[0]
        if not isinstance(p_a, (int, float)) or not isinstance(p_b, (int, float)):
            continue
        if p_a + p_b >= self._CROSS_PLATFORM_PRICE_SUM_THRESHOLD:
            continue
        if a.deadline is None or b.deadline is None:
            continue
        delta = abs((a.deadline - b.deadline).total_seconds())
        if delta > self._CROSS_PLATFORM_DEADLINE_DAYS * 86400:
            continue
        specs.append(RelationSpec(
            from_market_id=a.id,
            to_market_id=b.id,
            relation_type=RelationType.EQUIVALENT,
            confidence=self._CROSS_PLATFORM_CONFIDENCE,
            evidence={
                "rule": "cross_platform_price_inversion",
                "price_sum": round(p_a + p_b, 4),
                "deadline_delta_hours": round(delta / 3600, 1),
            },
        ))
    return specs
```

- [ ] **Step 5.4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_stage1_detector.py -v
```
Expected: all pass (including 4 new cross-platform tests)

- [ ] **Step 5.5: Commit**

```bash
git add src/parallax/detection/stage1.py tests/unit/test_stage1_detector.py
git commit -m "feat(detection): Stage 1 cross-platform price-inversion rule for EQUIVALENT candidates"
```

---

## Phase 3 — Kalshi Adapter

### Task 6: KalshiAdapter

Implement `KalshiAdapter(PlatformAdapter)` for the Kalshi REST API v2. Kalshi requires a Bearer API key. Map Kalshi market fields to `RawMarketData`. Add `kalshi_api_key` to config and wire the adapter into `IngestorService`.

**Files:**
- Create: `src/parallax/ingestion/kalshi_adapter.py`
- Modify: `src/parallax/config.py`
- Modify: `src/parallax/ingestion/ingestor.py`
- Create: `tests/unit/test_kalshi_adapter.py`

---

- [ ] **Step 6.1: Add kalshi_api_key to config**

```python
# src/parallax/config.py — add field to Settings
kalshi_api_key: str = ""  # empty string disables Kalshi ingestion
```

- [ ] **Step 6.2: Write failing tests**

```python
# tests/unit/test_kalshi_adapter.py
from __future__ import annotations
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from parallax.ingestion.kalshi_adapter import KalshiAdapter


def _raw_market(ticker="TRUMP-2026", close_time="2026-01-20T00:00:00Z",
                yes_bid=0.60, yes_ask=0.62, event_ticker="TRUMP-PRES",
                title="Will Trump be president in 2026?") -> dict:
    return {
        "ticker": ticker,
        "title": title,
        "close_time": close_time,
        "status": "open",
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "no_bid": 1 - yes_ask,
        "no_ask": 1 - yes_bid,
        "event_ticker": event_ticker,
        "category": "Politics",
        "rules_primary": "Resolves YES if Trump is president on Jan 20 2026.",
    }


class TestKalshiAdapter:
    def test_platform_name(self):
        adapter = KalshiAdapter(api_key="test")
        assert adapter.platform_name == "kalshi"

    def test_parse_valid_market(self):
        adapter = KalshiAdapter(api_key="test")
        raw = _raw_market()
        result = adapter._parse(raw)
        assert result is not None
        assert result.platform == "kalshi"
        assert result.market_id == "TRUMP-2026"
        assert result.group_id == "TRUMP-PRES"
        assert abs(result.outcome_prices[0] - 0.61) < 0.01  # mid-price
        assert result.is_closed is False

    def test_parse_closed_market_returns_none(self):
        adapter = KalshiAdapter(api_key="test")
        raw = _raw_market()
        raw["status"] = "finalized"
        result = adapter._parse(raw)
        assert result is None

    def test_parse_missing_close_time_returns_none(self):
        adapter = KalshiAdapter(api_key="test")
        raw = _raw_market()
        del raw["close_time"]
        result = adapter._parse(raw)
        assert result is None

    @pytest.mark.anyio
    async def test_fetch_markets_sends_auth_header(self):
        adapter = KalshiAdapter(api_key="test-key")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"markets": [_raw_market()], "cursor": ""}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        adapter._client = mock_client

        results = await adapter.fetch_markets()

        call_kwargs = mock_client.get.call_args.kwargs
        assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_fetch_markets_paginates_via_cursor(self):
        adapter = KalshiAdapter(api_key="test-key")
        page1 = MagicMock()
        page1.json.return_value = {"markets": [_raw_market("M1")], "cursor": "next-cursor"}
        page1.raise_for_status = MagicMock()
        page2 = MagicMock()
        page2.json.return_value = {"markets": [_raw_market("M2")], "cursor": ""}
        page2.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=[page1, page2])
        adapter._client = mock_client

        results = await adapter.fetch_markets()
        assert len(results) == 2
        assert mock_client.get.call_count == 2
```

- [ ] **Step 6.3: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_kalshi_adapter.py -v
```

- [ ] **Step 6.4: Implement KalshiAdapter**

```python
# src/parallax/ingestion/kalshi_adapter.py
from __future__ import annotations
from datetime import datetime
import httpx
from parallax.ingestion.adapter import PlatformAdapter
from parallax.shared.schemas import RawMarketData

_KALSHI_BASE = "https://trading-api.kalshi.com/trade-api/v2"
_PAGE_SIZE = 200


class KalshiAdapter(PlatformAdapter):
    """Fetches open markets from Kalshi via the REST API v2 (requires Bearer API key)."""

    def __init__(
        self,
        api_key: str,
        max_markets: int = 500,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_markets = max_markets
        self._client = http_client

    @property
    def platform_name(self) -> str:
        return "kalshi"

    async def fetch_markets(self) -> list[RawMarketData]:
        client = self._client or httpx.AsyncClient(timeout=30)
        own_client = self._client is None
        try:
            return await self._fetch(client)
        finally:
            if own_client:
                await client.aclose()

    async def _fetch(self, client: httpx.AsyncClient) -> list[RawMarketData]:
        results: list[RawMarketData] = []
        cursor = ""
        headers = {"Authorization": f"Bearer {self._api_key}"}
        while len(results) < self._max_markets:
            params: dict = {"status": "open", "limit": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                f"{_KALSHI_BASE}/markets",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("markets", [])
            for raw in batch:
                parsed = self._parse(raw)
                if parsed is not None:
                    results.append(parsed)
            cursor = data.get("cursor", "")
            if not cursor or not batch:
                break
        return results

    def _parse(self, raw: dict) -> RawMarketData | None:
        try:
            if raw.get("status", "") != "open":
                return None
            close_time = raw.get("close_time")
            if not close_time:
                return None
            deadline = datetime.fromisoformat(close_time.replace("Z", "+00:00"))

            yes_bid = raw.get("yes_bid", 0.0) or 0.0
            yes_ask = raw.get("yes_ask", 0.0) or 0.0
            yes_mid = (float(yes_bid) + float(yes_ask)) / 2.0

            return RawMarketData(
                platform="kalshi",
                market_id=raw["ticker"],
                title=raw.get("title", ""),
                description=raw.get("rules_primary", ""),
                resolution_criteria=raw.get("rules_primary", ""),
                outcomes=["Yes", "No"],
                outcome_prices=[round(yes_mid, 4), round(1.0 - yes_mid, 4)],
                category=raw.get("category"),
                group_id=raw.get("event_ticker"),
                deadline=deadline,
                is_closed=False,
                resolution_source=None,
                raw_payload=raw,
            )
        except (KeyError, ValueError, TypeError):
            return None
```

- [ ] **Step 6.5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_kalshi_adapter.py -v
```
Expected: 6 passed

- [ ] **Step 6.6: Wire KalshiAdapter into IngestorService**

```python
# src/parallax/ingestion/ingestor.py — update factory or init
# IngestorService accepts a list of adapters. Add KalshiAdapter when api_key is configured.

# In PipelineRunner or wherever IngestorService is instantiated, add:
from parallax.ingestion.kalshi_adapter import KalshiAdapter

adapters = [PolymarketAdapter(max_events=settings.polymarket_max_events_per_poll)]
if settings.kalshi_api_key:
    adapters.append(KalshiAdapter(api_key=settings.kalshi_api_key))
ingestor = IngestorService(session, adapters)
```

Check current `IngestorService` signature to confirm it accepts a list of adapters.

- [ ] **Step 6.7: Run full unit test suite**

```bash
uv run pytest tests/unit/ -v
```

- [ ] **Step 6.8: Commit**

```bash
git add src/parallax/ingestion/kalshi_adapter.py src/parallax/config.py \
        src/parallax/ingestion/ingestor.py \
        tests/unit/test_kalshi_adapter.py
git commit -m "feat(ingestion): KalshiAdapter — REST API v2 with cursor pagination and mid-price"
```

---

## Phase 4 — Integration Tests

### Task 7: Integration test suite

Write integration tests that run the full pipeline end-to-end against the `postgres_test` container (port 5433). Tests are marked `@pytest.mark.integration` and skipped unless the test DB is reachable.

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_pipeline_integration.py`

---

- [ ] **Step 7.1: Write conftest with DB fixtures**

```python
# tests/integration/conftest.py
from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from parallax.db.models import Base


TEST_DATABASE_URL = "postgresql://parallax:dev_password@localhost:5433/parallax_test"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def test_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    try:
        yield session
        session.rollback()  # always roll back after each test
    finally:
        session.close()
```

- [ ] **Step 7.2: Write integration tests**

```python
# tests/integration/test_pipeline_integration.py
from __future__ import annotations
import uuid
import pytest
from datetime import datetime, timezone
from parallax.db.models import RawMarket, MarketRelation, OpportunityCandidate
from parallax.detection.stage1 import Stage1ConstraintDetector
from parallax.divergence.candidate_repository import CandidateRepository
from parallax.divergence.service import DivergenceService
from parallax.graph.postgres_repository import PostgresGraphRepository
from parallax.ingestion.market_repository import MarketRepository
from parallax.ingestion.polymarket_adapter import PolymarketAdapter
from parallax.prover.service import ProverService
from parallax.shared.schemas import OpportunityType, RawMarketData


def _raw_market_data(market_id: str, yes_price: float, group_id: str | None = None) -> RawMarketData:
    return RawMarketData(
        platform="polymarket",
        market_id=market_id,
        title=f"Will {market_id} happen?",
        description="Test market.",
        resolution_criteria="Resolves YES if it happens.",
        outcomes=["Yes", "No"],
        outcome_prices=[yes_price, 1 - yes_price],
        group_id=group_id,
        deadline=datetime(2025, 12, 31, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=None,
        raw_payload={},
    )


@pytest.mark.integration
class TestMarketRepositoryIntegration:
    def test_upsert_and_retrieve(self, test_session):
        repo = MarketRepository(test_session)
        data = _raw_market_data("test-upsert-001", 0.6)
        market, created = repo.upsert(data)
        test_session.commit()
        assert created is True
        assert market.id == "polymarket:test-upsert-001"

        retrieved = repo.get("polymarket:test-upsert-001")
        assert retrieved is not None
        assert abs(retrieved.outcome_prices[0] - 0.6) < 0.001

    def test_upsert_updates_existing(self, test_session):
        repo = MarketRepository(test_session)
        data = _raw_market_data("test-upsert-002", 0.5)
        repo.upsert(data)
        test_session.commit()

        updated = _raw_market_data("test-upsert-002", 0.7)
        _, created = repo.upsert(updated)
        test_session.commit()
        assert created is False
        market = repo.get("polymarket:test-upsert-002")
        assert abs(market.outcome_prices[0] - 0.7) < 0.001


@pytest.mark.integration
class TestProverServiceIntegration:
    def _insert_market(self, session, market_id: str, yes_price: float, group_id: str) -> RawMarket:
        repo = MarketRepository(session)
        data = _raw_market_data(market_id, yes_price, group_id)
        market, _ = repo.upsert(data)
        session.commit()
        return market

    def test_stage1_detects_and_stores_relation(self, test_session):
        a = self._insert_market(test_session, f"int-rel-a-{uuid.uuid4().hex[:6]}", 0.6, "grp-int")
        b = self._insert_market(test_session, f"int-rel-b-{uuid.uuid4().hex[:6]}", 0.55, "grp-int")
        graph_repo = PostgresGraphRepository(test_session)
        prover = ProverService(test_session, graph_repo, stage2_classifier=None)

        import asyncio
        count = asyncio.run(prover.run([a, b]))
        test_session.commit()

        assert count == 1
        assert graph_repo.relation_exists(a.id, b.id, __import__("parallax.shared.schemas", fromlist=["RelationType"]).RelationType.MUTUALLY_EXCLUSIVE)


@pytest.mark.integration
class TestDivergenceServiceIntegration:
    def test_scan_creates_candidate(self, test_session):
        repo = MarketRepository(test_session)
        suffix = uuid.uuid4().hex[:6]
        a_data = _raw_market_data(f"div-a-{suffix}", 0.60, f"div-grp-{suffix}")
        b_data = _raw_market_data(f"div-b-{suffix}", 0.55, f"div-grp-{suffix}")
        a, _ = repo.upsert(a_data)
        b, _ = repo.upsert(b_data)
        test_session.commit()

        graph_repo = PostgresGraphRepository(test_session)
        from parallax.shared.schemas import RelationType
        graph_repo.add_relation(a.id, b.id, RelationType.MUTUALLY_EXCLUSIVE, 0.95, {}, "test")
        test_session.commit()

        svc = DivergenceService(test_session, graph_repo, friction_bps=50)
        count = svc.scan([a, b])
        test_session.commit()

        assert count == 1
        cand_repo = CandidateRepository(test_session)
        candidates = cand_repo.list_open()
        assert any(frozenset(c.market_ids) == frozenset([a.id, b.id]) for c in candidates)
```

- [ ] **Step 7.3: Add integration marker to pyproject.toml**

The marker `integration` is already declared in `pyproject.toml`. Confirm:

```bash
grep "integration" pyproject.toml
```
Expected: `integration: requires postgres and external APIs`

- [ ] **Step 7.4: Run integration tests (requires Docker)**

```bash
docker compose up -d
sleep 5
uv run pytest tests/integration/ -v -m integration
```
Expected: all integration tests pass

- [ ] **Step 7.5: Verify unit tests still pass**

```bash
uv run pytest tests/unit/ -v
```

- [ ] **Step 7.6: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_pipeline_integration.py
git commit -m "test(integration): end-to-end pipeline integration tests against postgres_test"
```

---

## ADR compliance check

| ADR | Requirement | Implementation |
|-----|-------------|----------------|
| 0002 | Anthropic API, tool_use, prompt caching | Stage2LLMDetector uses `tool_choice` + `cache_control: ephemeral` on system prompt |
| 0003 | Kalshi adapter behind PlatformAdapter | KalshiAdapter implements PlatformAdapter; added when `kalshi_api_key` non-empty |
| 0005 | Stage 1 first, Stage 2 for EQUIV/SUBSET only | ProverService routes by RelationType; ME stored without Stage 2 |
| 0006 | total_cost = capital deployed | Unchanged; DivergenceService convention preserved |

---

## Validation plan

```bash
# Full unit suite
uv run pytest tests/unit/ -v                    # expect 100+ pass

# Integration suite (requires Docker)
docker compose up -d && sleep 5
uv run pytest tests/integration/ -v -m integration

# Lint
uv run ruff check src/ tests/

# Smoke test API (requires running server + migrations)
uv run alembic upgrade head
uv run uvicorn parallax.api.app:app --port 8000 &
curl http://localhost:8000/health
```

---

## Known risks

| Risk | Mitigation |
|------|------------|
| Kalshi API key not available in dev | `kalshi_api_key = ""` skips adapter; unit tests mock httpx |
| Stage 2 LLM latency (2 API calls per candidate pair) | Only triggered for EQUIVALENT/SUBSET Stage 1 candidates; cross-platform rule emits conservatively |
| Anthropic API key not set in pipeline | Compiler step catches exceptions per-market and logs; pipeline continues |
| `run_once()` becoming async breaks existing call sites | Only called from `__main__` and tests; tests updated to `@pytest.mark.anyio` |
| CompiledContract 24h cache stale for fast-moving markets | Cache TTL configurable via `_RECOMPILE_AFTER_HOURS`; can be reduced to 1h in prod config |

---

## Out of scope (Slice 3)

- Real `CourtService` adversarial review (Prosecutor/Defense/Judge loop)
- Real `SimulatorService` with order book and slippage model
- Calibration loop (Autopsy → Stage 1/2 threshold tuning)
- WebSocket real-time feed (polling every 5 min is sufficient for Slice 2)
- SQLAlchemy 2.0 `select()` migration (low risk, high churn — defer)

---

*— End of Plan —*
