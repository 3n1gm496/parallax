# Operational Runbook

This file defines what counts as proof for Parallax in its current form.

## Truthfulness Boundary

- A passing unit suite is necessary, but not sufficient
- A passing DB-backed lifecycle integration is necessary for lifecycle proof
- A recent real-data run is necessary for runtime proof
- A real-data run is not complete unless the evidence is visible through the repo’s own API and UI surfaces

## P0.1: DB-Backed Lifecycle Proof

### Preconditions

- Docker is available
- the test database target is reachable
- `TEST_DATABASE_URL` matches the Docker-exposed test port

### Standard path

If `5433` is free:

```bash
docker compose up -d
TEST_DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:5433/parallax_test \
  uv run pytest tests/integration/test_pipeline_integration.py -m integration
```

If another worktree already occupies `5433`, move both the port and URL together:

```bash
POSTGRES_TEST_PORT=55433 docker compose up -d
TEST_DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55433/parallax_test \
  uv run pytest tests/integration/test_pipeline_integration.py -m integration
```

If `5432` is also occupied on the same machine, move the runtime port too so local API verification can use the same stack cleanly:

```bash
POSTGRES_PORT=55432 POSTGRES_TEST_PORT=55433 docker compose up -d
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax \
TEST_DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55433/parallax_test \
  uv run pytest tests/integration/test_pipeline_integration.py -m integration
```

### What P0.1 Must Prove

- market persistence
- relation persistence
- candidate creation
- court evaluation
- paper-position opening
- settlement
- autopsy persistence
- audit write on settlement

### What P0.1 Does Not Prove

- live Polymarket data
- live Kalshi data
- Anthropic compile on current markets
- semantic analysis on current live pairs

## P0.2: Recent Real-Data Runtime Proof

### Required Environment

At minimum:

```bash
DATABASE_URL=postgresql://parallax:dev_password@localhost:5432/parallax
ANTHROPIC_API_KEY=...
PIPELINE_MAX_OPEN_MARKETS=8
```

### Commands

```bash
docker compose up -d
uv run alembic upgrade head
uv run python -m parallax.pipeline.runner
uv run uvicorn parallax.api.app:app --port 8000
```

Port-conflict-safe variant:

```bash
POSTGRES_PORT=55432 POSTGRES_TEST_PORT=55433 docker compose up -d
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax uv run alembic upgrade head
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax uv run python -m parallax.pipeline.runner
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax uv run uvicorn parallax.api.app:app --port 8000
```

### Verification Commands

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/api/ops/metrics
curl http://127.0.0.1:8000/api/ops/runs
curl http://127.0.0.1:8000/api/candidates
curl http://127.0.0.1:8000/api/positions
curl http://127.0.0.1:8000/api/audit
```

### Evidence Required Before Claiming Runtime Proof

From `/api/ops/runs` or `/api/ops/runs/{run_id}`:

- at least one persisted run proof entry with `run_id`
- `run_status`, `started_at`, `completed_at`
- config fingerprint present
- provider fingerprints present
- non-zero `market_counts_by_platform.polymarket`
- non-zero `market_counts_by_platform.kalshi`
- readiness snapshot captured at run completion
- runtime control snapshot captured at run completion

From `/api/ops/metrics`:

- non-zero `market_counts_by_platform.polymarket`
- non-zero `market_counts_by_platform.kalshi`
- populated activity metrics for compiler, identity, relation_analysis, and divergence
- if any paper positions have already been settled, `evaluation` shows non-empty realized metrics rather than the zero-settlement placeholder

From `/ready`:

- database status is `ok`
- semantic analysis status is `ok` for a true semantic-runtime proof
- Polymarket provider is not stale
- Kalshi provider is not stale or misconfigured

From candidates and positions:

- at least one candidate, or a zero-candidate outcome backed by audit evidence
- candidate detail should expose a persisted decision snapshot when court evaluation has run
- `GET /api/candidates/{candidate_id}/decision` should return the persisted snapshot directly
- if any position was opened, that position can be settled through `POST /api/positions/{id}/settle`
- resulting autopsy appears in `GET /api/candidates/{id}/autopsy`

From the UI:

- operations view reflects the same run counts
- candidate detail shows relation evidence and live court assessment
- positions view can settle an open position and display the returned autopsy

## Current Workspace Note

As checked on `2026-05-02`:

- `.env.example` is sufficient for local bootstrap, but not for real-data proof until real credentials are inserted
- backend unit tests, frontend typecheck, and frontend build were re-verified in this checkout
- real-data proof is blocked unless working external credentials are present in `.env`
