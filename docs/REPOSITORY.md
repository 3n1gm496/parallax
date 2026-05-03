# Repository Map

## Top Level

- `src/parallax/`: backend runtime
- `tests/`: unit and integration coverage
- `docs/`: maintained documentation and ADR index
- `ui/`: Vite/React operator console
- `alembic/`: database migrations

## Backend Modules

- `api/`: FastAPI app, auth/session dependencies, and route surfaces
- `audit/`: append-only audit events
- `autopsy/`: settlement outcome recording and label persistence
- `candidates/`: candidate repository, relation evidence loaders, and read-side assembly for candidate API surfaces
- `compiler/`: contract compilation provider abstraction and persistence
- `court/`: structured candidate assessment and decision gating
- `db/`: SQLAlchemy models and session wiring
- `detection/`: structural and semantic relation logic
- `divergence/`: payoff construction, risk scoring, and candidate creation rules
- `graph/`: relation persistence abstraction
- `identity/`: canonical event management and conservative link provenance
- `ingestion/`: Polymarket adapter, Kalshi adapter, and ingestion orchestration
- `ops/`: operational schemas, readiness/runtime status, and aggregate reporting services
- `pipeline/`: run orchestration and run-scoped audit emission
- `prover/`: relation analysis orchestration and evidence persistence
- `simulator/`: execution heuristics and fill/slippage estimates
- `tracker/`: paper-position lifecycle
- `shared/`: core cross-module schemas and shared evidence vocabulary outside ops-specific reporting

## API Surface Ownership

- `api/routes/markets.py`: market listing and market detail
- `api/routes/candidates.py`: thin HTTP layer over candidate read-side services
- `api/routes/audit.py`: recent audit rows and per-entity audit history
- `api/routes/ops.py`: thin HTTP layer over ops reporting and proof services
- `api/routes/positions.py`: positions, settlement, and candidate autopsy rows

## Tests

- `tests/unit/`: fast isolated module, route, and contract tests
- `tests/integration/`: DB-backed lifecycle proof

## Frontend

- `ui/src/App.tsx`: shell and top-level navigation
- `ui/src/components/ProofFeed.tsx`: opportunity feed
- `ui/src/components/CandidateDetail.tsx`: candidate investigation panel
- `ui/src/components/OperationsView.tsx`: runtime and ops metrics
- `ui/src/components/PositionsBoard.tsx`: position lifecycle and settlement
- `ui/src/components/AuditLog.tsx`: raw audit inspection
- `ui/src/api/client.ts`: typed HTTP client
- `ui/src/types.ts`: frontend contract mirror of backend responses

## Documentation

- `docs/README.md`: entrypoint into maintained documentation
- `docs/STATUS.md`: verified state
- `docs/RUNTIME.md`: active runtime contract
- `docs/RUNBOOK.md`: proof procedure
- `docs/decisions/`: accepted ADRs
- `docs/superpowers/plans/`: historical planning material, not live contract; see `docs/superpowers/plans/README.md`
