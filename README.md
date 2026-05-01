# Parallax

Automated cross-platform prediction-market arbitrage detector.

Parallax ingests markets from Polymarket and Kalshi, compiles them into structured
semantic contracts using Claude, detects equivalent or subset relations between markets
on different platforms, and surfaces mispriced opportunity candidates for paper trading.

## How it works

```
Polymarket + Kalshi
        ↓
  IngestorService          fetch open markets → upsert to Postgres
        ↓
  CompilerService          Claude tool_use → CompiledContract (yes/no conditions, exclusions)
        ↓
  Stage 1 Detector         structural rules → MUTUALLY_EXCLUSIVE pairs + EQUIVALENT candidates
        ↓
  Stage 2 LLM Detector     Claude contract comparison + counterexample verification
        ↓
  DivergenceService        PayoffMatrix, worst-case payoff post-friction
        ↓
  CandidateRepository      open opportunity candidates
        ↓
  CourtService / Simulator paper-trade approval and sizing stubs
```

## Stack

- Python 3.13, SQLAlchemy 2.0, Pydantic v2, Alembic
- Anthropic Python SDK — `claude-sonnet-4-6`, `tool_use`, prompt caching
- httpx async, FastAPI, pytest + anyio
- Postgres 16 (Docker)

## Quick start

```bash
# 1. Install dependencies
uv sync

# 2. Start Postgres
docker compose up -d

# 3. Run migrations
uv run alembic upgrade head

# 4. Copy and fill in env
cp .env.example .env        # set ANTHROPIC_API_KEY (and optionally KALSHI_API_KEY)

# 5. Run one pipeline cycle
uv run python -m parallax.pipeline.runner

# 6. Start the API
uv run uvicorn parallax.api.app:app --reload --port 8000
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Required for compiler and Stage 2 LLM detection |
| `KALSHI_API_KEY` | `""` | Leave empty to disable Kalshi ingestion |
| `DATABASE_URL` | `postgresql://parallax:dev_password@localhost:5432/parallax` | |
| `FRICTION_BPS` | `50` | Round-trip transaction friction in basis points |
| `COMPILER_MIN_CONFIDENCE` | `0.5` | Contracts below this confidence skip Stage 2 |
| `POLYMARKET_MAX_EVENTS_PER_POLL` | `50` | Max Polymarket events fetched per cycle |

## Development

```bash
# Unit tests (no Docker required)
uv run pytest tests/unit/ -v

# Integration tests (requires Docker)
docker compose up -d
uv run pytest tests/integration/ -v -m integration

# Lint
uv tool run ruff check src/ tests/

# All-in-one dev mode
make dev
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/candidates` | Open opportunity candidates |
| `GET /api/markets` | Ingested markets |
| `GET /api/audit` | Append-only audit log |
| `GET /health` | Health check |

## Project structure

```
src/parallax/
├── shared/schemas.py          # Pydantic schemas + enums
├── db/models.py               # SQLAlchemy ORM (9 tables)
├── ingestion/                 # PlatformAdapter, PolymarketAdapter, KalshiAdapter
├── compiler/                  # AnthropicCompilerProvider, CompilerService
├── detection/                 # Stage1ConstraintDetector, Stage2LLMDetector
├── prover/service.py          # Stage 1+2 orchestration → graph
├── divergence/service.py      # PayoffMatrix, DivergenceService
├── graph/                     # GraphRepository, PostgresGraphRepository
├── pipeline/runner.py         # Top-level async pipeline
├── api/                       # FastAPI routes
└── config.py                  # pydantic-settings config

docs/decisions/                # Architecture Decision Records (ADR 0001–0006)
```

## Architecture decisions

Key decisions are recorded in `docs/decisions/`:

- **ADR 0002** — Anthropic API: `claude-sonnet-4-6`, `tool_use` for structured output, prompt caching
- **ADR 0005** — Hybrid detection: Stage 1 constraint rules + Stage 2 LLM counterexample verification
- **ADR 0006** — `worst_case_payoff` stored post-friction; `total_cost` = capital deployed
