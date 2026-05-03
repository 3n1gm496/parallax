# Parallax

Semantic arbitrage engine for prediction markets with:

- native Polymarket and Kalshi ingestion
- unified structural plus semantic relation analysis
- divergence scoring, court gating, and execution simulation
- snapshot-based CLOB orderbook execution (Polymarket + Kalshi)
- automated settlement with PnL normalization and autopsy persistence
- paper-position lifecycle with replay-calibrated fill simulation
- self-evaluating proof bundle (`GET /api/ops/proof`)
- FastAPI API surface plus a React operator console

## Read This First

- Documentation map: [docs/README.md](/home/administrator/tools/parallax/docs/README.md:1)
- Current verified repo state: [docs/STATUS.md](/home/administrator/tools/parallax/docs/STATUS.md:1)
- Runtime contract: [docs/RUNTIME.md](/home/administrator/tools/parallax/docs/RUNTIME.md:1)
- Operational runbook and proof criteria: [docs/RUNBOOK.md](/home/administrator/tools/parallax/docs/RUNBOOK.md:1)
- Vendor handoff path: [docs/VENDOR_HANDOFF.md](/home/administrator/tools/parallax/docs/VENDOR_HANDOFF.md:1)
- Repository map: [docs/REPOSITORY.md](/home/administrator/tools/parallax/docs/REPOSITORY.md:1)
- ADR index: [docs/decisions/README.md](/home/administrator/tools/parallax/docs/decisions/README.md:1)
- Agent workflow: [CLAUDE.md](/home/administrator/tools/parallax/CLAUDE.md:1)

## Truthfulness Rule

- `README.md` is only the entrypoint.
- `docs/STATUS.md` is the source of truth for what is verified in this checkout.
- `docs/RUNTIME.md` describes the active backend and UI contract.
- `docs/RUNBOOK.md` defines what evidence is required before claiming an operational milestone.
- `docs/superpowers/plans/` contains historical planning material, not the current contract.

## Quick Start

```bash
uv sync --extra dev
cp .env.example .env
docker compose up -d
uv run alembic upgrade head
uv run uvicorn parallax.api.app:app --reload --port 8000
```

Optional:

```bash
uv run python -m parallax.pipeline.runner
cd ui && npm install && npm run dev
```

Notes:

- `.env.example` is the minimal local bootstrap file. The full config surface is documented in [docs/RUNTIME.md](/home/administrator/tools/parallax/docs/RUNTIME.md:190).
- `ANTHROPIC_API_KEY` is required for semantic analysis and contract compilation.
- `PIPELINE_MAX_OPEN_MARKETS` can cap a proof run to a small deterministic market slice when you want a fast end-to-end smoke.
- If `5432` or `5433` are already occupied locally, use `POSTGRES_PORT=55432 POSTGRES_TEST_PORT=55433` for `docker compose up -d`, and point `DATABASE_URL` / `TEST_DATABASE_URL` at those same ports.
- For a third-party trial tomorrow, use [docs/VENDOR_HANDOFF.md](/home/administrator/tools/parallax/docs/VENDOR_HANDOFF.md:1) as the primary execution guide.

## Core Commands

```bash
make install
make up
make migrate
make test
make test-integration
make lint
make pipeline
make api
make verify
make test-smoke      # live CLOB adapter smoke tests (SMOKE_CLOB=1)
make proof           # run pipeline + print proof bundle capture command
```

Frontend:

```bash
cd ui && npm install && npm run build
```

## Primary Interfaces

Health:

- `GET /health`
- `GET /ready`

Read APIs:

- `GET /api/markets`
- `GET /api/markets/{id}`
- `GET /api/candidates`
- `GET /api/candidates/{id}`
- `GET /api/candidates/{id}/decision`
- `GET /api/candidates/{id}/autopsy`
- `GET /api/audit`
- `GET /api/audit/{entity_type}/{entity_id}`
- `GET /api/ops/metrics`
- `GET /api/ops/runs`
- `GET /api/ops/runs/{run_id}`
- `GET /api/ops/evaluation`
- `GET /api/ops/backtest`
- `GET /api/ops/policy`
- `GET /api/ops/identity-review`
- `GET /api/ops/relation-sets`
- `GET /api/ops/relation-sets/{set_key}`
- `GET /api/ops/execution`
- `GET /api/ops/proof`
- `GET /api/positions`
- `GET /api/positions/{id}`

Write API:

- `POST /api/positions/{id}/settle`

## Important Runtime Notes

- Persisted market platforms remain only `polymarket` and `kalshi`.
- Polymarket and Kalshi are both fetched directly from their native public APIs.
- Candidate detail computes live `simulation_result` and `court_assessment` on read.
- Court evaluation also persists a decision-time snapshot so operator review can compare stored decision evidence against current live recomputation.
- `/api/ops/metrics` is the aggregate proof surface; `/api/ops/runs` is the stable persisted run-proof surface.
- `/api/ops/proof` returns a `ProofBundleReport` — a 7-item self-evaluating checklist whose `bundle_status="complete"` is the strongest proof claim after a real-data run.
- `/api/ops/execution` exposes CLOB orderbook coverage, snapshot counts, and execution model distribution.
- When `orderbook_enabled=True`, the court path uses VWAP-based snapshot simulation instead of the heuristic estimator.
- Automated settlement runs each pipeline cycle; positions with deterministic oracle prices are closed and autopsy-labeled automatically.
- If `ANTHROPIC_API_KEY` is missing, semantic analysis is misconfigured and `/ready` reports that state explicitly.
