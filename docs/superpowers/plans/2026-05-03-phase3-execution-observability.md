# Fase 3 — Execution Observability Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Fase 1+2 snapshot execution path visible — in `/api/ops/execution`, `/ready`, `CandidateSummary`, and the UI — so operators can confirm snapshot-based court evaluation is firing and see coverage metrics.

**Architecture:** New `ExecutionReportService` queries `venue_tokens` and `orderbook_snapshots` plus the last 500 `candidate_decision_snapshots` to build an `ExecutionReport`; this is served at `/api/ops/execution`. `ReadinessReport` grows two fields (`orderbook_enabled`, `venue_token_count`). `CandidateSummary` gains `execution_model` via a batch join in `CandidateReadService`. UI surfaces the new fields in `CandidateDetail.tsx` (execution section) and `OperationsView.tsx` (new coverage panel).

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 sync, Pydantic v2, FastAPI, React + TypeScript (Vite).

---

### File Map

**Create:**
- `src/parallax/ops/execution_report.py` — `ExecutionReportService.build(session) -> ExecutionReport`
- `tests/unit/test_ops_execution_report.py`

**Modify:**
- `src/parallax/ops/schemas.py` — add `ExecutionCoverageStats`, `ExecutionReport`
- `src/parallax/api/routes/ops.py` — add `GET /ops/execution`
- `src/parallax/api/app.py` — no change needed (route already on router)
- `src/parallax/ops/runtime.py` — add `orderbook_enabled`, `venue_token_count` to readiness build
- `src/parallax/shared/schemas.py` — add `execution_model` field to `CandidateSummary`
- `src/parallax/candidates/service.py` — batch-load execution_model into summaries
- `ui/src/components/CandidateDetail.tsx` — render execution_model badge + new fields
- `ui/src/components/OperationsView.tsx` — fetch and render execution coverage panel
- `docs/STATUS.md` — document Fase 3
- `docs/RUNTIME.md` — add `/api/ops/execution` to API contract

---

### Task 1: `ExecutionReport` schema

**Files:**
- Modify: `src/parallax/ops/schemas.py`
- Test: `tests/unit/test_ops_execution_report.py` (partial — import only at this step)

- [ ] **Step 1: Write a failing import test**

```python
def test_execution_report_schema_importable():
    from parallax.ops.schemas import ExecutionCoverageStats, ExecutionReport
    r = ExecutionReport(
        orderbook_enabled=True,
        coverage=[
            ExecutionCoverageStats(
                platform="polymarket",
                venue_token_count=42,
                snapshot_count=10,
                latest_snapshot_at=None,
            )
        ],
        total_venue_tokens=42,
        total_snapshots=10,
        execution_model_distribution={"heuristic": 8, "snapshot_based": 2},
        avg_quote_staleness_seconds=12.5,
        depth_support_rate=0.9,
    )
    assert r.total_venue_tokens == 42
    assert r.execution_model_distribution["snapshot_based"] == 2
```

Run: `uv run pytest tests/unit/test_ops_execution_report.py::test_execution_report_schema_importable -v`
Expected: FAIL — `ImportError: cannot import name 'ExecutionCoverageStats'`

- [ ] **Step 2: Add schemas**

In `src/parallax/ops/schemas.py`, after the `OpsMetricsResponse` class, add:

```python
class ExecutionCoverageStats(BaseModel):
    platform: str
    venue_token_count: int
    snapshot_count: int
    latest_snapshot_at: datetime | None = None


class ExecutionReport(BaseModel):
    orderbook_enabled: bool
    coverage: list[ExecutionCoverageStats]
    total_venue_tokens: int
    total_snapshots: int
    execution_model_distribution: dict[str, int]
    avg_quote_staleness_seconds: float | None = None
    depth_support_rate: float | None = None
    report_basis: str = "last_500_evaluations"
```

- [ ] **Step 3: Run test**

```bash
uv run pytest tests/unit/test_ops_execution_report.py::test_execution_report_schema_importable -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/parallax/ops/schemas.py tests/unit/test_ops_execution_report.py
git commit -m "feat(observability): add ExecutionReport schema"
```

---

### Task 2: `ExecutionReportService`

**Files:**
- Create: `src/parallax/ops/execution_report.py`
- Test: `tests/unit/test_ops_execution_report.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_ops_execution_report.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _make_sim_json(execution_model="heuristic", staleness=None, depth_support=None):
    d = {"execution_model": execution_model, "quote_staleness_seconds": staleness}
    if depth_support is not None:
        d["depth_support"] = depth_support
    return d


def test_execution_report_service_empty_db():
    from parallax.ops.execution_report import ExecutionReportService

    session = MagicMock()
    # venue_token query returns empty
    vt_result = MagicMock()
    vt_result.all.return_value = []
    # snapshot query returns empty
    snap_result = MagicMock()
    snap_result.all.return_value = []
    # decision snapshot query returns empty
    ds_result = MagicMock()
    ds_result.scalars.return_value = MagicMock()
    ds_result.scalars.return_value.all.return_value = []

    session.execute.side_effect = [vt_result, snap_result, ds_result]

    report = ExecutionReportService.build(session)
    assert report.total_venue_tokens == 0
    assert report.total_snapshots == 0
    assert report.execution_model_distribution == {}
    assert report.avg_quote_staleness_seconds is None
    assert report.depth_support_rate is None


def test_execution_report_service_computes_distribution():
    from parallax.ops.execution_report import ExecutionReportService
    from parallax.config import settings

    session = MagicMock()

    vt_result = MagicMock()
    vt_result.all.return_value = [("polymarket", 5)]

    snap_result = MagicMock()
    ts = datetime(2026, 5, 3, tzinfo=timezone.utc)
    snap_result.all.return_value = [("polymarket", 3, ts)]

    ds_result = MagicMock()
    ds_result.scalars.return_value = MagicMock()
    ds_result.scalars.return_value.all.return_value = [
        _make_sim_json("snapshot_based", staleness=10.0, depth_support=True),
        _make_sim_json("snapshot_based", staleness=20.0, depth_support=False),
        _make_sim_json("heuristic"),
    ]

    session.execute.side_effect = [vt_result, snap_result, ds_result]

    report = ExecutionReportService.build(session)

    assert report.total_venue_tokens == 5
    assert report.total_snapshots == 3
    assert report.execution_model_distribution["snapshot_based"] == 2
    assert report.execution_model_distribution["heuristic"] == 1
    assert report.avg_quote_staleness_seconds == 15.0
    assert report.depth_support_rate == 0.5
    assert report.coverage[0].platform == "polymarket"
    assert report.coverage[0].venue_token_count == 5
```

Run: `uv run pytest tests/unit/test_ops_execution_report.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 2: Implement `ExecutionReportService`**

Create `src/parallax/ops/execution_report.py`:

```python
from __future__ import annotations

from datetime import datetime
from sqlalchemy import select, func, desc
from sqlalchemy.orm import Session

from parallax.config import settings
from parallax.db.models import VenueToken, OrderbookSnapshotRecord, CandidateDecisionSnapshot
from parallax.ops.schemas import ExecutionCoverageStats, ExecutionReport


class ExecutionReportService:
    @staticmethod
    def build(session: Session) -> ExecutionReport:
        vt_rows = session.execute(
            select(VenueToken.platform, func.count(VenueToken.id)).group_by(VenueToken.platform)
        ).all()
        vt_by_platform: dict[str, int] = {str(p): int(c) for p, c in vt_rows}

        snap_rows = session.execute(
            select(
                OrderbookSnapshotRecord.platform,
                func.count(OrderbookSnapshotRecord.id),
                func.max(OrderbookSnapshotRecord.captured_at),
            ).group_by(OrderbookSnapshotRecord.platform)
        ).all()
        snap_by_platform: dict[str, tuple[int, datetime | None]] = {
            str(p): (int(c), latest) for p, c, latest in snap_rows
        }

        all_platforms = sorted(set(vt_by_platform) | set(snap_by_platform))
        coverage = [
            ExecutionCoverageStats(
                platform=p,
                venue_token_count=vt_by_platform.get(p, 0),
                snapshot_count=snap_by_platform.get(p, (0, None))[0],
                latest_snapshot_at=snap_by_platform.get(p, (0, None))[1],
            )
            for p in all_platforms
        ]

        sim_jsons = session.execute(
            select(CandidateDecisionSnapshot.simulation_result)
            .where(CandidateDecisionSnapshot.simulation_result.isnot(None))
            .order_by(desc(CandidateDecisionSnapshot.evaluated_at))
            .limit(500)
        ).scalars().all()

        model_counts: dict[str, int] = {}
        staleness_values: list[float] = []
        depth_true = 0
        depth_total = 0

        for sim in sim_jsons:
            if not isinstance(sim, dict):
                continue
            em = sim.get("execution_model", "heuristic")
            model_counts[em] = model_counts.get(em, 0) + 1
            qs = sim.get("quote_staleness_seconds")
            if qs is not None:
                staleness_values.append(float(qs))
            ds = sim.get("depth_support")
            if ds is not None:
                depth_total += 1
                if ds:
                    depth_true += 1

        return ExecutionReport(
            orderbook_enabled=settings.orderbook_enabled,
            coverage=coverage,
            total_venue_tokens=sum(vt_by_platform.values()),
            total_snapshots=sum(c for c, _ in snap_by_platform.values()),
            execution_model_distribution=model_counts,
            avg_quote_staleness_seconds=sum(staleness_values) / len(staleness_values) if staleness_values else None,
            depth_support_rate=depth_true / depth_total if depth_total > 0 else None,
        )
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_ops_execution_report.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add src/parallax/ops/execution_report.py tests/unit/test_ops_execution_report.py
git commit -m "feat(observability): ExecutionReportService — snapshot coverage stats"
```

---

### Task 3: `/api/ops/execution` route

**Files:**
- Modify: `src/parallax/api/routes/ops.py`
- Test: `tests/unit/test_api_routes.py`

- [ ] **Step 1: Write failing test**

In `tests/unit/test_api_routes.py`, append:

```python
def test_ops_execution_route_returns_200(client):
    from unittest.mock import patch, MagicMock
    from parallax.ops.schemas import ExecutionReport
    mock_report = ExecutionReport(
        orderbook_enabled=False,
        coverage=[],
        total_venue_tokens=0,
        total_snapshots=0,
        execution_model_distribution={},
    )
    with patch("parallax.api.routes.ops.ExecutionReportService") as mock_svc:
        mock_svc.build.return_value = mock_report
        resp = client.get("/api/ops/execution")
    assert resp.status_code == 200
    data = resp.json()
    assert "orderbook_enabled" in data
    assert "execution_model_distribution" in data
```

Run: `uv run pytest tests/unit/test_api_routes.py::test_ops_execution_route_returns_200 -v`
Expected: FAIL — 404 (route not registered)

- [ ] **Step 2: Add route**

In `src/parallax/api/routes/ops.py`, add import at top:

```python
from parallax.ops.execution_report import ExecutionReportService
from parallax.ops.schemas import ExecutionReport
```

Append route after the last existing route:

```python
@router.get("/ops/execution", response_model=ExecutionReport)
def get_execution_report(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> ExecutionReport:
    return ExecutionReportService.build(session)
```

- [ ] **Step 3: Run test**

```bash
uv run pytest tests/unit/test_api_routes.py::test_ops_execution_route_returns_200 -v
```

Expected: PASS

- [ ] **Step 4: Run full unit suite**

```bash
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/parallax/api/routes/ops.py tests/unit/test_api_routes.py
git commit -m "feat(observability): GET /api/ops/execution route"
```

---

### Task 4: Readiness report — orderbook fields

**Files:**
- Modify: `src/parallax/ops/schemas.py` (add fields to `ReadinessReport`)
- Modify: `src/parallax/ops/runtime.py` (populate in `build_readiness_payload`)
- Test: `tests/unit/test_pipeline_runner.py` or a new unit test

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_ops_execution_report.py`:

```python
def test_readiness_report_has_orderbook_fields():
    from parallax.ops.schemas import ReadinessReport
    import inspect
    fields = ReadinessReport.model_fields
    assert "orderbook_enabled" in fields
    assert "venue_token_count" in fields
```

Run: `uv run pytest tests/unit/test_ops_execution_report.py::test_readiness_report_has_orderbook_fields -v`
Expected: FAIL

- [ ] **Step 2: Add fields to `ReadinessReport`**

In `src/parallax/ops/schemas.py`, update `ReadinessReport`:

```python
class ReadinessReport(BaseModel):
    status: str
    database: str
    degraded_reasons: list[str] = Field(default_factory=list)
    controls: RuntimeControlState
    checks: dict[str, object]
    orderbook_enabled: bool = False
    venue_token_count: int = 0
```

- [ ] **Step 3: Populate in `build_readiness_payload`**

In `src/parallax/ops/runtime.py`, add imports at the top (after existing imports):

```python
from parallax.db.models import VenueToken
```

In `build_readiness_payload`, before the `return ReadinessReport(...)` call, add:

```python
from sqlalchemy import func as sa_func
venue_token_count = session.execute(
    sa_select(sa_func.count(VenueToken.id))
).scalar_one() or 0
```

Then add to the `ReadinessReport(...)` constructor:

```python
orderbook_enabled=settings.orderbook_enabled,
venue_token_count=venue_token_count,
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_ops_execution_report.py -v
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/parallax/ops/schemas.py src/parallax/ops/runtime.py tests/unit/test_ops_execution_report.py
git commit -m "feat(observability): add orderbook_enabled + venue_token_count to ReadinessReport"
```

---

### Task 5: `CandidateSummary.execution_model`

**Files:**
- Modify: `src/parallax/shared/schemas.py`
- Modify: `src/parallax/candidates/service.py`
- Test: `tests/unit/test_api_routes.py`

The summary batch must not cause N+1 queries. Strategy: after `list_open()`, fetch all decision snapshot simulation_results in one query keyed by candidate_id, then look up per row.

- [ ] **Step 1: Write failing test**

Append to `tests/unit/test_api_routes.py`:

```python
def test_candidate_summary_includes_execution_model(client):
    from unittest.mock import patch, MagicMock
    from parallax.shared.schemas import CandidateSummary, CourtDecision, OpportunityType
    from datetime import datetime, timezone

    mock_summary = CandidateSummary(
        id="cand-1",
        opportunity_type=OpportunityType.PURE_ARBITRAGE,
        worst_case_payoff=0.05,
        total_cost=45.0,
        court_decision=CourtDecision.WATCHLIST,
        created_at=datetime.now(timezone.utc),
        execution_model="snapshot_based",
    )
    with patch("parallax.api.routes.candidates.CandidateReadService") as mock_svc:
        mock_svc.return_value.list_open_summaries.return_value = [mock_summary]
        resp = client.get("/api/candidates")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["execution_model"] == "snapshot_based"
```

Run: `uv run pytest tests/unit/test_api_routes.py::test_candidate_summary_includes_execution_model -v`
Expected: FAIL — `execution_model` field not on `CandidateSummary`

- [ ] **Step 2: Add field to `CandidateSummary`**

In `src/parallax/shared/schemas.py`, update `CandidateSummary`:

```python
class CandidateSummary(BaseModel):
    id: str
    opportunity_type: OpportunityType
    worst_case_payoff: float
    total_cost: float
    court_decision: CourtDecision
    created_at: datetime
    execution_model: Literal["heuristic", "snapshot_based", "replay_based", "degraded"] | None = None
```

- [ ] **Step 3: Populate `execution_model` in `list_open_summaries`**

In `src/parallax/candidates/service.py`, update `list_open_summaries`:

```python
def list_open_summaries(self, *, limit: int = 100, offset: int = 0) -> list[CandidateSummary]:
    from parallax.db.models import CandidateDecisionSnapshot
    from sqlalchemy import select
    import uuid as _uuid

    rows = self._repo.list_open(limit=limit, offset=offset)
    if not rows:
        return []

    candidate_ids = [row.id for row in rows]
    snap_rows = self._session.execute(
        select(
            CandidateDecisionSnapshot.candidate_id,
            CandidateDecisionSnapshot.simulation_result,
        ).where(CandidateDecisionSnapshot.candidate_id.in_(candidate_ids))
    ).all()
    em_by_id: dict = {
        str(cid): (sim.get("execution_model") if isinstance(sim, dict) else None)
        for cid, sim in snap_rows
    }

    return [
        CandidateSummary(
            id=str(row.id),
            opportunity_type=OpportunityType(row.opportunity_type),
            worst_case_payoff=row.worst_case_payoff,
            total_cost=PayoffMatrix.model_validate(row.payoff_matrix).total_cost,
            court_decision=CourtDecision(row.court_decision),
            created_at=row.detected_at,
            execution_model=em_by_id.get(str(row.id)),
        )
        for row in rows
    ]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_api_routes.py -v --tb=short
uv run pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/parallax/shared/schemas.py src/parallax/candidates/service.py tests/unit/test_api_routes.py
git commit -m "feat(observability): add execution_model to CandidateSummary"
```

---

### Task 6: UI — `CandidateDetail.tsx` execution section

**Files:**
- Modify: `ui/src/components/CandidateDetail.tsx`

No backend changes. The new fields (`execution_model`, `depth_support`, `quote_staleness_seconds`, `partial_fill_risk`) are already in `SimulationResult` returned by the API — they just need rendering.

- [ ] **Step 1: Read the current execution section**

Lines 102–138 of `CandidateDetail.tsx` render the Execution card. The simulation object has:
- `execution_model: string` (currently not rendered)
- `depth_support: boolean | null` (currently not rendered)
- `quote_staleness_seconds: number | null` (currently not rendered)
- `partial_fill_risk: number` (currently not rendered)

- [ ] **Step 2: Add execution_model badge and new metric lines**

After the existing `<Metric label="Model" value={simulation.model_version} />` line, add:

```tsx
<Metric
  label="Exec model"
  value={simulation.execution_model ?? "heuristic"}
/>
{simulation.depth_support !== null && simulation.depth_support !== undefined && (
  <Metric
    label="Depth support"
    value={simulation.depth_support ? "yes" : "no"}
  />
)}
{simulation.quote_staleness_seconds !== null && simulation.quote_staleness_seconds !== undefined && (
  <Metric
    label="Quote age"
    value={`${simulation.quote_staleness_seconds.toFixed(1)}s`}
  />
)}
{simulation.partial_fill_risk > 0 && (
  <Metric
    label="Partial fill risk"
    value={`${(simulation.partial_fill_risk * 100).toFixed(1)}%`}
  />
)}
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd /home/administrator/tools/parallax/ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
cd /home/administrator/tools/parallax
git add ui/src/components/CandidateDetail.tsx
git commit -m "feat(observability): render execution_model, depth_support, staleness in CandidateDetail"
```

---

### Task 7: UI — `OperationsView.tsx` execution coverage panel

**Files:**
- Modify: `ui/src/components/OperationsView.tsx`

Fetch `/api/ops/execution` and render a compact coverage panel next to the existing metrics.

- [ ] **Step 1: Add execution report fetch**

In `OperationsView.tsx`, alongside the existing `useEffect` that fetches `/api/ops/metrics`, add a parallel fetch for `/api/ops/execution`. Use the same pattern as other fetches in the file.

Find the existing state declarations (e.g. `const [metrics, setMetrics] = useState(null)`) and add:

```tsx
const [execReport, setExecReport] = useState<any>(null);
```

In the `useEffect` fetch block, add:

```tsx
fetch("/api/ops/execution")
  .then((r) => r.ok ? r.json() : null)
  .then(setExecReport)
  .catch(() => {});
```

- [ ] **Step 2: Add execution coverage panel**

Find a logical place in the rendered JSX (e.g., after the "Pipeline Activity" section, before "Policy") and add:

```tsx
{execReport && (
  <section style={cardStyle}>
    <h3 style={{ marginTop: 0 }}>Execution Coverage</h3>
    <div style={{ color: execReport.orderbook_enabled ? "#6ddc9b" : "#9fb4ca", marginBottom: 8 }}>
      orderbook {execReport.orderbook_enabled ? "enabled" : "disabled"}
    </div>
    {execReport.coverage.map((c: any) => (
      <div key={c.platform} style={{ marginBottom: 4 }}>
        <span style={{ color: "#bfd3ea" }}>{c.platform}</span>
        {" — "}
        <span style={{ color: "#9fb4ca" }}>{c.venue_token_count} tokens · {c.snapshot_count} snapshots</span>
        {c.latest_snapshot_at && (
          <span style={{ color: "#6b829a", marginLeft: 8 }}>
            last {new Date(c.latest_snapshot_at).toLocaleString()}
          </span>
        )}
      </div>
    ))}
    {Object.keys(execReport.execution_model_distribution).length > 0 && (
      <div style={{ marginTop: 8 }}>
        {Object.entries(execReport.execution_model_distribution).map(([model, count]: [string, any]) => (
          <div key={model} style={{ color: "#9fb4ca" }}>
            {model}: {count}
          </div>
        ))}
      </div>
    )}
    {execReport.avg_quote_staleness_seconds !== null && (
      <div style={{ color: "#9fb4ca", marginTop: 6 }}>
        avg staleness {execReport.avg_quote_staleness_seconds.toFixed(1)}s
        {execReport.depth_support_rate !== null && ` · depth support ${(execReport.depth_support_rate * 100).toFixed(0)}%`}
      </div>
    )}
  </section>
)}
```

- [ ] **Step 3: TypeScript check**

```bash
cd /home/administrator/tools/parallax/ui && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
cd /home/administrator/tools/parallax
git add ui/src/components/OperationsView.tsx
git commit -m "feat(observability): execution coverage panel in OperationsView"
```

---

### Task 8: Docs + full validation

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/RUNTIME.md`

- [ ] **Step 1: Full unit suite**

```bash
cd /home/administrator/tools/parallax
uv run pytest tests/unit/ -q --tb=short 2>&1 | tail -5
```

Expected: all pass (no regressions from ~246 baseline)

- [ ] **Step 2: TypeScript production build**

```bash
cd /home/administrator/tools/parallax/ui && npm run build 2>&1 | tail -10
```

Expected: `dist/` created with no type errors

- [ ] **Step 3: Update `docs/STATUS.md`**

Add after the "Token Discovery Layer (Fase 2)" section:

```markdown
## Execution Observability Layer (Fase 3 — 2026-05-03)

The snapshot execution path is now visible across the ops surface, readiness report, and UI:

- `GET /api/ops/execution`: `ExecutionReport` with `venue_tokens` coverage by platform, `orderbook_snapshots` stats, execution_model distribution from last 500 decision snapshots, avg quote staleness, depth support rate
- `ReadinessReport` now carries `orderbook_enabled` and `venue_token_count`
- `CandidateSummary` carries `execution_model` (batch-loaded from decision snapshots, no N+1)
- `CandidateDetail.tsx`: Execution section now renders `execution_model`, `depth_support`, `quote_staleness_seconds`, `partial_fill_risk`
- `OperationsView.tsx`: Execution Coverage panel fetches `/api/ops/execution` and shows per-platform token/snapshot counts, staleness, and model distribution
```

- [ ] **Step 4: Update `docs/RUNTIME.md`**

Add `GET /api/ops/execution` to the Read routes list and describe it in the Ops Contract section.

- [ ] **Step 5: Commit**

```bash
git add docs/STATUS.md docs/RUNTIME.md
git commit -m "docs: document Fase 3 Execution Observability Layer"
```
