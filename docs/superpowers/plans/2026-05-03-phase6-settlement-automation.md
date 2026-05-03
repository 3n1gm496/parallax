# Fase 6 — Settlement Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically settle open paper positions when all underlying markets have closed and their final prices are deterministic (≥0.9 or ≤0.1 for the YES outcome).

**Architecture:** A `SettlementScannerService` reads open `PaperPosition` rows, checks each underlying `RawMarket` for closure and deterministic outcome prices, computes per-leg PnL from `legs_json`, and calls `TrackerService.close_position()` + `AutopsyService.record()`. The scanner is wired into `PipelineRunner.run_once()` after the candidate evaluation loop, before the final audit record.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0, Pydantic v2. No new dependencies.

---

## File Map

| Action | Path |
|--------|------|
| Create | `src/parallax/settlement/__init__.py` |
| Create | `src/parallax/settlement/scanner.py` |
| Modify | `src/parallax/pipeline/runner.py` |
| Create | `tests/unit/test_settlement_scanner.py` |
| Modify | `docs/STATUS.md` |

---

### Task 1: `SettlementScannerService` — resolution inference + PnL computation

**Files:**
- Create: `src/parallax/settlement/__init__.py`
- Create: `src/parallax/settlement/scanner.py`
- Create: `tests/unit/test_settlement_scanner.py`

#### Resolution rules

- `market.outcome_prices[0]` (YES price) ≥ 0.9 → market resolved **YES**
- `market.outcome_prices[0]` (YES price) ≤ 0.1 → market resolved **NO**
- Otherwise → ambiguous; scanner **skips** the position (defers to manual settlement)

#### PnL computation per leg

```
side="YES": win when resolved=="YES", payoff = (1.0 - price) * quantity
            loss when resolved=="NO",  payoff = -price * quantity
side="NO":  win when resolved=="NO",  payoff = (1.0 - price) * quantity
            loss when resolved=="YES", payoff = -price * quantity
```

Total cost comes from `PayoffMatrix.total_cost` stored in the candidate's `payoff_matrix` column. Normalize: `actual_pnl = sum(payoffs) / total_cost`, clamped to `[-1.0, 1.0]`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_settlement_scanner.py
from __future__ import annotations
import json
import uuid
from unittest.mock import MagicMock, patch
import pytest
from parallax.settlement.scanner import SettlementScannerService

def _make_position(candidate_id: str, legs_json: list[dict]) -> MagicMock:
    pos = MagicMock()
    pos.id = uuid.uuid4()
    pos.candidate_id = uuid.UUID(candidate_id)
    pos.legs_json = legs_json
    pos.status = "OPEN"
    return pos

def _make_candidate(candidate_id: str, market_ids: list[str], payoff_matrix: dict) -> MagicMock:
    cand = MagicMock()
    cand.id = uuid.UUID(candidate_id)
    cand.market_ids = market_ids
    cand.payoff_matrix = payoff_matrix
    return cand

def _make_market(is_closed: bool, yes_price: float) -> MagicMock:
    m = MagicMock()
    m.is_closed = is_closed
    m.outcome_prices = [yes_price, 1.0 - yes_price]
    return m

CAND_ID = "00000000-0000-0000-0000-000000000001"
MKT_A = "polymarket:mkt-a"
MKT_B = "kalshi:mkt-b"

def _matrix_json(legs: list[dict], total_cost: float = 1.0) -> dict:
    return {
        "legs": legs,
        "total_cost": total_cost,
        "scenarios": [{"name": "win", "description": "win", "payoff": 0.1, "is_breaking": False}],
        "worst_case_payoff": 0.05,
        "best_case_payoff": 0.1,
        "breaking_scenario": None,
        "opportunity_type": "pure_arbitrage",
        "friction_bps": 10,
    }


class TestSettlementScannerService:

    def _make_session(self, positions, candidates_by_id, markets_by_id):
        session = MagicMock()

        tracker = MagicMock()
        tracker.get_open_positions.return_value = positions

        autopsy = MagicMock()

        def get_side_effect(model_class, pk):
            from parallax.db.models import OpportunityCandidate
            if model_class is OpportunityCandidate:
                return candidates_by_id.get(str(pk))
            return markets_by_id.get(str(pk))

        session.get.side_effect = get_side_effect
        return session, tracker, autopsy

    def test_no_open_positions_returns_empty(self):
        session = MagicMock()
        svc = SettlementScannerService(session)
        with patch("parallax.settlement.scanner.TrackerService") as MockTracker:
            MockTracker.return_value.get_open_positions.return_value = []
            result = svc.scan_and_settle()
        assert result == []

    def test_market_not_closed_skips_position(self):
        cand_id = CAND_ID
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.5, "quantity": 1.0}
        matrix = _matrix_json([leg], total_cost=0.5)
        pos = _make_position(cand_id, [leg])
        cand = _make_candidate(cand_id, [MKT_A], matrix)
        market = _make_market(is_closed=False, yes_price=0.95)

        session = MagicMock()
        session.get.side_effect = lambda cls, pk: (
            cand if str(pk) == cand_id else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService") as MockAutopsy,
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            result = svc.scan_and_settle()

        assert result == []
        MockTracker.return_value.close_position.assert_not_called()

    def test_ambiguous_price_skips_position(self):
        cand_id = CAND_ID
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.5, "quantity": 1.0}
        matrix = _matrix_json([leg], total_cost=0.5)
        pos = _make_position(cand_id, [leg])
        cand = _make_candidate(cand_id, [MKT_A], matrix)
        market = _make_market(is_closed=True, yes_price=0.5)

        session = MagicMock()
        session.get.side_effect = lambda cls, pk: (
            cand if str(pk) == cand_id else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            result = svc.scan_and_settle()

        assert result == []

    def test_yes_side_yes_resolution_wins(self):
        cand_id = CAND_ID
        # side=YES, price=0.4, qty=1.0 → win payoff = (1-0.4)*1.0 = 0.6
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        total_cost = 0.4
        matrix = _matrix_json([leg], total_cost=total_cost)
        pos = _make_position(cand_id, [leg])
        cand = _make_candidate(cand_id, [MKT_A], matrix)
        market = _make_market(is_closed=True, yes_price=0.95)  # resolves YES

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        settled_ids = []
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService") as MockAutopsy,
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        close_call = MockTracker.return_value.close_position.call_args
        position_id_arg = close_call[0][0]
        actual_pnl_arg = close_call[0][1]
        assert position_id_arg == str(pos.id)
        # pnl = 0.6 / 0.4 = 1.5, clamped to 1.0
        assert actual_pnl_arg == pytest.approx(1.0)

    def test_no_side_no_resolution_wins(self):
        cand_id = CAND_ID
        # side=NO, price=0.6 (complement of YES=0.4), qty=1.0 → win payoff = (1-0.6)*1.0 = 0.4
        leg = {"market_id": MKT_A, "side": "NO", "price": 0.6, "quantity": 1.0}
        total_cost = 0.6
        matrix = _matrix_json([leg], total_cost=total_cost)
        pos = _make_position(cand_id, [leg])
        cand = _make_candidate(cand_id, [MKT_A], matrix)
        market = _make_market(is_closed=True, yes_price=0.05)  # resolves NO

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        # pnl = 0.4 / 0.6 ≈ 0.6667
        assert actual_pnl_arg == pytest.approx(0.4 / 0.6, abs=1e-4)

    def test_yes_side_no_resolution_loses(self):
        cand_id = CAND_ID
        # side=YES, price=0.4, qty=1.0 → loss payoff = -0.4
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        total_cost = 0.4
        matrix = _matrix_json([leg], total_cost=total_cost)
        pos = _make_position(cand_id, [leg])
        cand = _make_candidate(cand_id, [MKT_A], matrix)
        market = _make_market(is_closed=True, yes_price=0.05)  # resolves NO

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        # pnl = -0.4 / 0.4 = -1.0
        assert actual_pnl_arg == pytest.approx(-1.0)

    def test_multi_leg_pnl_sums_and_normalizes(self):
        cand_id = CAND_ID
        # leg A: side=YES, price=0.4, qty=1.0 → win payoff = 0.6
        # leg B: side=NO, price=0.55, qty=1.0 → win payoff = 0.45
        # total_cost = 0.95, sum_payoff = 1.05, pnl = 1.05/0.95, clamped to 1.0
        leg_a = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        leg_b = {"market_id": MKT_B, "side": "NO", "price": 0.55, "quantity": 1.0}
        total_cost = 0.95
        matrix = _matrix_json([leg_a, leg_b], total_cost=total_cost)
        pos = _make_position(cand_id, [leg_a, leg_b])
        cand = _make_candidate(cand_id, [MKT_A, MKT_B], matrix)
        market_a = _make_market(is_closed=True, yes_price=0.95)  # YES
        market_b = _make_market(is_closed=True, yes_price=0.05)  # NO

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate, RawMarket
        def get_side_effect(cls, pk):
            if cls is OpportunityCandidate:
                return cand
            pk_str = str(pk)
            if pk_str == MKT_A:
                return market_a
            if pk_str == MKT_B:
                return market_b
            return None
        session.get.side_effect = get_side_effect

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService"),
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            result = svc.scan_and_settle()

        assert len(result) == 1
        actual_pnl_arg = MockTracker.return_value.close_position.call_args[0][1]
        # 1.05 / 0.95 > 1.0, clamped to 1.0
        assert actual_pnl_arg == pytest.approx(1.0)

    def test_autopsy_is_recorded_after_close(self):
        cand_id = CAND_ID
        leg = {"market_id": MKT_A, "side": "YES", "price": 0.4, "quantity": 1.0}
        matrix = _matrix_json([leg], total_cost=0.4)
        pos = _make_position(cand_id, [leg])
        cand = _make_candidate(cand_id, [MKT_A], matrix)
        market = _make_market(is_closed=True, yes_price=0.95)

        session = MagicMock()
        from parallax.db.models import OpportunityCandidate
        session.get.side_effect = lambda cls, pk: (
            cand if cls is OpportunityCandidate else (market if str(pk) == MKT_A else None)
        )

        svc = SettlementScannerService(session)
        with (
            patch("parallax.settlement.scanner.TrackerService") as MockTracker,
            patch("parallax.settlement.scanner.AutopsyService") as MockAutopsy,
        ):
            MockTracker.return_value.get_open_positions.return_value = [pos]
            MockTracker.return_value.close_position.return_value = True
            svc.scan_and_settle()

        MockAutopsy.return_value.record.assert_called_once()
        call_kwargs = MockAutopsy.return_value.record.call_args
        assert call_kwargs[0][0] == cand_id or call_kwargs[1].get("candidate_id") == cand_id
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/administrator/tools/parallax
python -m pytest tests/unit/test_settlement_scanner.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'parallax.settlement'`

- [ ] **Step 3: Create `src/parallax/settlement/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `src/parallax/settlement/scanner.py`**

```python
from __future__ import annotations
import logging
import uuid
from sqlalchemy.orm import Session

from parallax.autopsy.service import AutopsyService
from parallax.db.models import OpportunityCandidate, RawMarket
from parallax.shared.schemas import AutopsyLabel, PayoffMatrix, ResolutionType
from parallax.tracker.service import TrackerService

log = logging.getLogger(__name__)

YES_THRESHOLD = 0.9
NO_THRESHOLD = 0.1


def _infer_resolution(yes_price: float) -> str | None:
    """Return 'YES', 'NO', or None when price is ambiguous."""
    if yes_price >= YES_THRESHOLD:
        return "YES"
    if yes_price <= NO_THRESHOLD:
        return "NO"
    return None


def _compute_leg_payoff(side: str, price: float, quantity: float, resolved: str) -> float:
    """Raw dollar payoff for one leg given final resolution."""
    won = (side == resolved)
    if won:
        return (1.0 - price) * quantity
    return -price * quantity


class SettlementScannerService:
    """Scan open paper positions and automatically settle those whose markets have closed."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def scan_and_settle(self) -> list[str]:
        """Return list of settled position IDs."""
        tracker = TrackerService(self._session)
        autopsy = AutopsyService(self._session)
        settled: list[str] = []

        for position in tracker.get_open_positions():
            try:
                position_id = str(position.id)
                candidate_id = str(position.candidate_id)

                candidate = self._session.get(OpportunityCandidate, position.candidate_id)
                if candidate is None:
                    log.warning("scanner: candidate %s not found for position %s", candidate_id, position_id)
                    continue

                matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
                market_ids = {leg.market_id for leg in matrix.legs}

                # Resolve all markets; skip if any are open or ambiguous
                resolutions: dict[str, str] = {}
                skip = False
                for market_id in market_ids:
                    market = self._session.get(RawMarket, market_id)
                    if market is None or not market.is_closed:
                        skip = True
                        break
                    resolved = _infer_resolution(market.outcome_prices[0])
                    if resolved is None:
                        skip = True
                        break
                    resolutions[market_id] = resolved

                if skip:
                    continue

                # Compute PnL
                raw_payoff = sum(
                    _compute_leg_payoff(leg.side, leg.price, leg.quantity, resolutions[leg.market_id])
                    for leg in matrix.legs
                )
                actual_pnl = max(-1.0, min(1.0, raw_payoff / matrix.total_cost))

                # Determine resolution type
                resolution_type = ResolutionType.CORRECT

                closed = tracker.close_position(position_id, actual_pnl)
                if not closed:
                    continue

                autopsy.record(
                    candidate_id=candidate_id,
                    actual_resolution={mid: res for mid, res in resolutions.items()},
                    resolution_type=resolution_type,
                    position_id=position_id,
                    labels=[],
                )

                settled.append(position_id)
                log.info("scanner: settled position %s pnl=%.4f", position_id, actual_pnl)

            except Exception as exc:
                log.warning("scanner: position %s failed: %s", str(position.id), exc)

        return settled
```

- [ ] **Step 5: Run tests and confirm they pass**

```bash
python -m pytest tests/unit/test_settlement_scanner.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 6: Run full unit suite — no regressions**

```bash
python -m pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: `N passed` (no failures).

- [ ] **Step 7: Commit Task 1**

```bash
git add src/parallax/settlement/__init__.py src/parallax/settlement/scanner.py tests/unit/test_settlement_scanner.py
git commit -m "feat(fase-6): SettlementScannerService — resolution inference and PnL computation"
```

---

### Task 2: Wire `SettlementScannerService` into `PipelineRunner.run_once()`

**Files:**
- Modify: `src/parallax/pipeline/runner.py`
- Modify: `tests/unit/test_pipeline_runner.py`

The scanner runs after the candidate evaluation loop commits, within the same `with session_factory() as session` block. It gets its own `begin_nested()` savepoint so a single bad settlement doesn't abort the whole run. Settled count is added to `positions_settled`.

- [ ] **Step 1: Write the failing test**

Open `tests/unit/test_pipeline_runner.py`. Add two tests after the existing replay routing tests:

```python
@pytest.mark.anyio
async def test_run_once_settles_closed_positions(
    runner, session_factory, mock_session
):
    """When scanner finds settleable positions, positions_settled increments."""
    from unittest.mock import MagicMock, patch, AsyncMock
    import uuid

    with (
        patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
        patch("parallax.pipeline.runner.CompilerService"),
        patch("parallax.pipeline.runner.IdentityService"),
        patch("parallax.pipeline.runner.RelationAnalysisService"),
        patch("parallax.pipeline.runner.DivergenceService"),
        patch("parallax.pipeline.runner.CourtService"),
        patch("parallax.pipeline.runner.TrackerService"),
        patch("parallax.pipeline.runner.AuditService"),
        patch("parallax.pipeline.runner.CandidateRepository") as MockRepo,
        patch("parallax.pipeline.runner.ReplayStatisticsService"),
        patch("parallax.pipeline.runner.SettlementScannerService") as MockScanner,
        patch("parallax.pipeline.runner.build_readiness_payload"),
    ):
        MockIngestor.return_value.run_once = AsyncMock(return_value=MagicMock(
            markets_ingested=0, market_counts_by_platform={},
            contracts_compiled=0, events_resolved=0,
            relations_detected=0, candidates_found=0,
        ))
        MockRepo.return_value.list_open.return_value = []
        MockScanner.return_value.scan_and_settle.return_value = ["pos-1", "pos-2"]

        summary = await runner.run_once()

    assert summary.positions_settled == 2


@pytest.mark.anyio
async def test_run_once_scanner_exception_does_not_abort_run(
    runner, session_factory, mock_session
):
    """A scanner failure is caught and the run completes normally."""
    from unittest.mock import MagicMock, patch, AsyncMock

    with (
        patch("parallax.pipeline.runner.IngestorService") as MockIngestor,
        patch("parallax.pipeline.runner.CompilerService"),
        patch("parallax.pipeline.runner.IdentityService"),
        patch("parallax.pipeline.runner.RelationAnalysisService"),
        patch("parallax.pipeline.runner.DivergenceService"),
        patch("parallax.pipeline.runner.CourtService"),
        patch("parallax.pipeline.runner.TrackerService"),
        patch("parallax.pipeline.runner.AuditService"),
        patch("parallax.pipeline.runner.CandidateRepository") as MockRepo,
        patch("parallax.pipeline.runner.ReplayStatisticsService"),
        patch("parallax.pipeline.runner.SettlementScannerService") as MockScanner,
        patch("parallax.pipeline.runner.build_readiness_payload"),
    ):
        MockIngestor.return_value.run_once = AsyncMock(return_value=MagicMock(
            markets_ingested=0, market_counts_by_platform={},
            contracts_compiled=0, events_resolved=0,
            relations_detected=0, candidates_found=0,
        ))
        MockRepo.return_value.list_open.return_value = []
        MockScanner.return_value.scan_and_settle.side_effect = RuntimeError("boom")

        summary = await runner.run_once()

    # Run completed despite scanner error
    assert summary is not None
    assert summary.positions_settled == 0
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
python -m pytest tests/unit/test_pipeline_runner.py::test_run_once_settles_closed_positions tests/unit/test_pipeline_runner.py::test_run_once_scanner_exception_does_not_abort_run -v
```

Expected: `ImportError` or `AttributeError` — `SettlementScannerService` not imported in runner.

- [ ] **Step 3: Wire scanner into `runner.py`**

Add import at top of `src/parallax/pipeline/runner.py` (with other service imports):

```python
from parallax.settlement.scanner import SettlementScannerService
```

Then, in `run_once()`, insert the settlement scan block AFTER the candidate loop's `session.commit()` (line ~349) and BEFORE the `audit_svc.record("pipeline.run.completed", ...)` call:

```python
                # Settlement scan — auto-settle positions whose markets closed
                try:
                    scanner = SettlementScannerService(session)
                    settled_ids = scanner.scan_and_settle()
                    positions_settled += len(settled_ids)
                    if settled_ids:
                        session.commit()
                except Exception as exc:
                    log.warning("pipeline: settlement scan failed: %s", exc)
```

- [ ] **Step 4: Run the two new tests**

```bash
python -m pytest tests/unit/test_pipeline_runner.py::test_run_once_settles_closed_positions tests/unit/test_pipeline_runner.py::test_run_once_scanner_exception_does_not_abort_run -v
```

Expected: both PASS.

- [ ] **Step 5: Run full unit suite — no regressions**

```bash
python -m pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: all previous tests still pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/parallax/pipeline/runner.py tests/unit/test_pipeline_runner.py
git commit -m "feat(fase-6): wire SettlementScannerService into PipelineRunner.run_once()"
```

---

### Task 3: Update `docs/STATUS.md`

**Files:**
- Modify: `docs/STATUS.md`

- [ ] **Step 1: Add the Fase 6 section**

In `docs/STATUS.md`, add the following block after the `## Replay-Based Execution Path (Fase 5 — 2026-05-03)` section and before `## Verified But Still Heuristic`:

```markdown
## Automated Settlement Layer (Fase 6 — 2026-05-03)

Open paper positions are now automatically settled when all underlying markets have closed with deterministic prices:

- `SettlementScannerService` (`src/parallax/settlement/scanner.py`): scans `OPEN` paper positions each pipeline run; skips positions where any market is still open or has an ambiguous final price (0.1 < YES price < 0.9)
- Resolution inference: `outcome_prices[0]` ≥ 0.9 → YES, ≤ 0.1 → NO, else → ambiguous (manual settlement required)
- PnL computation: per-leg win/loss from stored `legs_json`; normalized by `PayoffMatrix.total_cost`; clamped to [-1.0, 1.0]
- Calls `TrackerService.close_position()` + `AutopsyService.record(resolution_type=CORRECT)` per settled position
- `PipelineRunner.run_once()` invokes scanner after the candidate loop; scanner failures are caught and logged without aborting the run
- `positions_settled` in `RunSummary` and `RunProofRecord` now reflects auto-settled positions
```

Also update the `positions_settled` bullet in `## Verified But Still Heuristic`:

Before:
```
- execution simulation defaults to heuristic when `orderbook_enabled=False`; snapshot path available when enabled
```

After (add new bullet before that line):
```
- settlement scanner only infers resolution from `outcome_prices[0]`; unusual oracle formats (multi-outcome, scaled) require manual settlement
```

- [ ] **Step 2: Commit Task 3**

```bash
git add docs/STATUS.md
git commit -m "docs: document Fase 6 automated settlement layer in STATUS.md"
```

---

## Self-Review

**Spec coverage:**
- Resolution inference from `outcome_prices[0]` → Task 1 ✓
- Per-leg PnL computation → Task 1 ✓
- `TrackerService.close_position()` + `AutopsyService.record()` → Task 1 ✓
- Wire into pipeline runner → Task 2 ✓
- `positions_settled` counter updates → Task 2 ✓
- Scanner failure isolation → Task 2 ✓
- STATUS.md → Task 3 ✓

**Placeholder scan:** None — all steps have code.

**Type consistency:**
- `SettlementScannerService.__init__(session: Session)` used consistently across tasks
- `scan_and_settle() -> list[str]` (position IDs) used in both implementation and test assertions
- `ResolutionType.CORRECT` from `parallax.shared.schemas` — consistent with `AutopsyService.record()` signature
- `TrackerService.close_position(position_id: str, actual_pnl: float)` — matches tracker service exactly
