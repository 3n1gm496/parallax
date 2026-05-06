# Project Instructions

## Mission

Parallax should stay architecturally ambitious while remaining explicit about what is live, what is heuristic, and what is still scaffolded.

## First files to read

1. [README.md](/home/administrator/tools/parallax/README.md:1)
2. [docs/ARCHITECTURE.md](/home/administrator/tools/parallax/docs/ARCHITECTURE.md:1)
3. [docs/RUNBOOK.md](/home/administrator/tools/parallax/docs/RUNBOOK.md:1)
4. [docs/API.md](/home/administrator/tools/parallax/docs/API.md:1)
5. [docs/decisions/README.md](/home/administrator/tools/parallax/docs/decisions/README.md:1)

## Working style

- Prefer the real runtime path over aspirational comments.
- Keep docs, tests, and code aligned in the same turn when possible.
- Treat ADRs as architecture targets; treat `docs/STATUS.md` as current maturity truth.
- Do not leave stale narrative behind after implementation changes.

## Safety

- Do not read `.env`, secrets, credentials, tokens, private keys, session files, or production data.
- Do not run destructive commands without explicit approval.
- Do not install dependencies without explicit approval.
- Do not deploy, push, tag, release, merge, or run migrations without explicit approval.

## Important repo facts

- Backend stack: Python 3.13, Rust Core (PyO3), SQLAlchemy 2.0, msgspec, FastAPI, Anthropic SDK.
- Frontend shell: `ui/` with Vite + React.
- Unit suite is expected to pass locally.
- Integration tests depend on `postgres_test` on port `5433` and may skip cleanly when unavailable.

## Commands

```bash
make install
make up
make down
make migrate
make test
make test-integration
make benchmark
make lint
make pipeline
make api
make dev
```

## Runtime invariants

- Polymarket and Kalshi runtime ingestion are both native.
- Persisted platforms stay `polymarket` or `kalshi`.
- `worst_case_payoff` is stored post-friction and must not be friction-adjusted twice.
- Relation persistence includes structural findings plus confirmed, rejected, and abstained semantic outcomes with explicit evidence and abstention state.
- GET routes use read-session semantics; write flows commit explicitly at the orchestrator boundary.
- Simulator output is heuristic and risk-aware; it is not a perfect-fill echo of `worst_case_payoff`.

## Current execution priority

1. Keep semantic trust and runtime truthfulness high.
2. Deepen lifecycle pieces only on top of verified contracts and tests.
3. Avoid widening public/API/UI claims beyond what the runtime actually does.
