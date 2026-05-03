# Fase 8 — End-to-End Real-Data Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the infrastructure to capture and verify an end-to-end real-data pipeline run, then execute the proof once credentials are available.

**Architecture:** Three code changes support the proof: (1) a `GET /api/ops/proof` endpoint that aggregates all evidence surfaces into a self-evaluating `ProofBundleReport`; (2) two new Makefile targets (`make test-smoke`, `make proof`); (3) an updated RUNBOOK.md that folds in all Fase 1–7 additions. The proof itself (Task 4) is the human-executed real-data run — it requires `ANTHROPIC_API_KEY` in `.env` and a running DB, and produces a `docs/proof-<timestamp>.json` artifact.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, Pydantic v2. No new dependencies.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/parallax/ops/schemas.py` | Add `ProofCheckItem`, `ProofBundleReport` |
| Modify | `src/parallax/ops/service.py` | Add `get_proof_bundle_payload()` |
| Modify | `src/parallax/api/routes/ops.py` | Add `GET /api/ops/proof` route |
| Modify | `tests/unit/test_api_routes.py` | Add proof route test |
| Modify | `Makefile` | Add `test-smoke` and `proof` targets |
| Modify | `docs/RUNBOOK.md` | Update P0.2 with all Fase 1–7 surfaces |
| Modify | `docs/STATUS.md` | Document proof infrastructure; mark once proof runs |

---

### Task 1: `ProofBundleReport` model + `GET /api/ops/proof` endpoint

**Files:**
- Modify: `src/parallax/ops/schemas.py`
- Modify: `src/parallax/ops/service.py`
- Modify: `src/parallax/api/routes/ops.py`
- Test: `tests/unit/test_api_routes.py`

The proof bundle aggregates four existing services: `build_readiness_payload`, `list_run_proofs_payload`, `get_ops_metrics_payload`. It builds a checklist from the combined data and returns `bundle_status = "complete"` only when all checklist items pass.

**Checklist items** (evaluated server-side):
| name | passes when |
|------|-------------|
| `database_ok` | `readiness.database == "ok"` |
| `polymarket_ingested` | `market_counts_by_platform.get("polymarket", 0) > 0` |
| `kalshi_ingested` | `market_counts_by_platform.get("kalshi", 0) > 0` |
| `compilation_ran` | latest run has `contracts_compiled > 0` |
| `relations_detected` | latest run has `relations_detected > 0` |
| `run_proof_exists` | at least one `RunProof` is persisted |
| `semantic_ok` | `readiness.checks` contains a semantic entry with `status == "ok"` |

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_api_routes.py` (after existing ops tests):

```python
def test_get_proof_bundle_returns_200(client):
    from unittest.mock import patch, MagicMock
    from parallax.ops.schemas import ProofBundleReport, ProofCheckItem

    bundle = ProofBundleReport(
        captured_at=datetime.now(timezone.utc),
        readiness_status="ok",
        market_counts_by_platform={"polymarket": 5, "kalshi": 3},
        total_markets=8,
        total_candidates=2,
        open_positions=1,
        contracts_compiled_last_run=4,
        relations_detected_last_run=3,
        run_proof_exists=True,
        proof_checklist=[
            ProofCheckItem(name="database_ok", passed=True, evidence="database=ok"),
            ProofCheckItem(name="polymarket_ingested", passed=True, evidence="5 markets"),
            ProofCheckItem(name="kalshi_ingested", passed=True, evidence="3 markets"),
            ProofCheckItem(name="compilation_ran", passed=True, evidence="4 contracts"),
            ProofCheckItem(name="relations_detected", passed=True, evidence="3 relations"),
            ProofCheckItem(name="run_proof_exists", passed=True, evidence="run persisted"),
            ProofCheckItem(name="semantic_ok", passed=False, evidence="semantic: not configured"),
        ],
        bundle_status="partial",
    )

    with patch("parallax.api.routes.ops.get_proof_bundle_payload", return_value=bundle):
        resp = client.get("/api/ops/proof")

    assert resp.status_code == 200
    data = resp.json()
    assert data["bundle_status"] in {"complete", "partial"}
    assert "proof_checklist" in data
    assert len(data["proof_checklist"]) == 7
```

Note: `client` fixture is already defined in the test file. Add `from datetime import datetime, timezone` if not already imported.

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/administrator/tools/parallax
.venv/bin/python -m pytest tests/unit/test_api_routes.py::test_get_proof_bundle_returns_200 -v 2>&1 | tail -15
```

Expected: `ImportError` — `ProofBundleReport` not defined yet.

- [ ] **Step 3: Add `ProofCheckItem` and `ProofBundleReport` to `src/parallax/ops/schemas.py`**

Add after the `OpsMetricsResponse` class (search for `class OpsMetricsResponse` and add after it):

```python
class ProofCheckItem(BaseModel):
    name: str
    passed: bool
    evidence: str


class ProofBundleReport(BaseModel):
    captured_at: datetime
    readiness_status: str
    market_counts_by_platform: dict[str, int] = Field(default_factory=dict)
    total_markets: int = 0
    total_candidates: int = 0
    open_positions: int = 0
    contracts_compiled_last_run: int = 0
    relations_detected_last_run: int = 0
    run_proof_exists: bool = False
    proof_checklist: list[ProofCheckItem] = Field(default_factory=list)
    bundle_status: str = "partial"   # "complete" when all checklist items pass
    bundle_version: str = "proof-bundle-v1"
```

- [ ] **Step 4: Add `get_proof_bundle_payload` to `src/parallax/ops/service.py`**

Add at the end of the file:

```python
def get_proof_bundle_payload(session: Session) -> "ProofBundleReport":
    from datetime import datetime, timezone
    from parallax.ops.runtime import build_readiness_payload
    from parallax.ops.schemas import ProofBundleReport, ProofCheckItem

    readiness = build_readiness_payload(session)
    runs = list_run_proofs_payload(session, limit=1).runs
    latest_run = runs[0] if runs else None
    metrics = get_ops_metrics_payload(session)

    market_counts = metrics.market_counts_by_platform
    total_markets = sum(market_counts.values())
    total_candidates = metrics.total_candidates
    open_positions = metrics.open_positions

    contracts_compiled = latest_run.contracts_compiled if latest_run else 0
    relations_detected = latest_run.relations_detected if latest_run else 0

    semantic_check = readiness.checks.get("semantic") or {}
    semantic_status = (
        semantic_check.get("status", "unknown")
        if isinstance(semantic_check, dict)
        else getattr(semantic_check, "status", "unknown")
    )

    checklist = [
        ProofCheckItem(
            name="database_ok",
            passed=readiness.database == "ok",
            evidence=f"database={readiness.database}",
        ),
        ProofCheckItem(
            name="polymarket_ingested",
            passed=market_counts.get("polymarket", 0) > 0,
            evidence=f"{market_counts.get('polymarket', 0)} polymarket markets",
        ),
        ProofCheckItem(
            name="kalshi_ingested",
            passed=market_counts.get("kalshi", 0) > 0,
            evidence=f"{market_counts.get('kalshi', 0)} kalshi markets",
        ),
        ProofCheckItem(
            name="compilation_ran",
            passed=contracts_compiled > 0,
            evidence=f"{contracts_compiled} contracts compiled in last run",
        ),
        ProofCheckItem(
            name="relations_detected",
            passed=relations_detected > 0,
            evidence=f"{relations_detected} relations in last run",
        ),
        ProofCheckItem(
            name="run_proof_exists",
            passed=latest_run is not None,
            evidence="run persisted" if latest_run else "no run proof found",
        ),
        ProofCheckItem(
            name="semantic_ok",
            passed=semantic_status == "ok",
            evidence=f"semantic: {semantic_status}",
        ),
    ]

    all_pass = all(item.passed for item in checklist)
    return ProofBundleReport(
        captured_at=datetime.now(timezone.utc),
        readiness_status=readiness.status,
        market_counts_by_platform=market_counts,
        total_markets=total_markets,
        total_candidates=total_candidates,
        open_positions=open_positions,
        contracts_compiled_last_run=contracts_compiled,
        relations_detected_last_run=relations_detected,
        run_proof_exists=latest_run is not None,
        proof_checklist=checklist,
        bundle_status="complete" if all_pass else "partial",
    )
```

- [ ] **Step 5: Add import to `src/parallax/ops/service.py`**

The `get_proof_bundle_payload` function uses lazy imports inside the function body to avoid circular imports. No top-level import changes needed. Verify `OpsMetricsResponse` has `market_counts_by_platform`, `total_candidates`, and `open_positions` by checking the existing `get_ops_metrics_payload` return value.

```bash
grep -n "total_candidates\|open_positions\|market_counts_by_platform" src/parallax/ops/schemas.py | head -10
```

If `OpsMetricsResponse` does not have `total_candidates` as a top-level field, read `OpsMetricsResponse` definition and use `metrics.pipeline_metrics.open_positions` or the equivalent nested path instead.

- [ ] **Step 6: Add route to `src/parallax/api/routes/ops.py`**

Add to imports:

```python
from parallax.ops.schemas import (
    BacktestReplayReport,
    EvaluationReport,
    ExecutionReport,
    IdentityReviewQueueResponse,
    OpsMetricsResponse,
    PolicyReport,
    ProofBundleReport,
    RelationSetListResponse,
    RunProof,
    RunProofListResponse,
)
```

Also add to service imports:

```python
from parallax.ops.service import (
    get_backtest_replay_payload,
    get_evaluation_report_payload,
    get_identity_review_queue_payload,
    get_ops_metrics_payload,
    get_proof_bundle_payload,
    get_relation_set_payload,
    get_run_proof_payload,
    list_relation_sets_payload,
    list_run_proofs_payload,
)
```

Add the route after the `get_execution_report` route at the end of the file:

```python
@router.get("/ops/proof", response_model=ProofBundleReport)
def get_proof_bundle(
    _auth: None = Depends(require_read_access),
    session: Session = Depends(get_read_session),
) -> ProofBundleReport:
    return get_proof_bundle_payload(session)
```

- [ ] **Step 7: Run the new test**

```bash
.venv/bin/python -m pytest tests/unit/test_api_routes.py::test_get_proof_bundle_returns_200 -v 2>&1 | tail -15
```

Expected: PASS.

If `OpsMetricsResponse` doesn't have a flat `total_candidates` or `open_positions`, fix the service function to use the correct nested path (e.g., `metrics.pipeline_metrics.open_positions`).

- [ ] **Step 8: Full unit suite — no regressions**

```bash
.venv/bin/python -m pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: `N passed`.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/parallax/ops/schemas.py src/parallax/ops/service.py src/parallax/api/routes/ops.py tests/unit/test_api_routes.py
git commit -m "feat(fase-8): GET /api/ops/proof — self-evaluating proof bundle endpoint"
```

---

### Task 2: Makefile targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add `test-smoke` and `proof` targets**

Current Makefile ends with:
```makefile
verify-integration:
	$(UV) run pytest tests/integration/test_pipeline_integration.py -v -m integration
```

Add after it:

```makefile
test-smoke:
	SMOKE_CLOB=1 $(UV) run pytest tests/smoke/ -v
proof:
	$(UV) run python -m parallax.pipeline.runner
	@echo ""
	@echo "Pipeline complete. If the API is running on port 8000, capture proof with:"
	@echo "  curl -s http://127.0.0.1:8000/api/ops/proof | python3 -m json.tool > docs/proof-$$(date +%Y%m%d-%H%M%S).json"
```

- [ ] **Step 2: Verify targets are syntactically valid**

```bash
make -n proof 2>&1
make -n test-smoke 2>&1
```

Expected: prints the commands without executing them (dry run).

- [ ] **Step 3: Commit Task 2**

```bash
git add Makefile
git commit -m "feat(fase-8): add make test-smoke and make proof targets"
```

---

### Task 3: Update `docs/RUNBOOK.md`

**Files:**
- Modify: `docs/RUNBOOK.md`

The RUNBOOK currently covers P0.1 (integration test) and P0.2 (real-data run) but does not mention:
- The smoke test suite (Fase 7)
- The `GET /api/ops/proof` endpoint (Fase 8)
- The `GET /api/ops/execution` surface (Fase 3)
- Automated settlement (Fase 6)

- [ ] **Step 1: Add smoke test section before P0.2**

After the `### What P0.1 Does Not Prove` section and before `## P0.2: Recent Real-Data Runtime Proof`, insert:

```markdown
## P0.1b: CLOB Adapter Smoke Test

Run to verify live Polymarket CLOB connectivity (no credentials required):

```bash
SMOKE_CLOB=1 uv run pytest tests/smoke/ -v
```

With Kalshi API key (optional):

```bash
SMOKE_CLOB=1 KALSHI_API_KEY=<key> SMOKE_KALSHI_TICKER=<ticker> \
  uv run pytest tests/smoke/ -v
```

This confirms the Polymarket CLOB adapter returns a valid snapshot from a live market.
Kalshi returns `None` gracefully without credentials — acceptable for this test.
```

- [ ] **Step 2: Update P0.2 Verification Commands and Evidence sections**

Replace the existing `### Verification Commands` block with:

```markdown
### Verification Commands

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/api/ops/metrics
curl http://127.0.0.1:8000/api/ops/runs
curl http://127.0.0.1:8000/api/ops/execution
curl http://127.0.0.1:8000/api/candidates
curl http://127.0.0.1:8000/api/positions
curl http://127.0.0.1:8000/api/audit
```

**Proof bundle capture (single command):**

```bash
curl -s http://127.0.0.1:8000/api/ops/proof \
  | python3 -m json.tool \
  > docs/proof-$(date +%Y%m%d-%H%M%S).json
cat docs/proof-*.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['bundle_status'], [i['name'] for i in d['proof_checklist'] if not i['passed']])"
```

`bundle_status == "complete"` with an empty failed list is the strongest proof claim.
```

- [ ] **Step 3: Add execution coverage section to Evidence Required**

After the "From candidates and positions" block in `### Evidence Required Before Claiming Runtime Proof`, add:

```markdown
From `/api/ops/execution` (when `orderbook_enabled=True`):
- non-zero `venue_token_count` for the platforms that ran
- `execution_model_distribution` shows `snapshot_based` entries, not only `heuristic`

From `/api/ops/proof`:
- `bundle_status == "complete"` means all seven checklist items passed
- `bundle_status == "partial"` — inspect `proof_checklist` for which items failed
- Save the JSON artifact to `docs/proof-<timestamp>.json` as the durable proof record

From automated settlement (after positions close):
- `GET /api/positions` shows positions with `status: "CLOSED"` and non-null `actual_pnl`
- `GET /api/candidates/{id}/autopsy` shows the corresponding autopsy record
- `run_proof.positions_settled > 0` in at least one run entry in `/api/ops/runs`
```

- [ ] **Step 4: Commit Task 3**

```bash
git add docs/RUNBOOK.md
git commit -m "docs: update RUNBOOK.md with Fase 1–7 surfaces and proof bundle capture steps"
```

---

### Task 4: Execute the real-data proof (requires credentials)

**Preconditions:**
- `.env` contains a working `ANTHROPIC_API_KEY` (not `placeholder`)
- Docker is available and the DB is running (`make up && make migrate`)
- Port 8000 is free

**Steps:**

- [ ] **Step 1: Start services and migrate**

```bash
make up
make migrate
```

Expected: `Running upgrade... done` (or `Already up to date`).

- [ ] **Step 2: Run the pipeline**

```bash
make pipeline
```

This calls `uv run python -m parallax.pipeline.runner`. Wait for completion.

Expected output includes lines like:
```
pipeline: run completed markets_ingested=N ...
```

If `ANTHROPIC_API_KEY` is missing or invalid, compilation will be skipped and `contracts_compiled=0` — the run still completes but the `compilation_ran` and `semantic_ok` checklist items will fail.

- [ ] **Step 3: Start the API**

In a second terminal:

```bash
make api
```

- [ ] **Step 4: Capture proof bundle**

```bash
mkdir -p docs/proofs
PROOF_FILE=docs/proofs/proof-$(date +%Y%m%d-%H%M%S).json
curl -s http://127.0.0.1:8000/api/ops/proof | python3 -m json.tool > $PROOF_FILE
cat $PROOF_FILE
```

Check `bundle_status` and the `proof_checklist` for which items passed.

- [ ] **Step 5: Run CLOB smoke tests**

```bash
make test-smoke
```

Expected: both tests PASS (Polymarket CLOB live confirmed; Kalshi None gracefully).

- [ ] **Step 6: Update `docs/STATUS.md`**

In `docs/STATUS.md`, move satisfied items from `## Not Yet Proven Here` to the proof record and add a `## Fase 8 — Real-Data Proof (2026-05-03)` section:

```markdown
## Real-Data Proof (Fase 8 — 2026-05-03)

End-to-end proof infrastructure is in place:

- `GET /api/ops/proof` → `ProofBundleReport` with 7-item checklist; `bundle_status="complete"` when all pass
- `make proof` — runs pipeline; prints proof capture command
- `make test-smoke` — runs CLOB smoke tests (`SMOKE_CLOB=1`)
- Proof artifact saved to `docs/proofs/proof-<timestamp>.json`

**[UPDATE THIS SECTION when proof runs with real credentials]**
- Proof run date: TBD
- bundle_status: TBD
- Failed checklist items: TBD
```

Also update `## Current Operational Blockers` to reflect whether credentials are now available.

- [ ] **Step 7: Commit the proof artifacts and STATUS update**

```bash
git add docs/STATUS.md docs/proofs/
git commit -m "docs: Fase 8 proof run completed — real-data pipeline verified"
```

---

## Self-Review

**1. Spec coverage:**
- Proof bundle endpoint → Task 1 ✓
- `make test-smoke` → Task 2 ✓
- `make proof` → Task 2 ✓
- RUNBOOK execution surface update → Task 3 ✓
- Real-data pipeline execution → Task 4 ✓
- STATUS.md update → Task 4 Step 6 ✓

**2. Placeholder scan:** Task 4 Step 6 has `[UPDATE THIS SECTION]` — intentional (the user fills it in after the proof run). All other steps have complete code.

**3. Type consistency:**
- `ProofBundleReport` fields match exactly between schema definition (Task 1 Step 3) and test instantiation (Task 1 Step 1)
- `get_proof_bundle_payload(session: Session) -> ProofBundleReport` — consistent with route handler and test patch target `parallax.ops.service.get_proof_bundle_payload`
- `ProofCheckItem(name=..., passed=..., evidence=...)` — consistent across schema and service build
- `metrics.market_counts_by_platform` — confirmed in `OpsMetricsResponse` (from `ops/schemas.py`)
- `metrics.open_positions` / `metrics.total_candidates` — need verification in Step 5 (the plan includes an explicit check for this)
