# Fase 4 — Risk Score + Snapshot Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the court evaluation uses snapshot-based simulation, `depth_support` and `partial_fill_risk` from the orderbook feed back into the `RiskScore`, so the `composite_risk` gate reflects actual book reality rather than stale detection-time heuristics.

**Architecture:** `RiskScore.adjust_from_simulation(base, simulation) -> RiskScore` produces a new score with snapshot-adjusted `execution_risk` and `liquidity_risk` (and recomputed `composite`). `CourtService._run_assessment()` accepts an optional `risk_override`. `assess_with_snapshots()` computes the adjusted score and passes it to `_run_assessment()`, then returns it as a third element. `_persist_evaluation()` persists the adjusted score in the decision snapshot when provided. The original `opportunity_candidates.risk_scores` column is never mutated.

**Tech Stack:** Python 3.13, Pydantic v2, SQLAlchemy 2.0. No DB schema changes.

---

### File Map

**Create:**
- `tests/unit/test_risk_score_adjustment.py`

**Modify:**
- `src/parallax/shared/schemas.py` — add `RiskScore.adjust_from_simulation(base, simulation)` static method
- `src/parallax/court/service.py` — four targeted changes:
  1. `_run_assessment` gains `risk_override: RiskScore | None = None`
  2. `_compute_adjusted_risk(candidate_id, simulation)` new private helper
  3. `assess_with_snapshots` computes adjusted risk, injects into `_run_assessment`, returns 3-tuple
  4. `evaluate_with_snapshots` and `_persist_evaluation` thread adjusted risk through to snapshot

---

### Task 1: `RiskScore.adjust_from_simulation`

**Files:**
- Modify: `src/parallax/shared/schemas.py`
- Test: `tests/unit/test_risk_score_adjustment.py`

The adjustment rules:
- `execution_model != "snapshot_based"` → return `base` unchanged
- `depth_support=True` → `execution_risk = max(0.0, base.execution_risk - 0.08)` (real book supports fill)
- `depth_support=False` → `execution_risk = min(1.0, base.execution_risk + 0.30)` (book insufficient)
- `depth_support=None` → unchanged
- `partial_fill_risk > 0` → `liquidity_risk = max(base.liquidity_risk, round(partial_fill_risk * 0.8, 4))`
- `composite` is recomputed by `RiskScore.combine()`
- `policy_version` becomes `"risk-v2-snapshot"`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_risk_score_adjustment.py`:

```python
from __future__ import annotations

import pytest
from parallax.shared.schemas import RiskScore, SimulationResult


def _base_risk(execution_risk=0.05, liquidity_risk=0.08) -> RiskScore:
    return RiskScore.combine(
        oracle=0.1, deadline=0.05, semantic=0.2,
        execution=execution_risk, liquidity=liquidity_risk,
        cancellation=0.05, source_trust=0.08,
    )


def _sim(execution_model="snapshot_based", depth_support=True, partial_fill_risk=0.1) -> SimulationResult:
    return SimulationResult(
        candidate_id="c1",
        simulated_pnl=0.05,
        friction_bps=50,
        fill_probability=0.9,
        is_executable=True,
        note="",
        execution_model=execution_model,
        depth_support=depth_support,
        partial_fill_risk=partial_fill_risk,
    )


def test_adjust_returns_base_unchanged_for_heuristic_model():
    base = _base_risk()
    sim = _sim(execution_model="heuristic")
    result = RiskScore.adjust_from_simulation(base, sim)
    assert result.execution_risk == base.execution_risk
    assert result.liquidity_risk == base.liquidity_risk
    assert result.policy_version == "risk-v2"


def test_adjust_lowers_execution_risk_when_depth_supported():
    base = _base_risk(execution_risk=0.13)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.0))
    assert result.execution_risk == round(max(0.0, 0.13 - 0.08), 4)
    assert result.policy_version == "risk-v2-snapshot"


def test_adjust_raises_execution_risk_when_depth_insufficient():
    base = _base_risk(execution_risk=0.10)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=False, partial_fill_risk=0.0))
    assert result.execution_risk == round(min(1.0, 0.10 + 0.30), 4)
    assert result.policy_version == "risk-v2-snapshot"


def test_adjust_leaves_execution_risk_unchanged_when_depth_unknown():
    base = _base_risk(execution_risk=0.10)
    sim = _sim(depth_support=None)
    result = RiskScore.adjust_from_simulation(base, sim)
    assert result.execution_risk == 0.10


def test_adjust_raises_liquidity_risk_from_partial_fill():
    base = _base_risk(liquidity_risk=0.08)
    # partial_fill_risk=0.7 → 0.7*0.8=0.56 > 0.08
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.7))
    assert result.liquidity_risk == round(0.7 * 0.8, 4)


def test_adjust_keeps_base_liquidity_when_partial_fill_low():
    base = _base_risk(liquidity_risk=0.20)
    # partial_fill_risk=0.1 → 0.1*0.8=0.08 < 0.20 → keep 0.20
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.1))
    assert result.liquidity_risk == 0.20


def test_adjust_recomputes_composite():
    base = _base_risk(execution_risk=0.05, liquidity_risk=0.08)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=False, partial_fill_risk=0.5))
    # composite is mean of all 7 components
    expected_exec = round(min(1.0, 0.05 + 0.30), 4)
    expected_liq = round(max(0.08, 0.5 * 0.8), 4)
    components = [0.1, 0.05, 0.2, expected_exec, expected_liq, 0.05, 0.08]
    expected_composite = round(sum(components) / 7, 4)
    assert result.composite == expected_composite


def test_adjust_clamps_execution_risk_at_zero():
    base = _base_risk(execution_risk=0.03)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=True, partial_fill_risk=0.0))
    assert result.execution_risk >= 0.0


def test_adjust_clamps_execution_risk_at_one():
    base = _base_risk(execution_risk=0.90)
    result = RiskScore.adjust_from_simulation(base, _sim(depth_support=False, partial_fill_risk=0.0))
    assert result.execution_risk <= 1.0
```

Run: `uv run pytest tests/unit/test_risk_score_adjustment.py -v`
Expected: FAIL — `AttributeError: type object 'RiskScore' has no attribute 'adjust_from_simulation'`

- [ ] **Step 2: Add `adjust_from_simulation` to `RiskScore`**

In `src/parallax/shared/schemas.py`, after the `combine` classmethod and before the `class SimulationResult` line, add:

```python
    @staticmethod
    def adjust_from_simulation(base: "RiskScore", simulation: "SimulationResult") -> "RiskScore":
        if simulation.execution_model != "snapshot_based":
            return base
        execution_risk = base.execution_risk
        if simulation.depth_support is True:
            execution_risk = round(max(0.0, execution_risk - 0.08), 4)
        elif simulation.depth_support is False:
            execution_risk = round(min(1.0, execution_risk + 0.30), 4)
        liquidity_risk = base.liquidity_risk
        if simulation.partial_fill_risk > 0:
            liquidity_risk = round(max(base.liquidity_risk, simulation.partial_fill_risk * 0.8), 4)
        return RiskScore.combine(
            oracle=base.oracle_risk,
            deadline=base.deadline_risk,
            semantic=base.semantic_risk,
            execution=execution_risk,
            liquidity=liquidity_risk,
            cancellation=base.cancellation_risk,
            source_trust=base.source_trust_risk,
            policy_version="risk-v2-snapshot",
        )
```

Note: `adjust_from_simulation` references `SimulationResult`, which is defined after `RiskScore` in the file. Use a string annotation or move the definition. The safest approach: define it as a `@staticmethod` with `"SimulationResult"` forward reference since both classes are in the same module and Pydantic resolves them. Python 3.13 with `from __future__ import annotations` makes this a non-issue since all annotations are strings.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_risk_score_adjustment.py -v --tb=short
```

Expected: all PASS

- [ ] **Step 4: Verify no regressions**

```bash
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/parallax/shared/schemas.py tests/unit/test_risk_score_adjustment.py
git commit -m "feat(risk): RiskScore.adjust_from_simulation — snapshot-aware execution/liquidity risk"
```

---

### Task 2: `_run_assessment` accepts `risk_override`

**Files:**
- Modify: `src/parallax/court/service.py`
- Test: existing tests pass unchanged

The only change to `_run_assessment` is the line that reads `risk` from the candidate. It becomes:

```python
risk = risk_override if risk_override is not None else (
    RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
)
```

- [ ] **Step 1: Update `_run_assessment` signature and risk lookup**

In `src/parallax/court/service.py`, change `_run_assessment` signature from:

```python
def _run_assessment(
    self,
    candidate_id: str,
    simulation: SimulationResult,
) -> tuple[CourtAssessment, SimulationResult]:
```

to:

```python
def _run_assessment(
    self,
    candidate_id: str,
    simulation: SimulationResult,
    risk_override: RiskScore | None = None,
) -> tuple[CourtAssessment, SimulationResult]:
```

And change the risk lookup line (currently line ~181):

```python
risk = RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
```

to:

```python
risk = risk_override if risk_override is not None else (
    RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
)
```

- [ ] **Step 2: Run full unit suite**

```bash
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all pass (no change in behavior — `risk_override` defaults to `None`)

- [ ] **Step 3: Commit**

```bash
git add src/parallax/court/service.py
git commit -m "refactor(court): _run_assessment accepts optional risk_override"
```

---

### Task 3: `assess_with_snapshots` computes and injects adjusted risk

**Files:**
- Modify: `src/parallax/court/service.py`
- Test: `tests/unit/test_risk_score_adjustment.py` (add court integration test)

Changes:
1. Add `_compute_adjusted_risk(candidate_id, simulation) -> RiskScore | None` private helper
2. `assess_with_snapshots` calls helper, passes result to `_run_assessment`
3. Return type changes to `tuple[CourtAssessment, SimulationResult, RiskScore | None]`
4. `evaluate_with_snapshots` unpacks 3-tuple

- [ ] **Step 1: Write failing integration test**

Append to `tests/unit/test_risk_score_adjustment.py`:

```python
def test_assess_with_snapshots_uses_adjusted_risk_in_composite_gate():
    """When depth_support=False, the composite gate in the assessment should reflect the penalized risk."""
    from unittest.mock import MagicMock, patch
    from parallax.court.service import CourtService
    from parallax.shared.schemas import (
        CourtAssessment, CourtDecision, RiskScore, SimulationResult, PayoffMatrix,
        Leg, Scenario, OpportunityType,
    )
    from parallax.execution.schemas import OrderbookSnapshot

    base_risk = RiskScore.combine(
        oracle=0.05, deadline=0.02, semantic=0.1,
        execution=0.05, liquidity=0.08, cancellation=0.05, source_trust=0.08,
    )
    # With depth_support=False, execution_risk → 0.35 → composite rises

    session = MagicMock()
    svc = CourtService.__new__(CourtService)
    svc._session = session
    svc._repo = MagicMock()
    svc._market_repo = MagicMock()
    svc._graph_repo = MagicMock()
    svc._simulator = MagicMock()

    candidate = MagicMock()
    candidate.id = "cand-1"
    candidate.risk_scores = base_risk.model_dump()
    candidate.worst_case_payoff = 0.05
    candidate.market_ids = ["mkt-a", "mkt-b"]
    candidate.opportunity_type = "pure_arbitrage"
    svc._repo.get.return_value = candidate

    simulation = SimulationResult(
        candidate_id="cand-1",
        simulated_pnl=0.03,
        friction_bps=50,
        fill_probability=0.9,
        is_executable=True,
        note="",
        execution_model="snapshot_based",
        depth_support=False,
        partial_fill_risk=0.0,
    )
    svc._simulator.simulate_snapshot.return_value = simulation

    svc._market_repo.get.return_value = None
    with patch("parallax.court.service.load_relation_evidence", return_value=None),          patch("parallax.court.service.get_relation_signals", return_value={
             "oracle_mismatch": False, "deadline_mismatch": False,
             "source_mismatch": False, "ambiguity_level": "low",
             "ambiguity_terms": [], "shared_ambiguity_terms": [],
         }):
        assessment, sim_out, adjusted_risk = svc.assess_with_snapshots("cand-1", {})

    assert adjusted_risk is not None
    assert adjusted_risk.execution_risk == round(min(1.0, 0.05 + 0.30), 4)
    assert adjusted_risk.policy_version == "risk-v2-snapshot"
    # composite gate in assessment should reference adjusted composite, not base
    composite_gate = next((g for g in assessment.gates if g.name == "composite_risk"), None)
    if composite_gate is not None:
        assert float(composite_gate.observed) == adjusted_risk.composite
```

Run: `uv run pytest tests/unit/test_risk_score_adjustment.py::test_assess_with_snapshots_uses_adjusted_risk_in_composite_gate -v`
Expected: FAIL — `ValueError: not enough values to unpack (expected 3, got 2)`

- [ ] **Step 2: Add `_compute_adjusted_risk` helper**

In `src/parallax/court/service.py`, add after `_orderbook_gates`:

```python
def _compute_adjusted_risk(
    self, candidate_id: str, simulation: SimulationResult
) -> RiskScore | None:
    candidate = self._repo.get(candidate_id)
    if candidate is None or not candidate.risk_scores:
        return None
    base = RiskScore.model_validate(candidate.risk_scores)
    return RiskScore.adjust_from_simulation(base, simulation)
```

- [ ] **Step 3: Update `assess_with_snapshots`**

Change the method body from:

```python
def assess_with_snapshots(
    self,
    candidate_id: str,
    snapshots: dict[str, OrderbookSnapshot | None],
) -> tuple[CourtAssessment, SimulationResult]:
    simulation = self._simulator.simulate_snapshot(candidate_id, snapshots)
    base_assessment, _ = self._run_assessment(candidate_id, simulation)
    ...
    return assessment, simulation
```

to:

```python
def assess_with_snapshots(
    self,
    candidate_id: str,
    snapshots: dict[str, OrderbookSnapshot | None],
) -> tuple[CourtAssessment, SimulationResult, RiskScore | None]:
    simulation = self._simulator.simulate_snapshot(candidate_id, snapshots)
    adjusted_risk = self._compute_adjusted_risk(candidate_id, simulation)
    base_assessment, _ = self._run_assessment(candidate_id, simulation, risk_override=adjusted_risk)
    ...
    return assessment, simulation, adjusted_risk
```

- [ ] **Step 4: Update `evaluate_with_snapshots` to unpack 3-tuple**

Change:

```python
def evaluate_with_snapshots(self, candidate_id, snapshots, run_id=None):
    assessment, simulation = self.assess_with_snapshots(candidate_id, snapshots)
    return self._persist_evaluation(candidate_id, assessment, simulation, run_id)
```

to:

```python
def evaluate_with_snapshots(self, candidate_id, snapshots, run_id=None):
    assessment, simulation, adjusted_risk = self.assess_with_snapshots(candidate_id, snapshots)
    return self._persist_evaluation(candidate_id, assessment, simulation, run_id, adjusted_risk=adjusted_risk)
```

- [ ] **Step 5: Run the integration test**

```bash
uv run pytest tests/unit/test_risk_score_adjustment.py::test_assess_with_snapshots_uses_adjusted_risk_in_composite_gate -v --tb=short
```

Expected: PASS

- [ ] **Step 6: Run full suite**

```bash
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/parallax/court/service.py tests/unit/test_risk_score_adjustment.py
git commit -m "feat(court): inject snapshot-adjusted RiskScore into composite_risk gate"
```

---

### Task 4: `_persist_evaluation` persists adjusted risk

**Files:**
- Modify: `src/parallax/court/service.py`
- Test: append to `tests/unit/test_risk_score_adjustment.py`

Currently `_persist_evaluation` re-reads `candidate.risk_scores` from DB. When `adjusted_risk` is provided, use it instead.

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_risk_score_adjustment.py`:

```python
def test_decision_snapshot_persists_adjusted_risk():
    """_persist_evaluation should store adjusted_risk in the decision snapshot when provided."""
    from unittest.mock import MagicMock, call
    from parallax.court.service import CourtService
    from parallax.shared.schemas import (
        CourtAssessment, CourtDecision, RiskScore, SimulationResult, OpportunityType,
    )

    adjusted_risk = RiskScore.combine(
        oracle=0.05, deadline=0.02, semantic=0.1,
        execution=0.35, liquidity=0.08, cancellation=0.05, source_trust=0.08,
        policy_version="risk-v2-snapshot",
    )
    simulation = SimulationResult(
        candidate_id="cand-1",
        simulated_pnl=0.03,
        friction_bps=50,
        fill_probability=0.9,
        is_executable=True,
        note="",
        execution_model="snapshot_based",
    )
    assessment = CourtAssessment(
        decision=CourtDecision.APPROVED,
        simulated_pnl=0.03,
        fill_probability=0.9,
        composite_risk=None,
        reasons=[],
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        relation_type=None,
        risk_flags=[],
        gates=[],
        policy_version="court-v2-snapshot",
    )

    session = MagicMock()
    svc = CourtService.__new__(CourtService)
    svc._session = session
    svc._repo = MagicMock()

    candidate = MagicMock()
    candidate.market_ids = ["mkt-a"]
    svc._repo.get.return_value = candidate

    upserted = {}
    def capture_upsert(**kwargs):
        upserted.update(kwargs)
    svc._repo.upsert_decision_snapshot.side_effect = lambda cid, **kwargs: upserted.update(kwargs)

    with patch("parallax.court.service.load_relation_evidence", return_value=None):
        svc._persist_evaluation("cand-1", assessment, simulation, run_id=None, adjusted_risk=adjusted_risk)

    svc._repo.update_decision.assert_called_once()
    svc._repo.upsert_decision_snapshot.assert_called_once()
    call_kwargs = svc._repo.upsert_decision_snapshot.call_args.kwargs
    persisted_risk = call_kwargs.get("risk_score")
    assert persisted_risk is not None
    assert persisted_risk.policy_version == "risk-v2-snapshot"
    assert persisted_risk.execution_risk == adjusted_risk.execution_risk
```

Run: `uv run pytest tests/unit/test_risk_score_adjustment.py::test_decision_snapshot_persists_adjusted_risk -v`
Expected: FAIL — `_persist_evaluation` doesn't accept `adjusted_risk`

- [ ] **Step 2: Update `_persist_evaluation`**

Change signature from:

```python
def _persist_evaluation(
    self,
    candidate_id: str,
    assessment: CourtAssessment,
    simulation: SimulationResult,
    run_id: str | None,
) -> CourtDecision:
```

to:

```python
def _persist_evaluation(
    self,
    candidate_id: str,
    assessment: CourtAssessment,
    simulation: SimulationResult,
    run_id: str | None,
    *,
    adjusted_risk: RiskScore | None = None,
) -> CourtDecision:
```

And change the risk resolution inside the method from:

```python
risk = None
if candidate is not None and candidate.risk_scores:
    risk = RiskScore.model_validate(candidate.risk_scores)
```

to:

```python
risk = adjusted_risk
if risk is None and candidate is not None and candidate.risk_scores:
    risk = RiskScore.model_validate(candidate.risk_scores)
```

- [ ] **Step 3: Run the new test**

```bash
uv run pytest tests/unit/test_risk_score_adjustment.py::test_decision_snapshot_persists_adjusted_risk -v --tb=short
```

Expected: PASS

- [ ] **Step 4: Run full suite**

```bash
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/parallax/court/service.py tests/unit/test_risk_score_adjustment.py
git commit -m "feat(court): persist snapshot-adjusted RiskScore in decision snapshot"
```

---

### Task 5: Final validation + STATUS.md

**Files:**
- Modify: `docs/STATUS.md`

- [ ] **Step 1: Run full unit suite**

```bash
uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -10
```

Expected: all pass, count >= 253 + new tests

- [ ] **Step 2: Verify the gate chain end-to-end with a constructed mock**

Run: `uv run pytest tests/unit/test_risk_score_adjustment.py -v`
Expected: all PASS

- [ ] **Step 3: Update STATUS.md**

Add to the "Verified But Still Heuristic" section, replace the `risk scoring` bullet:

Before:
```
- risk scoring is still a heuristic composite, even though it is now versioned and decomposed into a richer vector
```

After:
```
- risk scoring is still a detection-time heuristic composite; when snapshot-based simulation is available, `execution_risk` and `liquidity_risk` are adjusted from `depth_support` and `partial_fill_risk` and the adjusted score is persisted in the decision snapshot (policy_version="risk-v2-snapshot")
- court `composite_risk` gate uses snapshot-adjusted composite when `orderbook_enabled=True`, detection-time composite otherwise
```

- [ ] **Step 4: Final commit**

```bash
git add docs/STATUS.md
git commit -m "docs: document Fase 4 snapshot risk score adjustment in STATUS.md"
```
