# Project Instructions

## Project status

Slice 2 complete and merged to `main`. Detection pipeline is fully operational:
ingestion (Polymarket + Kalshi) → compile markets → Stage 1 constraint detection →
Stage 2 LLM confirmation → divergence scan → court/simulator stubs.

Next: Slice 3 — real CourtService (Prosecutor/Defense/Judge loop), real SimulatorService
with slippage, calibration loop, WebSocket feed.

## Operating mode

Use this workflow:

1. `/start` to classify the directory and select the next workflow.
2. `/idea` for rough product or project ideas.
3. `/onboard` after project structure exists.
4. `/plan` before non-trivial implementation.
5. `/build` only after an approved plan.
6. `/validate` after implementation.
7. `/review` before final handoff.
8. `/ship` when ready to summarize or prepare PR/release notes.

## Safety

- Do not read `.env`, secrets, credentials, tokens, private keys, session files, or production data.
- Do not run destructive commands without explicit approval.
- Do not install dependencies without explicit approval.
- Do not deploy, push, tag, release, merge, or run migrations without explicit approval.

## Cost control for Parallax

- Default mode is cost-controlled Sonnet.
- Do not use teammate mode, agent teams, or parallel agents unless explicitly requested.
- Do not use browser, Playwright, Chrome DevTools, Firecrawl, or GitHub MCP unless directly relevant to the current task.
- Prefer Serena and local file inspection for repo understanding.
- Use Context7 only for specific library/framework questions.
- Keep reports concise.
- Before expensive tool use, state what tool you want to use and why.

## Project-specific commands

```bash
# Dependencies
uv sync                                          # install all deps (including dev)

# Docker
docker compose up -d                             # start postgres (5432) + postgres_test (5433)
docker compose down                              # stop containers

# Database
uv run alembic upgrade head                      # apply migrations

# Tests
uv run pytest tests/unit/ -v                     # unit tests (117, no Docker needed)
uv run pytest tests/integration/ -v -m integration  # integration tests (requires Docker)

# Lint
uv tool run ruff check src/ tests/               # lint

# Run
uv run uvicorn parallax.api.app:app --reload --port 8000   # API server
uv run python -m parallax.pipeline.runner        # one-shot pipeline run

# Dev shortcut (Docker + API)
make dev
```

## Architecture notes

**Stack:** Python 3.13 · SQLAlchemy 2.0 (legacy query style) · Pydantic v2 ·
Anthropic Python SDK (claude-sonnet-4-6, tool_use, prompt caching) · httpx async ·
FastAPI · pytest + anyio · Alembic · Postgres 16

**Entry points:**
- `src/parallax/pipeline/runner.py` — `PipelineRunner.run_once()` (async): full pipeline orchestration
- `src/parallax/api/app.py` — FastAPI app; routes under `src/parallax/api/routes/`

**Pipeline flow:**
```
IngestorService (Polymarket + Kalshi adapters)
  → MarketRepository.upsert()
  → CompilerService (AnthropicCompilerProvider → CompiledContract)
  → ProverService
      → Stage1ConstraintDetector (intra-group MUTUALLY_EXCLUSIVE; cross-platform price-inversion EQUIVALENT candidates)
      → Stage2LLMDetector (EQUIVALENT/SUBSET candidates only — tool_use, counterexample verification)
      → PostgresGraphRepository.add_relation()
  → DivergenceService (PayoffMatrix, friction_bps) → CandidateRepository
  → CourtService stub → SimulatorService stub
```

**Key modules:**
| Module | Responsibility |
|--------|----------------|
| `shared/schemas.py` | All Pydantic schemas + enums (RelationType, OpportunityType, etc.) |
| `db/models.py` | SQLAlchemy ORM (9 tables) |
| `ingestion/` | PlatformAdapter ABC, PolymarketAdapter, KalshiAdapter, IngestorService |
| `compiler/` | CompilerProvider ABC, AnthropicCompilerProvider, CompilerService |
| `detection/stage1.py` | Rule-based relation detection (no LLM) |
| `detection/stage2.py` | LLM contract comparison with counterexample generation |
| `prover/service.py` | Orchestrates Stage 1 + Stage 2, stores confirmed relations |
| `divergence/service.py` | PayoffMatrix computation, DivergenceService |
| `graph/postgres_repository.py` | Bidirectional relation storage and lookup |
| `pipeline/runner.py` | Top-level async orchestration |

**Important invariants (see ADRs in `docs/decisions/`):**
- `worst_case_payoff` is stored **post-friction**; `SimulatorService` reads it directly — no second friction deduction (ADR 0006)
- `total_cost` = capital deployed (buy_price + (1 − sell_price)), not collateral (ADR 0006)
- `session.commit()` is the **caller's responsibility** — no auto-commit on context exit
- `relation_exists` checks both `(a→b)` and `(b→a)` to prevent duplicate reverse edges
- Stage 2 only fires for EQUIVALENT / DUPLICATE / SUBSET / SUPERSET — MUTUALLY_EXCLUSIVE is stored directly from Stage 1

**Config (env vars / `.env` file):**
| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql://parallax:dev_password@localhost:5432/parallax` | |
| `ANTHROPIC_API_KEY` | `placeholder` | Required for compiler + Stage 2 |
| `KALSHI_API_KEY` | `""` | Empty string disables Kalshi ingestion |
| `FRICTION_BPS` | `50` | Round-trip friction in basis points |
| `COMPILER_MIN_CONFIDENCE` | `0.5` | Contracts below this skip Stage 2 |
| `POLYMARKET_MAX_EVENTS_PER_POLL` | `50` | |

