# Vendor Handoff

This document is the shortest path for a third party to clone the repository, start it locally, and understand what is and is not proven.

## Goal

Give the vendor two executable paths:

- a local trial that proves repo wiring, API, UI, and lifecycle behavior
- an external-credentials trial that proves live Polymarket plus live Kalshi ingestion and Anthropic-backed semantic confirmation

## Path A: Local Trial Without External Credentials

Use this path when the vendor only needs to verify that the repository boots, migrations apply, the API responds, the UI builds, and the lifecycle surfaces exist.

### Required Software

- Python `3.12`
- `uv`
- Docker
- Node.js `20+`

### Bootstrap

```bash
cp .env.example .env
docker compose up -d
uv sync --extra dev
uv run alembic upgrade head
make ui-install
```

If `5432` or `5433` are already occupied on the vendor machine, move the Docker host ports and the runtime URLs together instead of fighting the defaults:

```bash
POSTGRES_PORT=55432 POSTGRES_TEST_PORT=55433 docker compose up -d
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax uv run alembic upgrade head
```

### Verification

```bash
make verify
TEST_DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:5433/parallax_test \
  make verify-integration
```

Port-conflict-safe variant:

```bash
TEST_DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55433/parallax_test \
  make verify-integration
```

### Start Backend And UI

Terminal 1:

```bash
make api
```

Terminal 2:

```bash
cd ui && npm run dev
```

### Smoke Checks

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/api/ops/metrics
curl http://127.0.0.1:8000/api/ops/runs
curl http://127.0.0.1:8000/api/ops/backtest
curl http://127.0.0.1:8000/api/ops/policy
curl http://127.0.0.1:8000/api/ops/relation-sets
curl http://127.0.0.1:8000/api/candidates
curl http://127.0.0.1:8000/api/positions
```

### Expected Outcome

- backend unit tests pass
- frontend typecheck and build pass
- DB-backed integration lifecycle test passes
- `/api/ops/runs` may stay empty until the pipeline is executed

### Optional Local Pipeline Run

```bash
make pipeline
```

With the default `.env.example`, this can run only after adding a real `ANTHROPIC_API_KEY`.

## Path B: External-Credentials Trial

Use this path when the vendor must validate current live data ingestion and full semantic confirmation behavior.

### `.env` Requirements

At minimum:

```bash
ANTHROPIC_API_KEY=...
```

Optional conservative market scope for a first live run:

```bash
POLYMARKET_MAX_EVENTS_PER_POLL=10
KALSHI_MAX_EVENTS_PER_POLL=10
PIPELINE_MAX_OPEN_MARKETS=8
```

### Commands

```bash
docker compose up -d
uv run alembic upgrade head
make api
```

If the vendor host already uses `5432` or `5433`, use:

```bash
POSTGRES_PORT=55432 POSTGRES_TEST_PORT=55433 docker compose up -d
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax uv run alembic upgrade head
DATABASE_URL=postgresql://parallax:dev_password@127.0.0.1:55432/parallax make api
```

In another terminal:

```bash
make pipeline
```

### Proof Checks

```bash
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/api/ops/metrics
curl http://127.0.0.1:8000/api/ops/runs
curl http://127.0.0.1:8000/api/ops/backtest
curl http://127.0.0.1:8000/api/ops/policy
curl http://127.0.0.1:8000/api/ops/relation-sets
curl http://127.0.0.1:8000/api/candidates
```

### Expected Outcome

- `/ready` reports Polymarket and Kalshi providers as configured and not stale
- `/ready` reports `semantic_analysis.status=ok`
- `/api/ops/runs` contains at least one persisted run proof with non-zero `market_counts_by_platform`
- `/api/ops/metrics` shows activity metrics for compiler, identity, relation proof, relation sets, and divergence
- `/api/ops/relation-sets` exposes persisted n-ary proof records
- `/api/ops/backtest` exposes replay/evaluation rows from persisted decision-time state
- `/api/ops/policy` exposes versioned operator recommendations derived from replay plus autopsy evidence

## What The Vendor Should Treat As Proven

- API contract documented in `README.md` and `docs/RUNTIME.md`
- lifecycle integration path proven by `tests/integration/test_pipeline_integration.py`
- operator console buildable with the current UI code
- identity-qualified relation proof now persists both pairwise and n-ary artifacts

## What The Vendor Should Not Treat As Proven Without A Live Trial

- live Kalshi freshness on their network
- live Anthropic-backed semantic confirmation on their credentials
- real-data candidate generation or run proofs in a fresh database before executing `make pipeline`

## Deliverables To Include With The Handoff

- `.env.example`
- `README.md`
- `docs/STATUS.md`
- `docs/RUNTIME.md`
- `docs/RUNBOOK.md`
- this file
