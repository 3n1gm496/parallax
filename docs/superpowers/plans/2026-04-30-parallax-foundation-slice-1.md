# PARALLAX Foundation Slice 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first architectural slice of PARALLAX — a proof pipeline that ingests
Polymarket markets, compiles them into structured contracts, detects intra-platform mutually
exclusive mispricings, proves their payoff, tracks paper trades, and surfaces everything in a
minimal War Room UI — all with an immutable audit log from day one.

**Architecture:** Python 3.12 monorepo (`src/parallax/`) with nine modules behind clean
interfaces (`PlatformAdapter`, `CompilerProvider`, `GraphRepository`). SQLAlchemy 2.0 sync +
PostgreSQL 16. Every module has its final interface even if some contain stubs in Slice 1.
Stage 1 constraint detection finds mutually exclusive sets by price-sum; the Payoff Prover
requires an explicit breaking scenario before emitting any candidate.

**Tech Stack:** Python 3.12, uv, SQLAlchemy 2.0, Alembic, PostgreSQL 16, Pydantic v2,
httpx, anthropic SDK, pytest, pytest-mock, FastAPI, Uvicorn, React 18, Vite, TypeScript,
TailwindCSS, Docker Compose

---

## ADR References

| ADR | Decision |
|-----|----------|
| 0001 | Intra-platform logical consistency first |
| 0002 | Anthropic API (Claude Sonnet 4.6) for compiler |
| 0003 | Polymarket-only ingestor, `PlatformAdapter` interface |
| 0004 | PostgreSQL adjacency table → `GraphRepository` interface |
| 0005 | Hybrid Stage 1 (constraint rules) + Stage 2 (LLM) |

---

## File Structure Map

```
parallax/
├── pyproject.toml
├── Makefile
├── docker-compose.yml
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
├── src/parallax/
│   ├── config.py                        # pydantic-settings
│   ├── shared/
│   │   └── schemas.py                   # all shared Pydantic types
│   ├── db/
│   │   ├── models.py                    # all SQLAlchemy models
│   │   └── session.py                   # engine + SessionLocal
│   ├── audit/
│   │   ├── repository.py                # AuditRepository (append-only)
│   │   └── service.py                   # AuditService (typed helpers)
│   ├── ingestor/
│   │   ├── adapter.py                   # PlatformAdapter ABC
│   │   ├── polymarket.py                # PolymarketAdapter
│   │   ├── repository.py                # MarketRepository
│   │   └── service.py                   # IngestorService (polling loop)
│   ├── compiler/
│   │   ├── provider.py                  # CompilerProvider ABC
│   │   ├── anthropic_provider.py        # AnthropicCompilerProvider
│   │   ├── repository.py                # ContractRepository
│   │   └── service.py                   # CompilerService
│   ├── identity/
│   │   ├── repository.py                # EventRepository
│   │   └── service.py                   # IdentityService
│   ├── graph/
│   │   ├── repository.py                # GraphRepository ABC
│   │   ├── postgres_repository.py       # PostgresGraphRepository
│   │   └── detector.py                  # Stage1ConstraintDetector
│   ├── prover/
│   │   ├── repository.py                # CandidateRepository
│   │   └── service.py                   # ProverService
│   ├── divergence/
│   │   └── service.py                   # DivergenceService
│   ├── tracker/
│   │   ├── repository.py                # TrackerRepository
│   │   └── service.py                   # TrackerService
│   ├── court/
│   │   └── service.py                   # CourtService (stub → watchlist)
│   ├── simulator/
│   │   └── service.py                   # SimulatorService (stub)
│   ├── autopsy/
│   │   ├── repository.py                # AutopsyRepository
│   │   └── service.py                   # AutopsyService (stub)
│   ├── calibrator/
│   │   └── __init__.py                  # empty — Slice 2
│   ├── pipeline/
│   │   └── runner.py                    # PipelineRunner (main loop)
│   └── api/
│       ├── main.py                      # FastAPI app
│       └── routes/
│           ├── candidates.py
│           ├── markets.py
│           └── audit.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_audit.py
│   │   ├── test_ingestor.py
│   │   ├── test_compiler.py
│   │   ├── test_identity.py
│   │   ├── test_graph_detector.py
│   │   ├── test_prover.py
│   │   ├── test_divergence.py
│   │   ├── test_tracker.py
│   │   └── test_stubs.py
│   └── integration/
│       └── test_pipeline.py
└── warroom/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/client.ts
        └── components/
            ├── ProofFeed.tsx
            ├── CandidateDetail.tsx
            └── AuditLog.tsx
```

---

## Phase 0 — Foundation

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `Makefile`
- Create: `src/parallax/__init__.py` (empty)
- Create: `src/parallax/config.py`

- [ ] **Step 1: Write failing import test**

```python
# tests/unit/test_config.py
def test_settings_import():
    from parallax.config import Settings
    assert Settings.model_fields["friction_bps"].default == 50
```

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "parallax"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "anthropic>=0.40",
    "httpx>=0.27",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "apscheduler>=3.10",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.14", "ruff>=0.8"]

[tool.hatch.build.targets.wheel]
packages = ["src/parallax"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
markers = ["integration: requires postgres and external APIs"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src"]
```

- [ ] **Step 3: Create src/parallax/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql://parallax:dev_password@localhost:5432/parallax"
    test_database_url: str = "postgresql://parallax:dev_password@localhost:5433/parallax_test"
    anthropic_api_key: str = "placeholder"
    polymarket_polling_interval_seconds: int = 300
    polymarket_max_events_per_poll: int = 50
    friction_bps: int = 50
    divergence_composite_block_threshold: float = 0.8

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
```

- [ ] **Step 4: Install dependencies and run test**

```bash
uv sync --extra dev
uv run pytest tests/unit/test_config.py -v
```
Expected: `PASSED`

- [ ] **Step 5: Create docker-compose.yml and Makefile, then commit**

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16-alpine
    environment: {POSTGRES_DB: parallax, POSTGRES_USER: parallax, POSTGRES_PASSWORD: dev_password}
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U parallax"]
      interval: 5s
      retries: 5
  postgres_test:
    image: postgres:16-alpine
    environment: {POSTGRES_DB: parallax_test, POSTGRES_USER: parallax, POSTGRES_PASSWORD: dev_password}
    ports: ["5433:5432"]
volumes:
  postgres_data:
```

```makefile
# Makefile
.PHONY: install up down migrate test test-integration lint pipeline api dev
install:
	uv sync --extra dev
up:
	docker compose up -d
down:
	docker compose down
migrate:
	uv run alembic upgrade head
test:
	uv run pytest tests/unit/ -v
test-integration:
	uv run pytest tests/integration/ -v -m integration
lint:
	uv run ruff check src/ tests/
pipeline:
	uv run python -m parallax.pipeline.runner
api:
	uv run uvicorn parallax.api.main:app --reload --port 8000
dev:
	docker compose up -d && uv run uvicorn parallax.api.main:app --reload --port 8000
```

Also create `tests/conftest.py`:

```python
# tests/conftest.py
import os
import pytest

# Override DB URL for unit tests — unit tests use mocks, not a real DB.
# Integration tests set DATABASE_URL in their own fixtures.
os.environ.setdefault("DATABASE_URL", "postgresql://parallax:dev_password@localhost:5432/parallax")
```

```bash
git add pyproject.toml docker-compose.yml Makefile \
        src/parallax/__init__.py src/parallax/config.py \
        tests/conftest.py
git commit -m "feat: project scaffolding — pyproject, docker-compose, config, conftest"
```

---

### Task 2: Shared schemas

**Files:**
- Create: `src/parallax/shared/__init__.py`
- Create: `src/parallax/shared/schemas.py`

All shared Pydantic types live here. Every module imports from this file — never re-define types.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_shared_schemas.py
def test_contract_schema_requires_confidence():
    from parallax.shared.schemas import ContractSchema
    s = ContractSchema(
        yes_conditions=["Trump wins electoral college"],
        no_conditions=["Trump does not win"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[],
        compiler_confidence=0.85,
    )
    assert s.compiler_confidence == 0.85

def test_payoff_matrix_worst_case():
    from parallax.shared.schemas import PayoffMatrix, Leg, Scenario, OpportunityType
    leg = Leg(market_id="m1", side="YES", price=0.40, quantity=1.0, outcome="Biden wins", platform="polymarket")
    breaking = Scenario(name="break", description="markets diverge", is_breaking=True, payoff=-0.40)
    good = Scenario(name="win", description="all YES", is_breaking=False, payoff=0.58)
    pm = PayoffMatrix(
        legs=[leg],
        total_cost=0.40,
        scenarios=[breaking, good],
        worst_case_payoff=-0.40,
        best_case_payoff=0.58,
        breaking_scenario=breaking,
        opportunity_type=OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING,
        friction_bps=50,
    )
    assert pm.worst_case_payoff == -0.40
```

Run: `uv run pytest tests/unit/test_shared_schemas.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Create src/parallax/shared/schemas.py**

```python
from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class RelationType(str, Enum):
    EQUIVALENT = "equivalent"
    DUPLICATE = "duplicate"
    SUBSET = "subset"
    SUPERSET = "superset"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    EXHAUSTIVE = "exhaustive"
    PREREQUISITE = "prerequisite"
    INVERSE = "inverse"
    SAME_EVENT_DIFFERENT_DEADLINE = "same_event_different_deadline"
    SAME_EVENT_DIFFERENT_ORACLE = "same_event_different_oracle"
    SAME_EVENT_DIFFERENT_SOURCE = "same_event_different_source"
    CORRELATED_ONLY = "correlated_only"
    NOT_RELATED = "not_related"


class OpportunityType(str, Enum):
    PURE_ARBITRAGE = "pure_arbitrage"
    NEAR_ARBITRAGE = "near_arbitrage"
    SEMANTIC_ARBITRAGE = "semantic_arbitrage"
    SUBSET_VIOLATION = "subset_violation"
    DUPLICATE_DIVERGENCE = "duplicate_divergence"
    MUTUALLY_EXCLUSIVE_MISPRICING = "mutually_exclusive_mispricing"
    EXHAUSTIVE_SET_MISPRICING = "exhaustive_set_mispricing"
    SETTLEMENT_YIELD = "settlement_yield"
    ASYMMETRIC_STRUCTURAL_BET = "asymmetric_structural_bet"
    FALSE_ARBITRAGE = "false_arbitrage"


class CourtDecision(str, Enum):
    APPROVED = "APPROVED"
    WATCHLIST = "WATCHLIST"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    PAPER_TRADE = "PAPER_TRADE"
    CANDIDATE_FOR_LIVE = "CANDIDATE_FOR_LIVE"


class RawMarketData(BaseModel):
    platform: str
    market_id: str
    title: str
    description: str
    resolution_criteria: str
    outcomes: list[str]
    outcome_prices: list[float]
    category: str | None = None
    group_id: str | None = None   # Polymarket event ID — used for Stage 1 grouping
    deadline: datetime
    is_closed: bool
    resolution_source: str | None = None
    raw_payload: dict


class AmbiguityFlag(BaseModel):
    term: str
    description: str


class Counterexample(BaseModel):
    scenario_description: str
    resolution_a: str   # "YES" | "NO" | "AMBIGUOUS"
    resolution_b: str
    why_different: str


class ContractSchema(BaseModel):
    yes_conditions: list[str]
    no_conditions: list[str]
    exclusions: list[str]
    ambiguity_terms: list[AmbiguityFlag]
    counterexamples: list[Counterexample]
    compiler_confidence: float   # 0.0–1.0; calibrated over time


class Leg(BaseModel):
    market_id: str
    side: str = "YES"            # "YES" | "NO"
    price: float
    quantity: float = 1.0
    cost: float | None = None    # defaults to price * quantity; set explicitly when known
    outcome: str | None = None   # human-readable outcome label, e.g. "Biden wins"
    platform: str | None = None


class Scenario(BaseModel):
    name: str
    description: str
    is_breaking: bool = False   # True → this scenario breaks the trade thesis
    payoff: float               # net payoff after total_cost is already subtracted


class PayoffMatrix(BaseModel):
    legs: list[Leg]
    total_cost: float
    scenarios: list[Scenario]
    worst_case_payoff: float
    best_case_payoff: float
    breaking_scenario: Scenario | None  # must exist for any approved candidate
    opportunity_type: OpportunityType
    friction_bps: int


class RiskScore(BaseModel):
    oracle_risk: float
    deadline_risk: float
    semantic_risk: float
    composite: float

    @classmethod
    def combine(cls, oracle: float, deadline: float, semantic: float) -> "RiskScore":
        return cls(
            oracle_risk=oracle,
            deadline_risk=deadline,
            semantic_risk=semantic,
            composite=round((oracle + deadline + semantic) / 3, 4),
        )


class SimulationResult(BaseModel):
    candidate_id: str
    simulated_pnl: float       # post-friction estimate
    friction_bps: int
    fill_probability: float    # 1.0 in stub (assumes full fill)
    is_executable: bool        # True if simulated_pnl > 0
    note: str                  # "stub — no order book model" in Slice 1


class ResolutionType(str, Enum):
    CORRECT = "CORRECT"
    IDENTITY_ERROR = "IDENTITY_ERROR"       # relation was wrongly detected
    ORACLE_DIVERGENCE = "ORACLE_DIVERGENCE" # oracle resolved unexpectedly
    CANCELLED = "CANCELLED"                 # market voided / no contest


# --- API response schemas ---

class CandidateSummary(BaseModel):
    id: str
    opportunity_type: str
    worst_case_payoff: float
    total_cost: float
    court_decision: str
    created_at: datetime

class CandidateDetail(BaseModel):
    id: str
    opportunity_type: str
    market_ids: list[str]
    payoff_matrix: PayoffMatrix
    risk_score: RiskScore | None
    simulation_result: SimulationResult | None
    court_decision: str
    created_at: datetime

class MarketSummary(BaseModel):
    id: str
    platform: str
    title: str
    outcome_prices: list[float]
    group_id: str | None
    deadline: datetime
    is_closed: bool

class MarketDetail(MarketSummary):
    description: str
    resolution_criteria: str
    resolution_source: str | None
    contract: ContractSchema | None

class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    entity_id: str | None
    payload: dict
    created_at: datetime

class RunSummary(BaseModel):
    markets_ingested: int
    contracts_compiled: int
    events_resolved: int
    relations_detected: int
    candidates_found: int
    candidates_watchlisted: int
    errors: list[str]
```

- [ ] **Step 3: Run test**

```bash
uv run pytest tests/unit/test_shared_schemas.py -v
```
Expected: `2 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/shared/ tests/unit/test_shared_schemas.py
git commit -m "feat: shared Pydantic schemas (RelationType, ContractSchema, PayoffMatrix, etc.)"
```

---

### Task 3: Database models + session

**Files:**
- Create: `src/parallax/db/__init__.py`
- Create: `src/parallax/db/models.py`
- Create: `src/parallax/db/session.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_db_models.py
def test_all_models_importable():
    from parallax.db.models import (
        AuditEvent, RawMarket, CompiledContract, CanonicalEvent,
        MarketEventLink, MarketRelation, OpportunityCandidate,
        PaperPosition, AutopsyRecord,
    )
    assert AuditEvent.__tablename__ == "audit_events"
    assert RawMarket.__tablename__ == "raw_markets"
    assert OpportunityCandidate.__tablename__ == "opportunity_candidates"
```

Run: `uv run pytest tests/unit/test_db_models.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 2: Create src/parallax/db/models.py**

```python
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, JSON, Float, Boolean, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(index=True, default=_now)
    # No update / delete allowed — enforced at repository level


class RawMarket(Base):
    __tablename__ = "raw_markets"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # "{platform}:{market_id}"
    platform: Mapped[str] = mapped_column(String(50), index=True)
    market_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    resolution_criteria: Mapped[str] = mapped_column(Text)
    outcomes: Mapped[list] = mapped_column(JSON)
    outcome_prices: Mapped[list] = mapped_column(JSON)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    group_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    deadline: Mapped[datetime] = mapped_column(index=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON)
    ingested_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now)


class CompiledContract(Base):
    __tablename__ = "compiled_contracts"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), index=True)
    contract_json: Mapped[dict] = mapped_column(JSON)
    compiler_confidence: Mapped[float] = mapped_column(Float)
    compiler_version: Mapped[str] = mapped_column(String(100))
    compiled_at: Mapped[datetime] = mapped_column(default=_now)


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(100), index=True)
    platform_group_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    resolution: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    updated_at: Mapped[datetime] = mapped_column(default=_now)


class MarketEventLink(Base):
    __tablename__ = "market_event_links"
    raw_market_id: Mapped[str] = mapped_column(ForeignKey("raw_markets.id"), primary_key=True)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_events.id"), primary_key=True
    )
    linked_at: Mapped[datetime] = mapped_column(default=_now)


class MarketRelation(Base):
    __tablename__ = "market_relations"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_market_id: Mapped[str] = mapped_column(String(255), index=True)
    to_market_id: Mapped[str] = mapped_column(String(255), index=True)
    relation_type: Mapped[str] = mapped_column(String(100), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(100))  # "stage1_constraint" | "stage2_llm"
    created_at: Mapped[datetime] = mapped_column(default=_now)


class OpportunityCandidate(Base):
    __tablename__ = "opportunity_candidates"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    market_ids: Mapped[list] = mapped_column(JSON)
    payoff_matrix: Mapped[dict] = mapped_column(JSON)
    opportunity_type: Mapped[str] = mapped_column(String(100), index=True)
    worst_case_payoff: Mapped[float] = mapped_column(Float)
    friction_bps: Mapped[int] = mapped_column(Integer)
    risk_scores: Mapped[dict] = mapped_column(JSON)
    court_decision: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="open", index=True)
    detected_at: Mapped[datetime] = mapped_column(default=_now)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"))
    status: Mapped[str] = mapped_column(String(50), default="OPEN")
    legs_json: Mapped[list] = mapped_column(JSON)   # list[Leg.model_dump()]
    opened_at: Mapped[datetime] = mapped_column(default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    actual_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)


class AutopsyRecord(Base):
    __tablename__ = "autopsy_records"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opportunity_candidates.id"))
    position_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    actual_resolution: Mapped[dict] = mapped_column(JSON)  # {market_id: "Yes"|"No"|"N/A"}
    resolution_type: Mapped[str] = mapped_column(String(100), index=True)
    identity_error: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(default=_now)
```

- [ ] **Step 3: Create src/parallax/db/session.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from parallax.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session() -> Session:
    return SessionLocal()
```

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/unit/test_db_models.py -v
```
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/db/ tests/unit/test_db_models.py
git commit -m "feat: SQLAlchemy models (all 9 tables) and session factory"
```

---

### Task 4: Alembic migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial_schema.py`

- [ ] **Step 1: Initialise alembic**

```bash
uv run alembic init alembic
```
Expected: creates `alembic/` directory and `alembic.ini`

- [ ] **Step 2: Edit alembic/env.py** — replace the `target_metadata = None` line with:

```python
from parallax.db.models import Base
target_metadata = Base.metadata
```

And set `sqlalchemy.url` to use the env var:

```python
import os
config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", ""))
```

- [ ] **Step 3: Generate the migration**

```bash
make up   # start postgres
make migrate  # runs alembic upgrade head — creates tables
```

Or manually:
```bash
docker compose up -d
uv run alembic revision --autogenerate -m "initial schema"
uv run alembic upgrade head
```
Expected: 9 tables created in postgres, no errors.

- [ ] **Step 4: Verify tables exist**

```bash
docker exec -it parallax-postgres-1 psql -U parallax -d parallax -c "\dt"
```
Expected output lists: `audit_events`, `raw_markets`, `compiled_contracts`, `canonical_events`,
`market_event_links`, `market_relations`, `opportunity_candidates`, `paper_positions`,
`autopsy_records`.

- [ ] **Step 5: Commit**

```bash
git add alembic/ alembic.ini
git commit -m "feat: Alembic setup with initial schema migration for all 9 tables"
```

---

### Task 5: Audit log (immutable)

**Files:**
- Create: `src/parallax/audit/__init__.py`
- Create: `src/parallax/audit/repository.py`
- Create: `src/parallax/audit/service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_audit.py
from unittest.mock import MagicMock, call
import uuid, pytest

def make_session_with_events(events):
    session = MagicMock()
    session.query.return_value.order_by.return_value.limit.return_value.all.return_value = events
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = events
    return session

def test_append_creates_audit_event():
    from parallax.audit.repository import AuditRepository
    from parallax.db.models import AuditEvent
    session = MagicMock()
    repo = AuditRepository(session)
    result = repo.append("market_ingested", "market", "polymarket:m1", {"title": "test"})
    session.add.assert_called_once()
    session.flush.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, AuditEvent)
    assert added.event_type == "market_ingested"
    assert added.entity_id == "polymarket:m1"

def test_repository_has_no_delete_method():
    from parallax.audit.repository import AuditRepository
    assert not hasattr(AuditRepository, "delete")
    assert not hasattr(AuditRepository, "update")

def test_audit_service_records_market_ingested():
    from parallax.audit.service import AuditService
    from parallax.audit.repository import AuditRepository
    repo = MagicMock(spec=AuditRepository)
    svc = AuditService(repo)
    svc.market_ingested("polymarket:m1", "Will Trump win?")
    repo.append.assert_called_once_with(
        "market_ingested", "market", "polymarket:m1",
        {"title": "Will Trump win?"}
    )
```

Run: `uv run pytest tests/unit/test_audit.py -v`
Expected: `3 errors (ModuleNotFoundError)`

- [ ] **Step 2: Create src/parallax/audit/repository.py**

```python
from __future__ import annotations
from datetime import datetime
from typing import Any
import uuid
from sqlalchemy.orm import Session
from parallax.db.models import AuditEvent


class AuditRepository:
    """Append-only. No update or delete methods exist by design."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> AuditEvent:
        event = AuditEvent(
            id=uuid.uuid4(),
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(event)
        self._session.flush()
        return event

    def list_recent(self, limit: int = 100) -> list[AuditEvent]:
        return (
            self._session.query(AuditEvent)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_by_entity(self, entity_type: str, entity_id: str) -> list[AuditEvent]:
        return (
            self._session.query(AuditEvent)
            .filter(
                AuditEvent.entity_type == entity_type,
                AuditEvent.entity_id == entity_id,
            )
            .order_by(AuditEvent.created_at.asc())
            .all()
        )
```

- [ ] **Step 3: Create src/parallax/audit/service.py**

```python
from __future__ import annotations
from parallax.audit.repository import AuditRepository


class AuditService:
    def __init__(self, repo: AuditRepository) -> None:
        self._repo = repo

    def market_ingested(self, market_id: str, title: str) -> None:
        self._repo.append("market_ingested", "market", market_id, {"title": title})

    def contract_compiled(self, market_id: str, confidence: float, version: str) -> None:
        self._repo.append(
            "contract_compiled", "market", market_id,
            {"confidence": confidence, "compiler_version": version},
        )

    def relation_detected(self, from_id: str, to_id: str, relation_type: str, confidence: float) -> None:
        self._repo.append(
            "relation_detected", "relation", f"{from_id}→{to_id}",
            {"relation_type": relation_type, "confidence": confidence},
        )

    def candidate_created(self, candidate_id: str, opportunity_type: str, worst_case_payoff: float) -> None:
        self._repo.append(
            "candidate_created", "candidate", candidate_id,
            {"opportunity_type": opportunity_type, "worst_case_payoff": worst_case_payoff},
        )

    def court_decision(self, candidate_id: str, decision: str) -> None:
        self._repo.append(
            "court_decision", "candidate", candidate_id, {"decision": decision}
        )

    def paper_trade_opened(self, position_id: str, candidate_id: str, theoretical_cost: float) -> None:
        self._repo.append(
            "paper_trade_opened", "position", position_id,
            {"candidate_id": candidate_id, "theoretical_cost": theoretical_cost},
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_audit.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/audit/ tests/unit/test_audit.py
git commit -m "feat: AuditRepository (append-only) and AuditService with typed event helpers"
```

---

*— End of Phase 0 —*

---

## Phase 1 — Data Pipeline

### Task 6: PlatformAdapter interface + MarketRepository

**Files:**
- Create: `src/parallax/ingestor/__init__.py`
- Create: `src/parallax/ingestor/adapter.py`
- Create: `src/parallax/ingestor/repository.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_ingestor.py
from unittest.mock import MagicMock
from datetime import datetime, timezone

def _make_market(market_id="m1", group_id="g1", prices=None):
    from parallax.shared.schemas import RawMarketData
    return RawMarketData(
        platform="polymarket",
        market_id=market_id,
        title="Will X win?",
        description="Resolves YES if X wins.",
        resolution_criteria="Official results.",
        outcomes=["Yes", "No"],
        outcome_prices=prices or [0.6, 0.4],
        group_id=group_id,
        deadline=datetime(2025, 11, 5, tzinfo=timezone.utc),
        is_closed=False,
        raw_payload={},
    )

def test_platform_adapter_is_abstract():
    from parallax.ingestor.adapter import PlatformAdapter
    import inspect
    assert inspect.isabstract(PlatformAdapter)

def test_market_repository_upsert():
    from parallax.ingestor.repository import MarketRepository
    session = MagicMock()
    session.get.return_value = None
    repo = MarketRepository(session)
    market = _make_market()
    repo.upsert(market)
    session.add.assert_called_once()

def test_market_repository_get_by_group():
    from parallax.ingestor.repository import MarketRepository
    from parallax.db.models import RawMarket
    m = MagicMock(spec=RawMarket)
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [m]
    repo = MarketRepository(session)
    result = repo.get_by_group("polymarket", "g1")
    assert result == [m]
```

Run: `uv run pytest tests/unit/test_ingestor.py -v`
Expected: `3 errors`

- [ ] **Step 2: Create src/parallax/ingestor/adapter.py**

```python
from abc import ABC, abstractmethod
from parallax.shared.schemas import RawMarketData


class PlatformAdapter(ABC):
    """Fetches raw market data from a prediction market platform."""

    @abstractmethod
    def fetch_events(self, offset: int = 0, limit: int = 50) -> list[list[RawMarketData]]:
        """Return grouped markets. Each inner list is one event (mutually exclusive set)."""
        ...

    @abstractmethod
    def fetch_market(self, market_id: str) -> RawMarketData | None:
        ...

    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...
```

- [ ] **Step 3: Create src/parallax/ingestor/repository.py**

```python
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import RawMarket
from parallax.shared.schemas import RawMarketData


class MarketRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, data: RawMarketData) -> RawMarket:
        pk = f"{data.platform}:{data.market_id}"
        existing = self._session.get(RawMarket, pk)
        if existing:
            existing.outcome_prices = data.outcome_prices
            existing.is_closed = data.is_closed
            existing.updated_at = datetime.now(timezone.utc)
            self._session.flush()
            return existing
        market = RawMarket(
            id=pk,
            platform=data.platform,
            market_id=data.market_id,
            title=data.title,
            description=data.description,
            resolution_criteria=data.resolution_criteria,
            outcomes=data.outcomes,
            outcome_prices=data.outcome_prices,
            category=data.category,
            group_id=data.group_id,
            deadline=data.deadline,
            is_closed=data.is_closed,
            resolution_source=data.resolution_source,
            raw_payload=data.raw_payload,
        )
        self._session.add(market)
        self._session.flush()
        return market

    def get_by_group(self, platform: str, group_id: str) -> list[RawMarket]:
        return (
            self._session.query(RawMarket)
            .filter(RawMarket.platform == platform, RawMarket.group_id == group_id)
            .all()
        )

    def get_active(self, platform: str) -> list[RawMarket]:
        return (
            self._session.query(RawMarket)
            .filter(RawMarket.platform == platform, RawMarket.is_closed == False)
            .all()
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_ingestor.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/ingestor/ tests/unit/test_ingestor.py
git commit -m "feat: PlatformAdapter ABC and MarketRepository (upsert + group query)"
```

---

### Task 7: PolymarketAdapter

**Files:**
- Create: `src/parallax/ingestor/polymarket.py`

Calls `GET https://gamma-api.polymarket.com/events?limit={limit}&offset={offset}&closed=false`.
Each event groups its markets as a mutually exclusive set; the event `id` becomes `group_id`.

- [ ] **Step 1: Write failing test**

```python
# append to tests/unit/test_ingestor.py

def test_polymarket_adapter_parses_event(requests_mock_or_httpx):
    """Uses pytest-mock to patch httpx.Client.get."""
    pass  # real test is in Step 3 below
```

Add a dedicated test:

```python
# tests/unit/test_polymarket_adapter.py
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

FAKE_EVENTS = [
    {
        "id": "event-001",
        "title": "US Election 2026",
        "markets": [
            {
                "id": "mkt-a",
                "conditionId": "0xaaa",
                "question": "Will Candidate A win?",
                "description": "Resolves YES if A wins the 2026 election.",
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["0.55", "0.45"]),
                "endDate": "2026-11-05T00:00:00.000Z",
                "closed": False,
                "active": True,
                "resolutionSource": "AP News",
                "category": "Politics",
            },
            {
                "id": "mkt-b",
                "conditionId": "0xbbb",
                "question": "Will Candidate B win?",
                "description": "Resolves YES if B wins.",
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["0.40", "0.60"]),
                "endDate": "2026-11-05T00:00:00.000Z",
                "closed": False,
                "active": True,
                "resolutionSource": "AP News",
                "category": "Politics",
            },
        ],
    }
]

def test_fetch_events_returns_grouped_markets():
    from parallax.ingestor.polymarket import PolymarketAdapter
    mock_response = MagicMock()
    mock_response.json.return_value = FAKE_EVENTS
    mock_response.raise_for_status = MagicMock()
    with patch("httpx.Client.get", return_value=mock_response):
        adapter = PolymarketAdapter()
        groups = adapter.fetch_events(offset=0, limit=50)
    assert len(groups) == 1
    assert len(groups[0]) == 2
    mkt_a = groups[0][0]
    assert mkt_a.market_id == "mkt-a"
    assert mkt_a.group_id == "event-001"
    assert mkt_a.outcome_prices == [0.55, 0.45]
    assert mkt_a.platform == "polymarket"

def test_fetch_events_skips_closed_markets():
    from parallax.ingestor.polymarket import PolymarketAdapter
    closed_event = {
        "id": "event-002",
        "title": "Old event",
        "markets": [
            {
                "id": "mkt-c",
                "conditionId": "0xccc",
                "question": "Old question?",
                "description": "Old",
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["1.0", "0.0"]),
                "endDate": "2024-01-01T00:00:00.000Z",
                "closed": True,
                "active": False,
                "resolutionSource": "",
                "category": "Politics",
            }
        ],
    }
    mock_response = MagicMock()
    mock_response.json.return_value = [closed_event]
    mock_response.raise_for_status = MagicMock()
    with patch("httpx.Client.get", return_value=mock_response):
        adapter = PolymarketAdapter()
        groups = adapter.fetch_events()
    assert groups == []
```

Run: `uv run pytest tests/unit/test_polymarket_adapter.py -v`
Expected: `2 errors`

- [ ] **Step 2: Create src/parallax/ingestor/polymarket.py**

```python
from __future__ import annotations
import json
from datetime import datetime, timezone
import httpx
from parallax.ingestor.adapter import PlatformAdapter
from parallax.shared.schemas import RawMarketData

_GAMMA_URL = "https://gamma-api.polymarket.com"


class PolymarketAdapter(PlatformAdapter):
    platform_name = "polymarket"

    def __init__(self, timeout: int = 30) -> None:
        self._client = httpx.Client(timeout=timeout)

    def fetch_events(self, offset: int = 0, limit: int = 50) -> list[list[RawMarketData]]:
        """Each returned inner list is one Polymarket event (mutually exclusive market set)."""
        resp = self._client.get(
            f"{_GAMMA_URL}/events",
            params={"limit": limit, "offset": offset, "closed": "false", "active": "true"},
        )
        resp.raise_for_status()
        events = resp.json()
        groups: list[list[RawMarketData]] = []
        for event in events:
            markets = [
                self._parse_market(m, group_id=event["id"])
                for m in event.get("markets", [])
                if not m.get("closed", False)
            ]
            if markets:
                groups.append(markets)
        return groups

    def fetch_market(self, market_id: str) -> RawMarketData | None:
        resp = self._client.get(f"{_GAMMA_URL}/markets/{market_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return self._parse_market(data, group_id=data.get("groupId"))

    def _parse_market(self, data: dict, group_id: str | None) -> RawMarketData:
        outcomes: list[str] = (
            json.loads(data["outcomes"]) if isinstance(data["outcomes"], str) else data["outcomes"]
        )
        raw_prices: list[str] = (
            json.loads(data["outcomePrices"])
            if isinstance(data["outcomePrices"], str)
            else data["outcomePrices"]
        )
        prices = [float(p) for p in raw_prices]
        deadline = datetime.fromisoformat(
            data["endDate"].replace("Z", "+00:00")
        )
        return RawMarketData(
            platform=self.platform_name,
            market_id=data["id"],
            title=data.get("question", data.get("title", "")),
            description=data.get("description", ""),
            resolution_criteria=data.get("description", ""),
            outcomes=outcomes,
            outcome_prices=prices,
            category=data.get("category"),
            group_id=group_id,
            deadline=deadline,
            is_closed=data.get("closed", False),
            resolution_source=data.get("resolutionSource"),
            raw_payload=data,
        )
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_polymarket_adapter.py -v
```
Expected: `2 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/ingestor/polymarket.py tests/unit/test_polymarket_adapter.py
git commit -m "feat: PolymarketAdapter — fetches events from Gamma API, parses grouped markets"
```

---

### Task 8: IngestorService (polling loop)

**Files:**
- Create: `src/parallax/ingestor/service.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_ingestor_service.py
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def _make_raw(market_id="m1", group_id="g1", prices=None):
    from parallax.shared.schemas import RawMarketData
    return RawMarketData(
        platform="polymarket", market_id=market_id,
        title="Test", description="Desc", resolution_criteria="RC",
        outcomes=["Yes", "No"], outcome_prices=prices or [0.6, 0.4],
        group_id=group_id,
        deadline=datetime(2026, 11, 5, tzinfo=timezone.utc),
        is_closed=False, raw_payload={},
    )

def test_ingest_once_upserts_markets_and_logs():
    from parallax.ingestor.service import IngestorService
    adapter = MagicMock()
    adapter.platform_name = "polymarket"
    adapter.fetch_events.return_value = [[_make_raw("m1"), _make_raw("m2")]]
    market_repo = MagicMock()
    market_repo.upsert.return_value = MagicMock(id="polymarket:m1")
    audit = MagicMock()
    svc = IngestorService(adapter, market_repo, audit)
    count = svc.ingest_once(limit=50)
    assert market_repo.upsert.call_count == 2
    assert audit.market_ingested.call_count == 2
    assert count == 2

def test_ingest_once_returns_zero_on_empty():
    from parallax.ingestor.service import IngestorService
    adapter = MagicMock()
    adapter.fetch_events.return_value = []
    svc = IngestorService(adapter, MagicMock(), MagicMock())
    assert svc.ingest_once() == 0
```

Run: `uv run pytest tests/unit/test_ingestor_service.py -v`
Expected: `2 errors`

- [ ] **Step 2: Create src/parallax/ingestor/service.py**

```python
from __future__ import annotations
from parallax.ingestor.adapter import PlatformAdapter
from parallax.ingestor.repository import MarketRepository
from parallax.audit.service import AuditService


class IngestorService:
    def __init__(
        self,
        adapter: PlatformAdapter,
        market_repo: MarketRepository,
        audit: AuditService,
    ) -> None:
        self._adapter = adapter
        self._repo = market_repo
        self._audit = audit

    def ingest_once(self, offset: int = 0, limit: int = 50) -> int:
        """Fetch one page of events, upsert all markets, return count ingested."""
        groups = self._adapter.fetch_events(offset=offset, limit=limit)
        count = 0
        for group in groups:
            for raw in group:
                record = self._repo.upsert(raw)
                self._audit.market_ingested(record.id, raw.title)
                count += 1
        return count
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_ingestor_service.py -v
```
Expected: `2 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/ingestor/service.py tests/unit/test_ingestor_service.py
git commit -m "feat: IngestorService — polls adapter, upserts markets, emits audit events"
```

---

### Task 9: CompilerProvider interface + AnthropicCompilerProvider

**Files:**
- Create: `src/parallax/compiler/__init__.py`
- Create: `src/parallax/compiler/provider.py`
- Create: `src/parallax/compiler/anthropic_provider.py`
- Create: `src/parallax/compiler/repository.py`
- Create: `src/parallax/compiler/service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_compiler.py
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

def _make_raw(market_id="m1"):
    from parallax.shared.schemas import RawMarketData
    return RawMarketData(
        platform="polymarket", market_id=market_id,
        title="Will X win?", description="Resolves YES if X wins official vote.",
        resolution_criteria="Official electoral commission results.",
        outcomes=["Yes", "No"], outcome_prices=[0.6, 0.4],
        deadline=datetime(2026, 11, 5, tzinfo=timezone.utc),
        is_closed=False, raw_payload={},
    )

def test_compiler_provider_is_abstract():
    from parallax.compiler.provider import CompilerProvider
    import inspect
    assert inspect.isabstract(CompilerProvider)

def test_anthropic_provider_returns_contract_schema(mocker):
    from parallax.compiler.anthropic_provider import AnthropicCompilerProvider
    from parallax.shared.schemas import ContractSchema
    fake_tool_use = MagicMock()
    fake_tool_use.type = "tool_use"
    fake_tool_use.input = {
        "yes_conditions": ["X wins official vote before deadline"],
        "no_conditions": ["X does not win", "Election postponed past deadline"],
        "exclusions": ["Vote count disputes not yet resolved"],
        "ambiguity_terms": [{"term": "official", "description": "depends on which body certifies"}],
        "counterexamples": [
            {
                "scenario_description": "X wins popular vote but not certified before deadline",
                "resolution_a": "NO",
                "resolution_b": "YES",
                "why_different": "certification timing ambiguity",
            }
        ],
        "compiler_confidence": 0.78,
    }
    fake_message = MagicMock()
    fake_message.content = [fake_tool_use]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = fake_message
    mocker.patch("anthropic.Anthropic", return_value=mock_client)
    provider = AnthropicCompilerProvider(api_key="test-key")
    result = provider.compile(_make_raw())
    assert isinstance(result, ContractSchema)
    assert result.compiler_confidence == 0.78
    assert len(result.counterexamples) == 1
    assert len(result.yes_conditions) == 1

def test_compiler_service_stores_contract(mocker):
    from parallax.compiler.service import CompilerService
    from parallax.shared.schemas import ContractSchema, AmbiguityFlag, Counterexample
    contract = ContractSchema(
        yes_conditions=["X wins"],
        no_conditions=["X loses"],
        exclusions=[],
        ambiguity_terms=[],
        counterexamples=[
            Counterexample(
                scenario_description="tie",
                resolution_a="NO",
                resolution_b="YES",
                why_different="different resolution rules",
            )
        ],
        compiler_confidence=0.9,
    )
    provider = MagicMock()
    provider.compile.return_value = contract
    provider.version = "anthropic/claude-sonnet-4-6"
    repo = MagicMock()
    stored = MagicMock()
    stored.id = "uuid-123"
    stored.compiler_confidence = 0.9
    repo.store.return_value = stored
    audit = MagicMock()
    svc = CompilerService(provider, repo, audit)
    result = svc.compile_market(_make_raw())
    repo.store.assert_called_once()
    audit.contract_compiled.assert_called_once_with(
        "polymarket:m1", 0.9, "anthropic/claude-sonnet-4-6"
    )
    assert result.compiler_confidence == 0.9
```

Run: `uv run pytest tests/unit/test_compiler.py -v`
Expected: `3 errors`

- [ ] **Step 2: Create src/parallax/compiler/provider.py**

```python
from abc import ABC, abstractmethod
from parallax.shared.schemas import RawMarketData, ContractSchema


class CompilerProvider(ABC):
    """Abstracts the LLM backend. Swap Anthropic for local or OpenAI without changing callers."""

    @abstractmethod
    def compile(self, market: RawMarketData) -> ContractSchema:
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Identifier stored with every compiled contract, e.g. anthropic/claude-sonnet-4-6."""
        ...
```

- [ ] **Step 3: Create src/parallax/compiler/anthropic_provider.py**

```python
from __future__ import annotations
import anthropic
from parallax.compiler.provider import CompilerProvider
from parallax.shared.schemas import (
    RawMarketData, ContractSchema, AmbiguityFlag, Counterexample,
)

_MODEL = "claude-sonnet-4-6"
_TOOL_NAME = "compile_contract"
_TOOL_DEF = {
    "name": _TOOL_NAME,
    "description": "Extract a structured formal contract from a prediction market description.",
    "input_schema": {
        "type": "object",
        "required": [
            "yes_conditions", "no_conditions", "exclusions",
            "ambiguity_terms", "counterexamples", "compiler_confidence",
        ],
        "properties": {
            "yes_conditions": {"type": "array", "items": {"type": "string"}},
            "no_conditions": {"type": "array", "items": {"type": "string"}},
            "exclusions": {"type": "array", "items": {"type": "string"}},
            "ambiguity_terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["term", "description"],
                    "properties": {
                        "term": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
            "counterexamples": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["scenario_description", "resolution_a", "resolution_b", "why_different"],
                    "properties": {
                        "scenario_description": {"type": "string"},
                        "resolution_a": {"type": "string", "enum": ["YES", "NO", "AMBIGUOUS"]},
                        "resolution_b": {"type": "string", "enum": ["YES", "NO", "AMBIGUOUS"]},
                        "why_different": {"type": "string"},
                    },
                },
            },
            "compiler_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    },
}

_SYSTEM = (
    "You are a formal contract compiler for prediction markets. "
    "Extract a precise structured contract from the market description. "
    "Always generate at least one counterexample: a realistic scenario where "
    "the market might resolve unexpectedly. "
    "Set compiler_confidence low (< 0.5) when the resolution criteria are ambiguous."
)


class AnthropicCompilerProvider(CompilerProvider):
    version = f"anthropic/{_MODEL}"

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def compile(self, market: RawMarketData) -> ContractSchema:
        prompt = (
            f"Market: {market.title}\n\n"
            f"Description: {market.description}\n\n"
            f"Resolution source: {market.resolution_source or 'not specified'}\n\n"
            f"Deadline: {market.deadline.isoformat()}"
        )
        message = self._client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            tools=[_TOOL_DEF],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_block = next(b for b in message.content if b.type == "tool_use")
        data = tool_block.input
        return ContractSchema(
            yes_conditions=data["yes_conditions"],
            no_conditions=data["no_conditions"],
            exclusions=data["exclusions"],
            ambiguity_terms=[AmbiguityFlag(**a) for a in data["ambiguity_terms"]],
            counterexamples=[Counterexample(**c) for c in data["counterexamples"]],
            compiler_confidence=float(data["compiler_confidence"]),
        )
```

- [ ] **Step 4: Create src/parallax/compiler/repository.py**

```python
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import CompiledContract
from parallax.shared.schemas import ContractSchema


class ContractRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def store(self, raw_market_id: str, contract: ContractSchema, version: str) -> CompiledContract:
        record = CompiledContract(
            id=uuid.uuid4(),
            raw_market_id=raw_market_id,
            contract_json=contract.model_dump(),
            compiler_confidence=contract.compiler_confidence,
            compiler_version=version,
            compiled_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_for_market(self, raw_market_id: str) -> CompiledContract | None:
        return (
            self._session.query(CompiledContract)
            .filter(CompiledContract.raw_market_id == raw_market_id)
            .order_by(CompiledContract.compiled_at.desc())
            .first()
        )
```

- [ ] **Step 5: Create src/parallax/compiler/service.py**

```python
from __future__ import annotations
from parallax.compiler.provider import CompilerProvider
from parallax.compiler.repository import ContractRepository
from parallax.audit.service import AuditService
from parallax.db.models import CompiledContract
from parallax.shared.schemas import RawMarketData


class CompilerService:
    def __init__(
        self,
        provider: CompilerProvider,
        repo: ContractRepository,
        audit: AuditService,
    ) -> None:
        self._provider = provider
        self._repo = repo
        self._audit = audit

    def compile_market(self, market: RawMarketData) -> CompiledContract:
        contract = self._provider.compile(market)
        raw_market_id = f"{market.platform}:{market.market_id}"
        record = self._repo.store(raw_market_id, contract, self._provider.version)
        self._audit.contract_compiled(raw_market_id, contract.compiler_confidence, self._provider.version)
        return record
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_compiler.py -v
```
Expected: `3 passed`

- [ ] **Step 7: Commit**

```bash
git add src/parallax/compiler/ tests/unit/test_compiler.py
git commit -m "feat: CompilerProvider ABC, AnthropicCompilerProvider (tool_use), CompilerService"
```

---

*— End of Phase 1 —*

---

## Phase 2 — Semantic Layer

### Task 10: Identity module

**Files:**
- Create: `src/parallax/identity/__init__.py`
- Create: `src/parallax/identity/repository.py`
- Create: `src/parallax/identity/service.py`

Each Polymarket event group becomes one `CanonicalEvent`. The `platform_group_key`
is `"{platform}:{group_id}"` and is the unique deduplication key.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_identity.py
from unittest.mock import MagicMock
import uuid

def test_event_repository_get_by_group_key_returns_none_when_missing():
    from parallax.identity.repository import EventRepository
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    repo = EventRepository(session)
    result = repo.get_by_group_key("polymarket:g1")
    assert result is None

def test_event_repository_create():
    from parallax.identity.repository import EventRepository
    from parallax.db.models import CanonicalEvent
    session = MagicMock()
    repo = EventRepository(session)
    event = repo.create(name="US Election 2026", domain="politics", platform_group_key="polymarket:g1")
    session.add.assert_called_once()
    session.flush.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, CanonicalEvent)
    assert added.platform_group_key == "polymarket:g1"

def test_identity_service_creates_canonical_event_on_first_market():
    from parallax.identity.service import IdentityService
    from parallax.identity.repository import EventRepository
    from parallax.db.models import RawMarket
    event_repo = MagicMock(spec=EventRepository)
    event_repo.get_by_group_key.return_value = None
    created = MagicMock()
    created.id = uuid.uuid4()
    event_repo.create.return_value = created
    event_repo.link_market.return_value = None
    market = MagicMock(spec=RawMarket)
    market.id = "polymarket:m1"
    market.title = "Will A win?"
    market.group_id = "g1"
    market.platform = "polymarket"
    market.category = "politics"
    svc = IdentityService(event_repo)
    canonical = svc.resolve(market)
    event_repo.get_by_group_key.assert_called_once_with("polymarket:g1")
    event_repo.create.assert_called_once()
    event_repo.link_market.assert_called_once()
    assert canonical.id == created.id

def test_identity_service_reuses_existing_event():
    from parallax.identity.service import IdentityService
    from parallax.identity.repository import EventRepository
    from parallax.db.models import RawMarket, CanonicalEvent
    existing = MagicMock(spec=CanonicalEvent)
    existing.id = uuid.uuid4()
    event_repo = MagicMock(spec=EventRepository)
    event_repo.get_by_group_key.return_value = existing
    market = MagicMock(spec=RawMarket)
    market.id = "polymarket:m2"
    market.group_id = "g1"
    market.platform = "polymarket"
    market.category = "politics"
    svc = IdentityService(event_repo)
    canonical = svc.resolve(market)
    event_repo.create.assert_not_called()
    assert canonical.id == existing.id
```

Run: `uv run pytest tests/unit/test_identity.py -v`
Expected: `4 errors`

- [ ] **Step 2: Create src/parallax/identity/repository.py**

```python
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import CanonicalEvent, MarketEventLink


class EventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_group_key(self, platform_group_key: str) -> CanonicalEvent | None:
        return (
            self._session.query(CanonicalEvent)
            .filter(CanonicalEvent.platform_group_key == platform_group_key)
            .first()
        )

    def create(self, name: str, domain: str, platform_group_key: str) -> CanonicalEvent:
        event = CanonicalEvent(
            id=uuid.uuid4(),
            name=name,
            domain=domain,
            platform_group_key=platform_group_key,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self._session.add(event)
        self._session.flush()
        return event

    def link_market(self, raw_market_id: str, canonical_event_id: uuid.UUID) -> None:
        link = MarketEventLink(
            raw_market_id=raw_market_id,
            canonical_event_id=canonical_event_id,
        )
        self._session.merge(link)
        self._session.flush()
```

- [ ] **Step 3: Create src/parallax/identity/service.py**

```python
from __future__ import annotations
from parallax.db.models import RawMarket, CanonicalEvent
from parallax.identity.repository import EventRepository


class IdentityService:
    def __init__(self, event_repo: EventRepository) -> None:
        self._repo = event_repo

    def resolve(self, market: RawMarket) -> CanonicalEvent:
        """Find or create the canonical event for this market."""
        group_key = f"{market.platform}:{market.group_id}" if market.group_id else f"{market.platform}:{market.id}"
        existing = self._repo.get_by_group_key(group_key)
        if existing:
            self._repo.link_market(market.id, existing.id)
            return existing
        domain = (market.category or "general").lower()
        event = self._repo.create(
            name=market.title,
            domain=domain,
            platform_group_key=group_key,
        )
        self._repo.link_market(market.id, event.id)
        return event
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_identity.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/identity/ tests/unit/test_identity.py
git commit -m "feat: IdentityService — find-or-create CanonicalEvent, link markets via group key"
```

---

### Task 11: GraphRepository interface + PostgresGraphRepository

**Files:**
- Create: `src/parallax/graph/__init__.py`
- Create: `src/parallax/graph/repository.py`
- Create: `src/parallax/graph/postgres_repository.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_graph_repository.py
from unittest.mock import MagicMock
import uuid

def test_graph_repository_is_abstract():
    from parallax.graph.repository import GraphRepository
    import inspect
    assert inspect.isabstract(GraphRepository)

def test_postgres_graph_repository_add_relation():
    from parallax.graph.postgres_repository import PostgresGraphRepository
    from parallax.graph.repository import RelationCreate
    from parallax.shared.schemas import RelationType
    from parallax.db.models import MarketRelation
    session = MagicMock()
    repo = PostgresGraphRepository(session)
    rel = RelationCreate(
        from_market_id="polymarket:m1",
        to_market_id="polymarket:m2",
        relation_type=RelationType.MUTUALLY_EXCLUSIVE,
        confidence=0.95,
        evidence={"stage": "stage1_constraint", "price_sum": 0.92},
        created_by="stage1_constraint",
    )
    repo.add_relation(rel)
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert isinstance(added, MarketRelation)
    assert added.relation_type == "mutually_exclusive"

def test_postgres_graph_repository_find_groups():
    from parallax.graph.postgres_repository import PostgresGraphRepository
    from parallax.db.models import RawMarket
    m1 = MagicMock(spec=RawMarket)
    m1.group_id = "g1"
    m1.platform = "polymarket"
    m2 = MagicMock(spec=RawMarket)
    m2.group_id = "g1"
    m2.platform = "polymarket"
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = [m1, m2]
    repo = PostgresGraphRepository(session)
    groups = repo.find_active_groups("polymarket")
    assert len(groups) >= 1
```

Run: `uv run pytest tests/unit/test_graph_repository.py -v`
Expected: `3 errors`

- [ ] **Step 2: Create src/parallax/graph/repository.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from parallax.db.models import MarketRelation, RawMarket
from parallax.shared.schemas import RelationType


@dataclass
class RelationCreate:
    from_market_id: str
    to_market_id: str
    relation_type: RelationType
    confidence: float
    evidence: dict
    created_by: str  # "stage1_constraint" | "stage2_llm"


class GraphRepository(ABC):
    """Graph-semantic interface. Backing store (PostgreSQL, Neo4j) is an implementation detail."""

    @abstractmethod
    def add_relation(self, relation: RelationCreate) -> MarketRelation:
        ...

    @abstractmethod
    def get_relations_for_market(self, market_id: str) -> list[MarketRelation]:
        ...

    @abstractmethod
    def find_active_groups(self, platform: str) -> dict[str, list[RawMarket]]:
        """Return {group_id: [RawMarket, ...]} for all active grouped markets on the platform."""
        ...
```

- [ ] **Step 3: Create src/parallax/graph/postgres_repository.py**

```python
from __future__ import annotations
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import MarketRelation, RawMarket
from parallax.graph.repository import GraphRepository, RelationCreate


class PostgresGraphRepository(GraphRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_relation(self, relation: RelationCreate) -> MarketRelation:
        record = MarketRelation(
            id=uuid.uuid4(),
            from_market_id=relation.from_market_id,
            to_market_id=relation.to_market_id,
            relation_type=relation.relation_type.value,
            confidence=relation.confidence,
            evidence=relation.evidence,
            created_by=relation.created_by,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_relations_for_market(self, market_id: str) -> list[MarketRelation]:
        return (
            self._session.query(MarketRelation)
            .filter(
                (MarketRelation.from_market_id == market_id)
                | (MarketRelation.to_market_id == market_id)
            )
            .all()
        )

    def find_active_groups(self, platform: str) -> dict[str, list[RawMarket]]:
        markets = (
            self._session.query(RawMarket)
            .filter(
                RawMarket.platform == platform,
                RawMarket.is_closed == False,
                RawMarket.group_id.isnot(None),
            )
            .all()
        )
        groups: dict[str, list[RawMarket]] = defaultdict(list)
        for m in markets:
            groups[m.group_id].append(m)
        return dict(groups)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_graph_repository.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/graph/ tests/unit/test_graph_repository.py
git commit -m "feat: GraphRepository ABC and PostgresGraphRepository (adjacency table)"
```

---

### Task 12: Stage 1 constraint detector

**Files:**
- Create: `src/parallax/graph/detector.py`

Finds groups where `sum(YES prices) < THRESHOLD` → `exhaustive_set_mispricing` candidate.
`YES price` = `outcome_prices[0]` for each market in a Polymarket group.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_graph_detector.py
from unittest.mock import MagicMock
from datetime import datetime, timezone

def _make_db_market(market_id, group_id, yes_price):
    from parallax.db.models import RawMarket
    m = MagicMock(spec=RawMarket)
    m.id = f"polymarket:{market_id}"
    m.group_id = group_id
    m.platform = "polymarket"
    m.outcome_prices = [yes_price, 1 - yes_price]
    m.deadline = datetime(2026, 11, 5, tzinfo=timezone.utc)
    return m

def test_detects_mispriced_exhaustive_set():
    from parallax.graph.detector import Stage1ConstraintDetector
    graph_repo = MagicMock()
    graph_repo.find_active_groups.return_value = {
        "g1": [
            _make_db_market("mA", "g1", 0.44),
            _make_db_market("mB", "g1", 0.50),
        ]
    }
    detector = Stage1ConstraintDetector(graph_repo, threshold=0.97)
    results = detector.detect("polymarket")
    assert len(results) == 1
    assert results[0]["group_id"] == "g1"
    assert abs(results[0]["price_sum"] - 0.94) < 0.001
    assert results[0]["gap"] > 0

def test_skips_fairly_priced_set():
    from parallax.graph.detector import Stage1ConstraintDetector
    graph_repo = MagicMock()
    graph_repo.find_active_groups.return_value = {
        "g2": [
            _make_db_market("mC", "g2", 0.50),
            _make_db_market("mD", "g2", 0.49),
        ]
    }
    detector = Stage1ConstraintDetector(graph_repo, threshold=0.97)
    results = detector.detect("polymarket")
    assert results == []

def test_skips_single_market_groups():
    from parallax.graph.detector import Stage1ConstraintDetector
    graph_repo = MagicMock()
    graph_repo.find_active_groups.return_value = {
        "g3": [_make_db_market("mE", "g3", 0.50)]
    }
    detector = Stage1ConstraintDetector(graph_repo, threshold=0.97)
    results = detector.detect("polymarket")
    assert results == []

def test_records_relations_for_detected_set():
    from parallax.graph.detector import Stage1ConstraintDetector
    graph_repo = MagicMock()
    graph_repo.find_active_groups.return_value = {
        "g1": [
            _make_db_market("mA", "g1", 0.44),
            _make_db_market("mB", "g1", 0.50),
        ]
    }
    detector = Stage1ConstraintDetector(graph_repo, threshold=0.97)
    detector.detect_and_persist("polymarket")
    assert graph_repo.add_relation.call_count >= 1
```

Run: `uv run pytest tests/unit/test_graph_detector.py -v`
Expected: `4 errors`

- [ ] **Step 2: Create src/parallax/graph/detector.py**

```python
from __future__ import annotations
from itertools import combinations
from parallax.db.models import RawMarket
from parallax.graph.repository import GraphRepository, RelationCreate
from parallax.shared.schemas import RelationType


class Stage1ConstraintDetector:
    """
    Finds intra-platform mutually exclusive sets where sum(YES prices) < threshold.
    YES price = outcome_prices[0] for each market (Polymarket convention).
    """

    def __init__(self, graph_repo: GraphRepository, threshold: float = 0.97) -> None:
        self._repo = graph_repo
        self._threshold = threshold

    def detect(self, platform: str) -> list[dict]:
        """Return metadata dicts for groups that pass the constraint filter."""
        groups = self._repo.find_active_groups(platform)
        results = []
        for group_id, markets in groups.items():
            if len(markets) < 2:
                continue
            price_sum = sum(m.outcome_prices[0] for m in markets)
            if price_sum < self._threshold:
                results.append(
                    {
                        "group_id": group_id,
                        "platform": platform,
                        "markets": markets,
                        "price_sum": price_sum,
                        "gap": self._threshold - price_sum,
                    }
                )
        return results

    def detect_and_persist(self, platform: str) -> list[dict]:
        """Detect + write MUTUALLY_EXCLUSIVE relations for every pair in each mispriced group."""
        results = self.detect(platform)
        for group in results:
            markets: list[RawMarket] = group["markets"]
            price_sum = group["price_sum"]
            for m_a, m_b in combinations(markets, 2):
                self._repo.add_relation(
                    RelationCreate(
                        from_market_id=m_a.id,
                        to_market_id=m_b.id,
                        relation_type=RelationType.MUTUALLY_EXCLUSIVE,
                        confidence=0.90,
                        evidence={
                            "stage": "stage1_constraint",
                            "group_id": group["group_id"],
                            "price_sum": price_sum,
                            "gap": group["gap"],
                            "market_count": len(markets),
                        },
                        created_by="stage1_constraint",
                    )
                )
        return results
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_graph_detector.py -v
```
Expected: `4 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/graph/detector.py tests/unit/test_graph_detector.py
git commit -m "feat: Stage1ConstraintDetector — finds exhaustive mispriced sets by YES price sum"
```

---

### Task 13: ProverService

**Files:**
- Create: `src/parallax/prover/__init__.py`
- Create: `src/parallax/prover/repository.py`
- Create: `src/parallax/prover/service.py`

Proves payoff for groups detected by Stage 1. A candidate is only emitted if:
1. `worst_case_payoff` after friction > -∞ (always true but the breaking scenario must exist)
2. A `breaking_scenario` is explicitly named in the PayoffMatrix
3. The net payoff in the expected case > 0 (i.e., `price_sum < 1 - friction`)

Formula for exhaustive set:
- `total_cost = sum(YES prices)`
- `friction = total_cost * friction_bps / 10_000`
- `net_payoff = 1.0 - total_cost - friction`
- Breaking scenario payoff: `-(total_cost)` (event cancelled, all positions worthless)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_prover.py
from unittest.mock import MagicMock
from datetime import datetime, timezone

def _make_db_market(market_id, group_id, yes_price, outcome="Win"):
    from parallax.db.models import RawMarket
    m = MagicMock(spec=RawMarket)
    m.id = f"polymarket:{market_id}"
    m.group_id = group_id
    m.platform = "polymarket"
    m.title = f"Will {outcome} win?"
    m.outcomes = [outcome, "No"]
    m.outcome_prices = [yes_price, round(1 - yes_price, 4)]
    m.deadline = datetime(2026, 11, 5, tzinfo=timezone.utc)
    return m

def test_prover_emits_candidate_for_mispriced_group():
    from parallax.prover.service import ProverService
    from parallax.shared.schemas import OpportunityType
    repo = MagicMock()
    stored = MagicMock()
    stored.id = "cand-001"
    repo.store.return_value = stored
    audit = MagicMock()
    svc = ProverService(repo, audit, friction_bps=50)
    markets = [
        _make_db_market("mA", "g1", 0.44, "A"),
        _make_db_market("mB", "g1", 0.50, "B"),
    ]
    candidate = svc.prove_group("g1", markets)
    assert candidate is not None
    repo.store.assert_called_once()
    stored_call = repo.store.call_args[0]
    payoff_matrix = stored_call[1]
    assert payoff_matrix.opportunity_type == OpportunityType.EXHAUSTIVE_SET_MISPRICING
    assert payoff_matrix.total_cost == pytest.approx(0.94)
    assert payoff_matrix.breaking_scenario is not None
    assert payoff_matrix.breaking_scenario.is_breaking is True

def test_prover_rejects_fairly_priced_group():
    from parallax.prover.service import ProverService
    repo = MagicMock()
    audit = MagicMock()
    svc = ProverService(repo, audit, friction_bps=50)
    markets = [
        _make_db_market("mC", "g2", 0.50, "C"),
        _make_db_market("mD", "g2", 0.49, "D"),
    ]
    candidate = svc.prove_group("g2", markets)
    assert candidate is None
    repo.store.assert_not_called()

def test_prover_breaking_scenario_has_negative_payoff():
    from parallax.prover.service import ProverService
    repo = MagicMock()
    stored = MagicMock()
    stored.id = "cand-002"
    repo.store.return_value = stored
    svc = ProverService(repo, MagicMock(), friction_bps=50)
    markets = [
        _make_db_market("mE", "g3", 0.30, "E"),
        _make_db_market("mF", "g3", 0.55, "F"),
    ]
    svc.prove_group("g3", markets)
    payoff_matrix = repo.store.call_args[0][1]
    assert payoff_matrix.breaking_scenario.payoff < 0
    assert payoff_matrix.worst_case_payoff < 0

import pytest
```

Run: `uv run pytest tests/unit/test_prover.py -v`
Expected: `3 errors`

- [ ] **Step 2: Create src/parallax/prover/repository.py**

```python
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import OpportunityCandidate
from parallax.shared.schemas import PayoffMatrix, RiskScore, CourtDecision


class CandidateRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def store(
        self,
        market_ids: list[str],
        payoff_matrix: PayoffMatrix,
        risk_score: RiskScore,
        court_decision: CourtDecision,
    ) -> OpportunityCandidate:
        record = OpportunityCandidate(
            id=uuid.uuid4(),
            market_ids=market_ids,
            payoff_matrix=payoff_matrix.model_dump(),
            opportunity_type=payoff_matrix.opportunity_type.value,
            worst_case_payoff=payoff_matrix.worst_case_payoff,
            friction_bps=payoff_matrix.friction_bps,
            risk_scores=risk_score.model_dump(),
            court_decision=court_decision.value,
            detected_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def list_open(self) -> list[OpportunityCandidate]:
        return (
            self._session.query(OpportunityCandidate)
            .filter(OpportunityCandidate.status == "open")
            .order_by(OpportunityCandidate.detected_at.desc())
            .all()
        )

    def get(self, candidate_id: uuid.UUID) -> OpportunityCandidate | None:
        return self._session.get(OpportunityCandidate, candidate_id)
```

- [ ] **Step 3: Create src/parallax/prover/service.py**

```python
from __future__ import annotations
from parallax.db.models import RawMarket, OpportunityCandidate
from parallax.prover.repository import CandidateRepository
from parallax.audit.service import AuditService
from parallax.shared.schemas import (
    Leg, Scenario, PayoffMatrix, RiskScore,
    OpportunityType, CourtDecision,
)

_REJECT_THRESHOLD = 0.97


class ProverService:
    def __init__(
        self,
        repo: CandidateRepository,
        audit: AuditService,
        friction_bps: int = 50,
    ) -> None:
        self._repo = repo
        self._audit = audit
        self._friction_bps = friction_bps

    def prove_group(
        self,
        group_id: str,
        markets: list[RawMarket],
    ) -> OpportunityCandidate | None:
        """
        Prove whether a group of markets forms an exhaustive_set_mispricing.
        Returns None if the group does not pass the proof.
        A candidate is emitted only if net_payoff > 0 and breaking_scenario is explicitly named.
        """
        yes_prices = [m.outcome_prices[0] for m in markets]
        total_cost = sum(yes_prices)
        friction = total_cost * self._friction_bps / 10_000
        net_payoff = round(1.0 - total_cost - friction, 6)

        if net_payoff <= 0:
            return None

        legs = [
            Leg(
                market_id=m.id,
                side="YES",
                price=m.outcome_prices[0],
                quantity=1.0,
                outcome=m.outcomes[0] if m.outcomes else "YES",
                platform=m.platform,
            )
            for m in markets
        ]

        # One scenario per market: that market resolves YES (the normal case)
        win_scenarios = [
            Scenario(
                name=f"{m.outcomes[0] if m.outcomes else 'market'}_wins",
                description=f"{m.id} resolves YES; all others resolve NO.",
                is_breaking=False,
                payoff=round(net_payoff, 6),
            )
            for m in markets
        ]

        # Breaking scenario: all markets resolve NO (event cancelled / none of the above)
        breaking = Scenario(
            name="event_cancelled_or_no_winner",
            description=(
                "All markets in the group resolve NO — event cancelled, postponed "
                "past deadline, or an unlisted outcome occurs."
            ),
            is_breaking=True,
            payoff=round(-total_cost, 6),
        )

        payoff_matrix = PayoffMatrix(
            legs=legs,
            total_cost=round(total_cost, 6),
            scenarios=win_scenarios + [breaking],
            worst_case_payoff=round(-total_cost, 6),
            best_case_payoff=round(net_payoff, 6),
            breaking_scenario=breaking,
            opportunity_type=OpportunityType.EXHAUSTIVE_SET_MISPRICING,
            friction_bps=self._friction_bps,
        )

        # Minimal risk for Stage 1 intra-platform: same platform, same group, same deadline
        risk = RiskScore.combine(oracle=0.05, deadline=0.05, semantic=0.10)

        record = self._repo.store(
            market_ids=[m.id for m in markets],
            payoff_matrix=payoff_matrix,
            risk_score=risk,
            court_decision=CourtDecision.WATCHLIST,
        )
        self._audit.candidate_created(
            str(record.id),
            OpportunityType.EXHAUSTIVE_SET_MISPRICING.value,
            payoff_matrix.worst_case_payoff,
        )
        return record
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_prover.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/prover/ tests/unit/test_prover.py
git commit -m "feat: ProverService — exhaustive set mispricing proof with explicit breaking scenario"
```

---

*— End of Phase 2 —*


---

## Phase 3 — Risk, Tracking, and Stubs

### Task 14: DivergenceService

**Files:**
- Create: `src/parallax/divergence/service.py`
- Create: `tests/unit/test_divergence.py`

**Purpose:** Score each opportunity candidate's risk of resolution divergence.
Three independent risk dimensions, combined into a scalar `risk_score` ∈ [0.0, 1.0]:
- `oracle_risk`: how reliable / ambiguous is the resolution oracle?
- `deadline_risk`: how close together are the market deadlines?
- `semantic_risk`: how similar are the compiled `yes_conditions` / `no_conditions`?

A high `risk_score` does not block the candidate — it informs the Trade Court.
This is a pure computation layer: no DB writes, no API calls.

**Risk scoring rules:**

| Dimension | Signal | Score |
|-----------|--------|-------|
| `oracle_risk` | All markets share same `resolution_source` | 0.05 |
| `oracle_risk` | Any market has `resolution_source = None` | 0.60 |
| `oracle_risk` | All markets have different `resolution_source` | 0.30 |
| `deadline_risk` | All deadlines within 24 hours of each other | 0.05 |
| `deadline_risk` | Widest gap ≥ 7 days | 0.80 |
| `deadline_risk` | Gap between 24h–7d (linear interpolation) | 0.05 + (gap_hours - 24) / (168 - 24) * 0.75 |
| `semantic_risk` | Compiled contracts available for all markets | Jaccard distance on yes_condition tokens |
| `semantic_risk` | Any contract not yet compiled | 0.50 (unknown) |

Combined: `risk_score = (oracle_risk + deadline_risk + semantic_risk) / 3`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_divergence.py
from datetime import datetime, timezone, timedelta
from parallax.divergence.service import DivergenceService
from parallax.shared.schemas import RiskScore


def _market(resolution_source=None, deadline=None):
    from parallax.shared.schemas import RawMarketData
    return RawMarketData(
        platform="polymarket",
        market_id="abc",
        title="T",
        description="D",
        resolution_criteria="RC",
        outcomes=["Yes", "No"],
        outcome_prices=[0.40, 0.60],
        category=None,
        group_id="g1",
        deadline=deadline or datetime(2026, 5, 1, tzinfo=timezone.utc),
        is_closed=False,
        resolution_source=resolution_source,
        raw_payload={},
    )


def test_same_oracle_low_risk():
    svc = DivergenceService()
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    markets = [_market("UMA", now), _market("UMA", now)]
    score = svc.score(markets, contracts=None)
    assert isinstance(score, RiskScore)
    assert score.oracle_risk == 0.05


def test_none_oracle_high_risk():
    svc = DivergenceService()
    now = datetime(2026, 5, 1, tzinfo=timezone.utc)
    markets = [_market(None, now), _market("UMA", now)]
    score = svc.score(markets, contracts=None)
    assert score.oracle_risk == 0.60


def test_wide_deadline_gap_high_risk():
    svc = DivergenceService()
    d1 = datetime(2026, 5, 1, tzinfo=timezone.utc)
    d2 = d1 + timedelta(days=10)
    markets = [_market("UMA", d1), _market("UMA", d2)]
    score = svc.score(markets, contracts=None)
    assert score.deadline_risk >= 0.75
```

Run: `uv run pytest tests/unit/test_divergence.py -v`
Expected: `3 failed` (module does not exist)

- [ ] **Step 2: Implement `DivergenceService`**

```python
# src/parallax/divergence/service.py
import math
from datetime import datetime
from parallax.shared.schemas import RawMarketData, CompiledContract, RiskScore


class DivergenceService:

    def score(
        self,
        markets: list[RawMarketData],
        contracts: list[CompiledContract] | None,
    ) -> RiskScore:
        oracle = self._oracle_risk(markets)
        deadline = self._deadline_risk(markets)
        semantic = self._semantic_risk(markets, contracts)
        return RiskScore.combine(oracle, deadline, semantic)

    # --- private ---

    def _oracle_risk(self, markets: list[RawMarketData]) -> float:
        sources = {m.resolution_source for m in markets}
        if None in sources:
            return 0.60
        if len(sources) == 1:
            return 0.05
        return 0.30

    def _deadline_risk(self, markets: list[RawMarketData]) -> float:
        deadlines = [m.deadline for m in markets]
        gap_hours = (max(deadlines) - min(deadlines)).total_seconds() / 3600
        if gap_hours <= 24:
            return 0.05
        if gap_hours >= 168:  # 7 days
            return 0.80
        return round(0.05 + (gap_hours - 24) / (168 - 24) * 0.75, 4)

    def _semantic_risk(
        self,
        markets: list[RawMarketData],
        contracts: list[CompiledContract] | None,
    ) -> float:
        if not contracts or len(contracts) < len(markets):
            return 0.50
        # Jaccard distance on yes_condition token sets
        token_sets = [
            set(" ".join(c.yes_conditions).lower().split())
            for c in contracts
        ]
        union = token_sets[0].union(*token_sets[1:])
        intersection = token_sets[0].intersection(*token_sets[1:])
        if not union:
            return 0.50
        jaccard_similarity = len(intersection) / len(union)
        return round(1.0 - jaccard_similarity, 4)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_divergence.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/divergence/ src/parallax/shared/schemas.py \
        tests/unit/test_divergence.py
git commit -m "feat: DivergenceService — oracle/deadline/semantic risk scoring"
```

---

### Task 15: TrackerService + PaperPosition tracking

**Files:**
- Create: `src/parallax/tracker/repository.py`
- Create: `src/parallax/tracker/service.py`
- Create: `tests/unit/test_tracker.py`

**Purpose:** Open, update, and close paper positions linked to approved opportunity candidates.
`TrackerService` writes to `PaperPosition` rows; `AutopsyService` (Task 17) reads them on resolution.
This is paper-only — no real execution in Slice 1.

**Contract:**
- `open_position(candidate_id, legs)` → `PaperPosition`
  - `legs` is `list[Leg]` from `PayoffMatrix` — each leg is one market side with a notional cost
  - status starts at `OPEN`
  - `opened_at` = UTC now
  - emits `AuditEvent` via `AuditService`
- `close_position(position_id, resolution_outcomes)` → `PaperPosition`
  - `resolution_outcomes: dict[str, str]` — market_id → "Yes" | "No" | "N/A"
  - computes `actual_pnl` from leg payoffs
  - status → `CLOSED`
  - emits `AuditEvent`
- `get_open_positions()` → `list[PaperPosition]`

**`PaperPosition` DB model** (already declared in `db/models.py`):
```python
id: UUID; candidate_id: UUID (FK); status: str; legs_json: JSON
opened_at: datetime; closed_at: datetime | None; actual_pnl: float | None
```

`Leg` is already defined in `shared/schemas.py` (Task 2). Fields used here: `market_id`, `side`, `price`, `quantity`, `cost`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_tracker.py
import uuid
from unittest.mock import MagicMock
from parallax.tracker.service import TrackerService
from parallax.shared.schemas import Leg


def _make_legs():
    return [
        Leg(market_id="poly:A", side="YES", price=0.30, quantity=1.0, cost=0.30),
        Leg(market_id="poly:B", side="YES", price=0.35, quantity=1.0, cost=0.35),
        Leg(market_id="poly:C", side="YES", price=0.28, quantity=1.0, cost=0.28),
    ]


def test_open_position_returns_open_status():
    repo = MagicMock()
    audit = MagicMock()
    repo.create.return_value = MagicMock(id=uuid.uuid4(), status="OPEN")
    svc = TrackerService(repo=repo, audit=audit)
    position = svc.open_position(candidate_id=uuid.uuid4(), legs=_make_legs())
    assert position.status == "OPEN"
    audit.paper_trade_opened.assert_called_once()


def test_close_position_computes_pnl():
    repo = MagicMock()
    audit = MagicMock()
    candidate_id = uuid.uuid4()
    position_id = uuid.uuid4()
    legs = _make_legs()
    mock_position = MagicMock()
    mock_position.id = position_id
    mock_position.status = "OPEN"
    mock_position.legs_json = [l.model_dump() for l in legs]
    repo.get.return_value = mock_position
    repo.update.return_value = MagicMock(status="CLOSED", actual_pnl=pytest.approx(0.07, abs=0.01))
    svc = TrackerService(repo=repo, audit=audit)
    # All three YES legs win: each pays 1.0, cost was 0.93 total → pnl = 0.07
    closed = svc.close_position(
        position_id=position_id,
        resolution_outcomes={"poly:A": "Yes", "poly:B": "Yes", "poly:C": "Yes"},
    )
    assert closed.status == "CLOSED"
```

Run: `uv run pytest tests/unit/test_tracker.py -v`
Expected: `2 failed`

- [ ] **Step 2: Implement `TrackerRepository`**

```python
# src/parallax/tracker/repository.py
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import PaperPosition
from parallax.shared.schemas import Leg


class TrackerRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, candidate_id: uuid.UUID, legs: list[Leg]) -> PaperPosition:
        position = PaperPosition(
            id=uuid.uuid4(),
            candidate_id=candidate_id,
            status="OPEN",
            legs_json=[l.model_dump() for l in legs],
            opened_at=datetime.now(timezone.utc),
        )
        self._session.add(position)
        self._session.flush()
        return position

    def get(self, position_id: uuid.UUID) -> PaperPosition:
        return self._session.get(PaperPosition, position_id)

    def update(self, position: PaperPosition) -> PaperPosition:
        self._session.flush()
        return position

    def get_open(self) -> list[PaperPosition]:
        from sqlalchemy import select
        stmt = select(PaperPosition).where(PaperPosition.status == "OPEN")
        return list(self._session.execute(stmt).scalars())
```

- [ ] **Step 3: Implement `TrackerService`**

```python
# src/parallax/tracker/service.py
import uuid
from datetime import datetime, timezone
from parallax.tracker.repository import TrackerRepository
from parallax.audit.service import AuditService
from parallax.shared.schemas import Leg, PaperPosition as PaperPositionSchema


class TrackerService:
    def __init__(self, repo: TrackerRepository, audit: AuditService):
        self._repo = repo
        self._audit = audit

    def open_position(
        self, candidate_id: uuid.UUID, legs: list[Leg]
    ):
        position = self._repo.create(candidate_id=candidate_id, legs=legs)
        total_cost = sum(l.cost for l in legs)
        self._audit.paper_trade_opened(str(position.id), str(candidate_id), total_cost)
        return position

    def close_position(self, position_id: uuid.UUID, resolution_outcomes: dict[str, str]):
        position = self._repo.get(position_id)
        legs = [Leg(**l) for l in position.legs_json]
        actual_pnl = self._compute_pnl(legs, resolution_outcomes)
        position.status = "CLOSED"
        position.closed_at = datetime.now(timezone.utc)
        position.actual_pnl = actual_pnl
        return self._repo.update(position)

    def get_open_positions(self):
        return self._repo.get_open()

    # --- private ---

    def _compute_pnl(
        self, legs: list[Leg], outcomes: dict[str, str]
    ) -> float:
        total_cost = sum(l.cost for l in legs)
        total_payoff = 0.0
        for leg in legs:
            outcome = outcomes.get(leg.market_id, "N/A")
            won = (leg.side == "YES" and outcome == "Yes") or (
                leg.side == "NO" and outcome == "No"
            )
            if won:
                total_payoff += leg.quantity  # pays 1.0 per share on win
        return round(total_payoff - total_cost, 6)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_tracker.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/tracker/ tests/unit/test_tracker.py
git commit -m "feat: TrackerService — paper position open/close/pnl with audit trail"
```

---

### Task 16: CourtService stub

**Files:**
- Create: `src/parallax/court/service.py`
- Create: `tests/unit/test_stubs.py` (partial — CourtService section)

**Purpose:** In Slice 1, the Trade Court is a stub that auto-approves every candidate that passes
the `ProverService` payoff threshold and stamps it `WATCHLIST`. The full adversarial
Prosecutor/Defense/Judge loop is Slice 2. The stub must implement the final interface so
downstream code is not coupled to stub behavior.

**Final interface (designed for Slice 2 even if stubbed now):**
```python
class CourtService:
    def review(self, candidate_id: UUID) -> CourtDecision
    def get_decision(self, candidate_id: UUID) -> CourtDecision | None
```

`CourtDecision` is already defined in `shared/schemas.py` (Task 2) with values `APPROVED`, `WATCHLIST`, `REJECTED`, `PENDING`, `PAPER_TRADE`, `CANDIDATE_FOR_LIVE`. No addition needed here.

Stub behavior: `review()` always returns `WATCHLIST`. Writes the decision to the
`OpportunityCandidate` row via `CandidateRepository`.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_stubs.py
import uuid
from unittest.mock import MagicMock
from parallax.court.service import CourtService
from parallax.shared.schemas import CourtDecision


def test_court_stub_returns_watchlist():
    repo = MagicMock()
    audit = MagicMock()
    candidate_id = uuid.uuid4()
    mock_candidate = MagicMock()
    mock_candidate.id = candidate_id
    repo.get.return_value = mock_candidate
    repo.update_decision.return_value = mock_candidate
    svc = CourtService(repo=repo, audit=audit)
    decision = svc.review(candidate_id)
    assert decision == CourtDecision.WATCHLIST
```

Run: `uv run pytest tests/unit/test_stubs.py::test_court_stub_returns_watchlist -v`
Expected: `1 failed`

- [ ] **Step 2: Implement `CourtService` stub**

```python
# src/parallax/court/service.py
import uuid
from parallax.shared.schemas import CourtDecision
from parallax.prover.repository import CandidateRepository
from parallax.audit.service import AuditService


class CourtService:
    """Slice 1 stub: auto-approves to WATCHLIST. Slice 2 replaces with adversarial review."""

    def __init__(self, repo: CandidateRepository, audit: AuditService):
        self._repo = repo
        self._audit = audit

    def review(self, candidate_id: uuid.UUID) -> CourtDecision:
        decision = CourtDecision.WATCHLIST
        self._repo.update_decision(candidate_id, decision)
        self._audit.court_decision(str(candidate_id), decision.value)
        return decision

    def get_decision(self, candidate_id: uuid.UUID) -> CourtDecision | None:
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            return None
        return CourtDecision(candidate.court_decision) if candidate.court_decision else None
```

Also add `update_decision` and `get` to `CandidateRepository` (`src/parallax/prover/repository.py`):

```python
def get(self, candidate_id: uuid.UUID) -> OpportunityCandidate | None:
    return self._session.get(OpportunityCandidate, candidate_id)

def update_decision(
    self, candidate_id: uuid.UUID, decision: CourtDecision
) -> OpportunityCandidate:
    candidate = self._session.get(OpportunityCandidate, candidate_id)
    candidate.court_decision = decision.value
    self._session.flush()
    return candidate
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_stubs.py -v
```
Expected: `1 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/court/ src/parallax/prover/repository.py \
        src/parallax/shared/schemas.py tests/unit/test_stubs.py
git commit -m "feat: CourtService stub — WATCHLIST auto-approval, final interface for Slice 2"
```

---

### Task 17: SimulatorService stub

**Files:**
- Create: `src/parallax/simulator/service.py`
- Extend: `tests/unit/test_stubs.py`

**Purpose:** Slice 1 stub for execution simulation. Returns a `SimulationResult` with
mock friction applied. The real simulator (Slice 2) will model order book impact, slippage,
and partial fill probability. The stub is used by `PipelineRunner` to compute
post-friction worst-case payoff for display in the War Room.

`SimulationResult` is already defined in `shared/schemas.py` (Task 2). No addition needed here.

Stub formula: `simulated_pnl = worst_case_payoff - (total_cost * friction_bps / 10_000)`

- [ ] **Step 1: Write failing test** (append to `test_stubs.py`)

```python
def test_simulator_stub_applies_friction():
    from parallax.simulator.service import SimulatorService
    from parallax.shared.schemas import SimulationResult, PayoffMatrix, Scenario, Leg, OpportunityType

    svc = SimulatorService(friction_bps=50)
    matrix = PayoffMatrix(
        legs=[Leg(market_id="m1", side="YES", price=0.30, quantity=1.0, cost=0.30)],
        total_cost=0.30,
        scenarios=[],
        worst_case_payoff=0.05,
        best_case_payoff=0.70,
        breaking_scenario=Scenario(name="break", description="test", is_breaking=True, payoff=-0.30),
        opportunity_type=OpportunityType.MUTUALLY_EXCLUSIVE_MISPRICING,
        friction_bps=50,
    )
    result = svc.simulate(candidate_id="cand-001", payoff_matrix=matrix)
    assert isinstance(result, SimulationResult)
    assert result.friction_bps == 50
    assert result.simulated_pnl < matrix.worst_case_payoff
    assert result.fill_probability == 1.0
```

- [ ] **Step 2: Implement `SimulatorService` stub**

```python
# src/parallax/simulator/service.py
from parallax.shared.schemas import PayoffMatrix, SimulationResult


class SimulatorService:
    """Slice 1 stub: applies flat friction, assumes full fill. No order book model."""

    def __init__(self, friction_bps: int = 50):
        self._friction_bps = friction_bps

    def simulate(self, candidate_id: str, payoff_matrix: PayoffMatrix) -> SimulationResult:
        friction_cost = payoff_matrix.total_cost * self._friction_bps / 10_000
        simulated_pnl = round(payoff_matrix.worst_case_payoff - friction_cost, 6)
        return SimulationResult(
            candidate_id=candidate_id,
            simulated_pnl=simulated_pnl,
            friction_bps=self._friction_bps,
            fill_probability=1.0,
            is_executable=simulated_pnl > 0,
            note="stub — no order book model",
        )
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_stubs.py -v
```
Expected: `2 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/simulator/ src/parallax/shared/schemas.py \
        tests/unit/test_stubs.py
git commit -m "feat: SimulatorService stub — friction-adjusted pnl, final interface for Slice 2"
```

---

### Task 18: AutopsyService stub

**Files:**
- Create: `src/parallax/autopsy/repository.py`
- Create: `src/parallax/autopsy/service.py`
- Extend: `tests/unit/test_stubs.py`

**Purpose:** Records the outcome of resolved positions. In Slice 1 it writes an
`AutopsyRecord` row with `resolution_type` and `identity_error` flag; calibration logic
(Slice 2) reads these records to tune Stage 1 thresholds and Stage 2 prompts.

**`AutopsyRecord` DB model** (already declared in `db/models.py`):
```python
id: UUID; candidate_id: UUID; position_id: UUID | None
actual_resolution: JSON        # dict of market_id → outcome
resolution_type: str           # CORRECT | IDENTITY_ERROR | ORACLE_DIVERGENCE | CANCELLED
identity_error: bool           # True if relation was wrong (Stage 1/2 false positive)
created_at: datetime
```

`ResolutionType` is already defined in `shared/schemas.py` (Task 2). No addition needed here.

`AutopsyService.record(candidate_id, position_id, actual_resolution, resolution_type)`

- [ ] **Step 1: Write failing test** (append to `test_stubs.py`)

```python
def test_autopsy_records_identity_error():
    from parallax.autopsy.service import AutopsyService
    from parallax.shared.schemas import ResolutionType
    import uuid

    repo = MagicMock()
    repo.create.return_value = MagicMock(identity_error=True)
    svc = AutopsyService(repo=repo)
    record = svc.record(
        candidate_id=uuid.uuid4(),
        position_id=None,
        actual_resolution={"m1": "Yes", "m2": "Yes"},
        resolution_type=ResolutionType.IDENTITY_ERROR,
    )
    assert record.identity_error is True
    repo.create.assert_called_once()
```

- [ ] **Step 2: Implement `AutopsyRepository`**

```python
# src/parallax/autopsy/repository.py
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from parallax.db.models import AutopsyRecord
from parallax.shared.schemas import ResolutionType


class AutopsyRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(
        self,
        candidate_id: uuid.UUID,
        position_id: uuid.UUID | None,
        actual_resolution: dict,
        resolution_type: ResolutionType,
    ) -> AutopsyRecord:
        record = AutopsyRecord(
            id=uuid.uuid4(),
            candidate_id=candidate_id,
            position_id=position_id,
            actual_resolution=actual_resolution,
            resolution_type=resolution_type.value,
            identity_error=(resolution_type == ResolutionType.IDENTITY_ERROR),
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_identity_errors(self) -> list[AutopsyRecord]:
        from sqlalchemy import select
        stmt = select(AutopsyRecord).where(AutopsyRecord.identity_error.is_(True))
        return list(self._session.execute(stmt).scalars())
```

- [ ] **Step 3: Implement `AutopsyService`**

```python
# src/parallax/autopsy/service.py
import uuid
from parallax.autopsy.repository import AutopsyRepository
from parallax.shared.schemas import ResolutionType


class AutopsyService:
    def __init__(self, repo: AutopsyRepository):
        self._repo = repo

    def record(
        self,
        candidate_id: uuid.UUID,
        position_id: uuid.UUID | None,
        actual_resolution: dict[str, str],
        resolution_type: ResolutionType,
    ):
        return self._repo.create(
            candidate_id=candidate_id,
            position_id=position_id,
            actual_resolution=actual_resolution,
            resolution_type=resolution_type,
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_stubs.py -v
```
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add src/parallax/autopsy/ src/parallax/shared/schemas.py \
        tests/unit/test_stubs.py
git commit -m "feat: AutopsyService — resolution record + identity_error flag for calibration"
```

---

### Task 19: PipelineRunner — main orchestration loop

**Files:**
- Create: `src/parallax/pipeline/runner.py`
- Create: `tests/integration/test_pipeline.py`

**Purpose:** `PipelineRunner` is the single entry point that wires all modules together
and runs one complete proof cycle. The scheduler (APScheduler) calls `run_once()` on a
configured interval. `run_once()` is deterministic — given the same DB state it produces
the same candidates — and fully testable with mocked adapters.

**Execution sequence per `run_once()` call:**

```
1. IngestorService.ingest_once()
   → fetch Polymarket events → upsert RawMarket rows → emit audit

2. For each upserted market without a compiled contract:
   CompilerService.compile_market(market_id)
   → compile to ContractSchema → upsert CompiledContract → emit audit

3. IdentityService.resolve_all_ungrouped()
   → for each market with group_id not yet linked to CanonicalEvent:
     find_or_create CanonicalEvent → write MarketEventLink

4. For each CanonicalEvent with ≥ 2 markets:
   Stage1ConstraintDetector.detect_and_persist(markets)
   → write MUTUALLY_EXCLUSIVE MarketRelation rows for any price-sum < 0.97

5. For each CanonicalEvent with MUTUALLY_EXCLUSIVE relations:
   ProverService.prove_group(markets)
   → compute PayoffMatrix → require breaking_scenario → store OpportunityCandidate

6. For each new OpportunityCandidate:
   DivergenceService.score(markets, contracts) → RiskScore
   CourtService.review(candidate_id) → CourtDecision.WATCHLIST (stub)
   SimulatorService.simulate(candidate_id, payoff_matrix) → SimulationResult

7. Return RunSummary
```

**`RunSummary` schema** (add to `shared/schemas.py`):
```python
class RunSummary(BaseModel):
    markets_ingested: int
    contracts_compiled: int
    events_resolved: int
    relations_detected: int
    candidates_found: int
    candidates_watchlisted: int
    errors: list[str]
```

The pipeline is **not** responsible for closing positions or running autopsies — those are
triggered by external resolution events (Slice 2).

- [ ] **Step 1: Write integration test** (mocked adapter)

```python
# tests/integration/test_pipeline.py
from unittest.mock import MagicMock, patch
from parallax.pipeline.runner import PipelineRunner
from parallax.shared.schemas import RunSummary


def _build_runner_with_mocks():
    """Return a PipelineRunner with all service dependencies mocked."""
    ingestor = MagicMock()
    ingestor.ingest_once.return_value = 3  # 3 markets ingested
    compiler = MagicMock()
    compiler.compile_pending.return_value = 2  # 2 contracts compiled
    identity = MagicMock()
    identity.resolve_all_ungrouped.return_value = 1  # 1 event resolved
    detector = MagicMock()
    detector.detect_and_persist_all.return_value = 3  # 3 relations found
    prover = MagicMock()
    mock_candidate = MagicMock()
    mock_candidate.id = "cand-001"
    mock_candidate.payoff_matrix = {
        "worst_case_payoff": 0.05, "total_cost": 0.90,
        "best_case_payoff": 0.10, "friction_bps": 50,
        "opportunity_type": "MUTUALLY_EXCLUSIVE_MISPRICING",
        "legs": [], "scenarios": [], "breaking_scenario": None,
    }
    prover.prove_pending_groups.return_value = [mock_candidate]
    divergence = MagicMock()
    court = MagicMock()
    from parallax.shared.schemas import CourtDecision
    court.review.return_value = CourtDecision.WATCHLIST
    simulator = MagicMock()
    from parallax.shared.schemas import SimulationResult
    simulator.simulate.return_value = SimulationResult(
        candidate_id="cand-001", simulated_pnl=0.04,
        friction_bps=50, fill_probability=1.0,
        is_executable=True, note="stub",
    )
    return PipelineRunner(
        ingestor=ingestor, compiler=compiler, identity=identity,
        detector=detector, prover=prover, divergence=divergence,
        court=court, simulator=simulator,
    )


def test_run_once_returns_summary():
    runner = _build_runner_with_mocks()
    summary = runner.run_once()
    assert isinstance(summary, RunSummary)
    assert summary.markets_ingested == 3
    assert summary.candidates_watchlisted == 1
    assert summary.errors == []


def test_run_once_calls_all_services():
    runner = _build_runner_with_mocks()
    runner.run_once()
    runner._ingestor.ingest_once.assert_called_once()
    runner._compiler.compile_pending.assert_called_once()
    runner._identity.resolve_all_ungrouped.assert_called_once()
    runner._detector.detect_and_persist_all.assert_called_once()
    runner._prover.prove_pending_groups.assert_called_once()
    runner._court.review.assert_called_once()
    runner._simulator.simulate.assert_called_once()
```

Run: `uv run pytest tests/integration/test_pipeline.py -v`
Expected: `2 failed` (PipelineRunner does not exist)

- [ ] **Step 2: Add batch methods to intermediate services (TDD each)**

Each batch method must follow the same Red → Green → Commit pattern before proceeding to Step 3.

**`CompilerService.compile_pending()`** — add to `src/parallax/compiler/service.py`:
```python
def compile_pending(self) -> int:
    """Compile all markets that have no compiled contract. Returns count compiled."""
    markets = self._market_repo.get_uncompiled()   # add get_uncompiled() to MarketRepository
    count = 0
    for market in markets:
        try:
            self.compile_market(market.id)
            count += 1
        except Exception:
            pass  # logged inside compile_market
    return count
```
Add to `MarketRepository`:
```python
def get_uncompiled(self) -> list[RawMarket]:
    """Return markets with no corresponding CompiledContract row."""
    from sqlalchemy import select, not_, exists
    from parallax.db.models import CompiledContract
    stmt = (
        select(RawMarket)
        .where(RawMarket.is_closed.is_(False))
        .where(
            not_(exists().where(CompiledContract.raw_market_id == RawMarket.id))
        )
    )
    return list(self._session.execute(stmt).scalars())
```

**`IdentityService.resolve_all_ungrouped()`** — add to `src/parallax/identity/service.py`:
```python
def resolve_all_ungrouped(self) -> int:
    """Resolve canonical events for markets not yet linked. Returns count resolved."""
    from sqlalchemy import select, not_, exists
    from parallax.db.models import RawMarket, MarketEventLink
    stmt = (
        select(RawMarket)
        .where(RawMarket.group_id.is_not(None))
        .where(not_(exists().where(MarketEventLink.raw_market_id == RawMarket.id)))
    )
    markets = list(self._session.execute(stmt).scalars())
    for market in markets:
        self.resolve(market)
    return len(markets)
```
Note: `IdentityService.__init__` must receive `session` in addition to `event_repo` so it can query `RawMarket` directly, or this query belongs in a dedicated `MarketRepository` call. Prefer the latter: add `get_unlinked()` to `MarketRepository` and inject it into `IdentityService`.

**`Stage1ConstraintDetector.detect_and_persist_all()`** — add to `src/parallax/graph/detector.py`:
```python
def detect_and_persist_all(self) -> int:
    """Run detect_and_persist on all active groups. Returns total relation count."""
    groups = self._graph_repo.find_active_groups("polymarket")
    total = 0
    for group_id, markets in groups.items():
        relations = self.detect_and_persist(markets)
        total += len(relations)
    return total
```

**`ProverService.prove_pending_groups()`** — add to `src/parallax/prover/service.py`:
```python
def prove_pending_groups(self) -> list[OpportunityCandidate]:
    """Prove all groups with MUTUALLY_EXCLUSIVE relations not yet proven."""
    unproven = self._repo.list_unproven_groups()  # add to CandidateRepository
    results = []
    for group_id, markets in unproven.items():
        candidate = self.prove_group(group_id, markets)
        if candidate:
            results.append(candidate)
    return results
```
Add `list_unproven_groups()` to `CandidateRepository`:
```python
def list_unproven_groups(self) -> dict[str, list]:
    """Return {group_id: [RawMarket]} for groups with MUTUALLY_EXCLUSIVE relations
    that have no OpportunityCandidate yet."""
    from sqlalchemy import select
    from parallax.db.models import MarketRelation, RawMarket
    proven_market_ids = {
        mid
        for row in self._session.execute(select(OpportunityCandidate.market_ids)).scalars()
        for mid in (row or [])
    }
    stmt = (
        select(MarketRelation)
        .where(MarketRelation.relation_type == "mutually_exclusive")
    )
    relations = list(self._session.execute(stmt).scalars())
    groups: dict[str, set] = {}
    for rel in relations:
        if rel.from_market_id not in proven_market_ids:
            key = self._session.get(RawMarket, rel.from_market_id)
            if key and key.group_id:
                groups.setdefault(key.group_id, set()).add(rel.from_market_id)
                groups[key.group_id].add(rel.to_market_id)
    result = {}
    for gid, mids in groups.items():
        markets = [self._session.get(RawMarket, mid) for mid in mids]
        result[gid] = [m for m in markets if m is not None]
    return result
```

- [ ] **Step 3: Implement `PipelineRunner`**

```python
# src/parallax/pipeline/runner.py
import logging
from parallax.shared.schemas import RunSummary, PayoffMatrix, CourtDecision
from parallax.ingestor.service import IngestorService
from parallax.compiler.service import CompilerService
from parallax.identity.service import IdentityService
from parallax.graph.detector import Stage1ConstraintDetector
from parallax.prover.service import ProverService
from parallax.divergence.service import DivergenceService
from parallax.court.service import CourtService
from parallax.simulator.service import SimulatorService

logger = logging.getLogger(__name__)


class PipelineRunner:
    def __init__(
        self,
        ingestor: IngestorService,
        compiler: CompilerService,
        identity: IdentityService,
        detector: Stage1ConstraintDetector,
        prover: ProverService,
        divergence: DivergenceService,
        court: CourtService,
        simulator: SimulatorService,
    ):
        self._ingestor = ingestor
        self._compiler = compiler
        self._identity = identity
        self._detector = detector
        self._prover = prover
        self._divergence = divergence
        self._court = court
        self._simulator = simulator

    def run_once(self) -> RunSummary:
        errors: list[str] = []

        markets_ingested = self._safe(self._ingestor.ingest_once, "ingestor", errors)
        contracts_compiled = self._safe(self._compiler.compile_pending, "compiler", errors)
        events_resolved = self._safe(self._identity.resolve_all_ungrouped, "identity", errors)
        relations_detected = self._safe(self._detector.detect_and_persist_all, "detector", errors)

        candidates = self._safe(
            self._prover.prove_pending_groups, "prover", errors, default=[]
        )
        candidates_watchlisted = 0
        for candidate in candidates:
            try:
                self._divergence.score([], None)  # markets/contracts fetched in Slice 2
                decision = self._court.review(candidate.id)
                if decision == CourtDecision.WATCHLIST:
                    payoff = PayoffMatrix(**candidate.payoff_matrix)
                    self._simulator.simulate(str(candidate.id), payoff)
                    candidates_watchlisted += 1
            except Exception as exc:
                errors.append(f"post-proof error for {candidate.id}: {exc}")
                logger.exception("post-proof error", exc_info=exc)

        return RunSummary(
            markets_ingested=markets_ingested or 0,
            contracts_compiled=contracts_compiled or 0,
            events_resolved=events_resolved or 0,
            relations_detected=relations_detected or 0,
            candidates_found=len(candidates),
            candidates_watchlisted=candidates_watchlisted,
            errors=errors,
        )

    # --- private ---

    def _safe(self, fn, name: str, errors: list[str], default=None):
        try:
            return fn()
        except Exception as exc:
            errors.append(f"{name} error: {exc}")
            logger.exception("%s error", name, exc_info=exc)
            return default
```

- [ ] **Step 4: Run integration test**

```bash
uv run pytest tests/integration/test_pipeline.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: All tests pass (no regressions from batch method additions)

- [ ] **Step 6: Commit**

```bash
git add src/parallax/pipeline/ src/parallax/shared/schemas.py \
        tests/integration/test_pipeline.py
git commit -m "feat: PipelineRunner — orchestrates full proof cycle, run_once() deterministic"
```

---

*— End of Phase 3 —*


---

## Phase 4 — API Layer and War Room UI

### Task 20: FastAPI application scaffold

**Files:**
- Create: `src/parallax/api/main.py`
- Create: `src/parallax/api/deps.py`
- Create: `src/parallax/api/routes/__init__.py` (empty)

**Purpose:** FastAPI app wiring: lifespan event (creates DB tables on startup), CORS for
the War Room UI (localhost:5173 in dev), and a `/health` endpoint. `deps.py` provides
`get_session()` dependency for all routes.

**`main.py` structure:**

```python
# src/parallax/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from parallax.db.session import engine
from parallax.db.models import Base
from parallax.api.routes import candidates, markets, audit as audit_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="PARALLAX", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(markets.router,    prefix="/api/markets",    tags=["markets"])
app.include_router(audit_routes.router, prefix="/api/audit",   tags=["audit"])


@app.get("/health")
def health():
    return {"status": "ok"}
```

**`deps.py`:**

```python
# src/parallax/api/deps.py
from typing import Generator
from sqlalchemy.orm import Session
from parallax.db.session import SessionLocal


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

- [ ] **Step 1: Write failing import test**

```python
# tests/unit/test_api_scaffold.py
def test_app_imports():
    from parallax.api.main import app
    assert app.title == "PARALLAX"

def test_health_route_registered():
    from parallax.api.main import app
    routes = [r.path for r in app.routes]
    assert "/health" in routes
```

Run: `uv run pytest tests/unit/test_api_scaffold.py -v`
Expected: `2 failed`

- [ ] **Step 2: Create scaffold files** (`main.py`, `deps.py`, empty route `__init__.py`)

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_api_scaffold.py -v
```
Expected: `2 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/api/ tests/unit/test_api_scaffold.py
git commit -m "feat: FastAPI app scaffold — lifespan, CORS, health endpoint"
```

---

### Task 21: `/api/candidates` route

**Files:**
- Create: `src/parallax/api/routes/candidates.py`

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/candidates` | List candidates — filter by `status`, `opportunity_type`, `min_payoff` |
| `GET` | `/api/candidates/{id}` | Full candidate detail: payoff matrix, risk score, simulation result |

All response schemas (`CandidateSummary`, `CandidateDetail`, `MarketSummary`, `MarketDetail`, `AuditEventResponse`, `RunSummary`) are already defined in `shared/schemas.py` (Task 2). No additions needed.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_candidates_route.py
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def _make_mock_candidate():
    c = MagicMock()
    c.id = "cand-001"
    c.opportunity_type = "MUTUALLY_EXCLUSIVE_MISPRICING"
    c.market_ids = ["poly:A", "poly:B"]
    c.court_decision = "WATCHLIST"
    from datetime import datetime, timezone
    c.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    c.payoff_matrix = {
        "legs": [], "total_cost": 0.90, "scenarios": [],
        "worst_case_payoff": 0.05, "best_case_payoff": 0.10,
        "breaking_scenario": None, "opportunity_type": "MUTUALLY_EXCLUSIVE_MISPRICING",
        "friction_bps": 50,
    }
    c.risk_scores = None
    return c


def test_list_candidates_200():
    with patch("parallax.api.routes.candidates.CandidateRepository") as MockRepo:
        MockRepo.return_value.list_active.return_value = [_make_mock_candidate()]
        from parallax.api.main import app
        client = TestClient(app)
        resp = client.get("/api/candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["opportunity_type"] == "MUTUALLY_EXCLUSIVE_MISPRICING"


def test_get_candidate_404():
    with patch("parallax.api.routes.candidates.CandidateRepository") as MockRepo:
        MockRepo.return_value.get.return_value = None
        from parallax.api.main import app
        client = TestClient(app)
        resp = client.get("/api/candidates/nonexistent")
        assert resp.status_code == 404
```

Run: `uv run pytest tests/unit/test_candidates_route.py -v`
Expected: `2 failed`

- [ ] **Step 2: Implement `candidates.py` route**

```python
# src/parallax/api/routes/candidates.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from parallax.api.deps import get_session
from parallax.prover.repository import CandidateRepository
from parallax.shared.schemas import (
    CandidateSummary, CandidateDetail, PayoffMatrix, RiskScore, SimulationResult
)

router = APIRouter()


@router.get("", response_model=list[CandidateSummary])
def list_candidates(
    status: str | None = Query(None),
    opportunity_type: str | None = Query(None),
    min_payoff: float | None = Query(None),
    session: Session = Depends(get_session),
):
    repo = CandidateRepository(session)
    candidates = repo.list_active(
        status=status,
        opportunity_type=opportunity_type,
        min_payoff=min_payoff,
    )
    return [
        CandidateSummary(
            id=str(c.id),
            opportunity_type=c.opportunity_type,
            worst_case_payoff=c.payoff_matrix.get("worst_case_payoff", 0.0),
            total_cost=c.payoff_matrix.get("total_cost", 0.0),
            court_decision=c.court_decision or "PENDING",
            created_at=c.created_at,
        )
        for c in candidates
    ]


@router.get("/{candidate_id}", response_model=CandidateDetail)
def get_candidate(candidate_id: str, session: Session = Depends(get_session)):
    repo = CandidateRepository(session)
    c = repo.get_by_str_id(candidate_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return CandidateDetail(
        id=str(c.id),
        opportunity_type=c.opportunity_type,
        market_ids=c.market_ids or [],
        payoff_matrix=PayoffMatrix(**c.payoff_matrix),
        risk_score=RiskScore(**c.risk_scores) if c.risk_scores else None,
        simulation_result=None,  # not persisted in Slice 1; computed on demand in Slice 2
        court_decision=c.court_decision or "PENDING",
        created_at=c.created_at,
    )
```

Also add `list_active` and `get_by_str_id` to `CandidateRepository`:

```python
def list_active(
    self,
    status: str | None = None,
    opportunity_type: str | None = None,
    min_payoff: float | None = None,
) -> list[OpportunityCandidate]:
    from sqlalchemy import select
    stmt = select(OpportunityCandidate)
    if status:
        stmt = stmt.where(OpportunityCandidate.court_decision == status)
    if opportunity_type:
        stmt = stmt.where(OpportunityCandidate.opportunity_type == opportunity_type)
    return list(self._session.execute(stmt).scalars())

def get_by_str_id(self, candidate_id: str) -> OpportunityCandidate | None:
    import uuid
    try:
        uid = uuid.UUID(candidate_id)
    except ValueError:
        return None
    return self._session.get(OpportunityCandidate, uid)
```

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/unit/test_candidates_route.py -v
```
Expected: `2 passed`

- [ ] **Step 4: Commit**

```bash
git add src/parallax/api/routes/candidates.py src/parallax/prover/repository.py \
        src/parallax/shared/schemas.py tests/unit/test_candidates_route.py
git commit -m "feat: /api/candidates — list with filters and detail endpoint"
```

---

### Task 22: `/api/markets` and `/api/audit` routes

**Files:**
- Create: `src/parallax/api/routes/markets.py`
- Create: `src/parallax/api/routes/audit.py`

**Markets endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/markets` | List active markets (paginated: `limit`, `offset`); optional `group_id` filter |
| `GET` | `/api/markets/{market_id}` | Single market with its compiled contract if available |

All response schemas are already defined in `shared/schemas.py` (Task 2). No additions needed.

**Audit endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/audit` | Paginated audit log — `limit` (default 50, max 200), `offset`, optional `event_type` filter |

- [ ] **Step 1: Implement `markets.py`**

```python
# src/parallax/api/routes/markets.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from parallax.api.deps import get_session
from parallax.ingestor.repository import MarketRepository
from parallax.compiler.repository import ContractRepository
from parallax.shared.schemas import MarketSummary, MarketDetail, ContractSchema

router = APIRouter()


@router.get("", response_model=list[MarketSummary])
def list_markets(
    group_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    repo = MarketRepository(session)
    markets = repo.list_active(group_id=group_id, limit=limit, offset=offset)
    return [
        MarketSummary(
            id=m.id, platform=m.platform, title=m.title,
            outcome_prices=m.outcome_prices or [],
            group_id=m.group_id, deadline=m.deadline, is_closed=m.is_closed,
        )
        for m in markets
    ]


@router.get("/{market_id:path}", response_model=MarketDetail)
def get_market(market_id: str, session: Session = Depends(get_session)):
    market_repo = MarketRepository(session)
    contract_repo = ContractRepository(session)
    m = market_repo.get(market_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Market not found")
    contract_row = contract_repo.get_for_market(market_id)
    contract = ContractSchema(**contract_row.contract_json) if contract_row else None
    return MarketDetail(
        id=m.id, platform=m.platform, title=m.title,
        description=m.description, resolution_criteria=m.resolution_criteria,
        outcome_prices=m.outcome_prices or [],
        group_id=m.group_id, deadline=m.deadline, is_closed=m.is_closed,
        resolution_source=m.resolution_source, contract=contract,
    )
```

Also add `list_active(group_id, limit, offset)` to `MarketRepository`:

```python
def list_active(
    self, group_id: str | None = None, limit: int = 50, offset: int = 0
) -> list[RawMarket]:
    from sqlalchemy import select
    stmt = select(RawMarket).where(RawMarket.is_closed.is_(False))
    if group_id:
        stmt = stmt.where(RawMarket.group_id == group_id)
    stmt = stmt.limit(limit).offset(offset)
    return list(self._session.execute(stmt).scalars())
```

- [ ] **Step 2: Implement `audit.py`**

```python
# src/parallax/api/routes/audit.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from parallax.api.deps import get_session
from parallax.audit.repository import AuditRepository
from parallax.shared.schemas import AuditEventResponse

router = APIRouter()


@router.get("", response_model=list[AuditEventResponse])
def list_audit_events(
    event_type: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    repo = AuditRepository(session)
    events = repo.list(event_type=event_type, limit=limit, offset=offset)
    return [
        AuditEventResponse(
            id=str(e.id), event_type=e.event_type,
            entity_id=e.entity_id, payload=e.payload or {},
            created_at=e.created_at,
        )
        for e in events
    ]
```

Also add `list(event_type, limit, offset)` to `AuditRepository`:

```python
def list(
    self, event_type: str | None = None, limit: int = 50, offset: int = 0
) -> list[AuditEvent]:
    from sqlalchemy import select
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    stmt = stmt.limit(limit).offset(offset)
    return list(self._session.execute(stmt).scalars())
```

- [ ] **Step 3: Write smoke tests**

```python
# tests/unit/test_markets_audit_routes.py
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def test_markets_list_200():
    with patch("parallax.api.routes.markets.MarketRepository") as MockRepo:
        MockRepo.return_value.list_active.return_value = []
        from parallax.api.main import app
        client = TestClient(app)
        resp = client.get("/api/markets")
        assert resp.status_code == 200
        assert resp.json() == []


def test_audit_list_200():
    with patch("parallax.api.routes.audit.AuditRepository") as MockRepo:
        MockRepo.return_value.list.return_value = []
        from parallax.api.main import app
        client = TestClient(app)
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        assert resp.json() == []
```

Run: `uv run pytest tests/unit/test_markets_audit_routes.py -v`
Expected: `2 passed`

- [ ] **Step 4: Run full test suite**

```bash
uv run pytest tests/ -v
```
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/parallax/api/routes/ src/parallax/ingestor/repository.py \
        src/parallax/audit/repository.py src/parallax/shared/schemas.py \
        tests/unit/test_markets_audit_routes.py
git commit -m "feat: /api/markets and /api/audit routes — paginated list endpoints"
```

---

### Task 23: War Room UI scaffold (Vite + React + TypeScript + TailwindCSS)

**Files:**
- Create: `warroom/package.json`
- Create: `warroom/vite.config.ts`
- Create: `warroom/tsconfig.json`
- Create: `warroom/index.html`
- Create: `warroom/src/main.tsx`
- Create: `warroom/src/App.tsx`
- Create: `warroom/src/api/client.ts`
- Create: `warroom/tailwind.config.ts`
- Create: `warroom/postcss.config.js`

**Purpose:** Minimal structural shell. The War Room is a read-only decision surface —
not a dashboard. It does not show charts or sparklines. It shows proof artifacts:
payoff matrices, breaking scenarios, risk scores, audit trails. The UI is intentionally
austere; information density over decoration.

**Design constraints:**
- Dark background (`bg-zinc-950`), monospace font for numeric evidence
- No auto-refresh polling in Slice 1 — manual refresh button only
- Three views: ProofFeed (candidate list), CandidateDetail (full proof), AuditLog
- Navigation: top-level tab bar (`/feed`, `/audit`) — CandidateDetail opens in same pane

**`package.json` key dependencies:**

```json
{
  "name": "warroom",
  "private": true,
  "version": "0.1.0",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0"
  }
}
```

**`vite.config.ts`:**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

**`src/api/client.ts`** — typed fetch wrapper:

```typescript
const BASE = '/api'

export async function fetchCandidates(params?: {
  status?: string
  opportunity_type?: string
  min_payoff?: number
}) {
  const query = new URLSearchParams()
  if (params?.status)           query.set('status', params.status)
  if (params?.opportunity_type) query.set('opportunity_type', params.opportunity_type)
  if (params?.min_payoff != null) query.set('min_payoff', String(params.min_payoff))
  const resp = await fetch(`${BASE}/candidates?${query}`)
  if (!resp.ok) throw new Error(`candidates ${resp.status}`)
  return resp.json()
}

export async function fetchCandidate(id: string) {
  const resp = await fetch(`${BASE}/candidates/${id}`)
  if (!resp.ok) throw new Error(`candidate ${resp.status}`)
  return resp.json()
}

export async function fetchAuditLog(params?: { limit?: number; offset?: number; event_type?: string }) {
  const query = new URLSearchParams()
  if (params?.limit != null)  query.set('limit', String(params.limit))
  if (params?.offset != null) query.set('offset', String(params.offset))
  if (params?.event_type)     query.set('event_type', params.event_type)
  const resp = await fetch(`${BASE}/audit?${query}`)
  if (!resp.ok) throw new Error(`audit ${resp.status}`)
  return resp.json()
}
```

- [ ] **Step 1: Create all scaffold files** (package.json, vite.config.ts, tsconfig.json, index.html, main.tsx, App.tsx, api/client.ts, tailwind.config.ts, postcss.config.js)

- [ ] **Step 2: Install dependencies**

```bash
cd warroom && npm install
```

- [ ] **Step 3: Typecheck passes**

```bash
cd warroom && npm run typecheck
```
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add warroom/
git commit -m "feat: War Room UI scaffold — Vite + React + TypeScript + Tailwind"
```

---

### Task 24: ProofFeed component

**Files:**
- Create: `warroom/src/components/ProofFeed.tsx`

**Purpose:** Shows the live list of opportunity candidates. Each row is a proof summary:
opportunity type badge, worst-case payoff, total cost, court decision badge, timestamp.
Clicking a row navigates to `CandidateDetail`. Manual refresh button top-right.

**Component spec:**

```typescript
// Props
interface ProofFeedProps {
  onSelect: (candidateId: string) => void
}

// Each row shows:
// [OPPORTUNITY_TYPE]  worst_case_payoff  /  total_cost  [COURT_DECISION]  timestamp
// e.g.:
// [MUTUALLY_EXCLUSIVE_MISPRICING]  +0.0500  /  0.9000  [WATCHLIST]  2026-05-01 14:23
```

**Styling rules:**
- `WATCHLIST` badge: amber — `bg-amber-900 text-amber-200`
- `APPROVED` badge: green — `bg-green-900 text-green-200`
- `REJECTED` badge: red — `bg-red-900 text-red-200`
- Positive payoff: `text-green-400 font-mono`
- Negative payoff: `text-red-400 font-mono`
- Row hover: `hover:bg-zinc-800 cursor-pointer`

```typescript
// warroom/src/components/ProofFeed.tsx
import { useEffect, useState } from 'react'
import { fetchCandidates } from '../api/client'

interface Candidate {
  id: string
  opportunity_type: string
  worst_case_payoff: number
  total_cost: number
  court_decision: string
  created_at: string
}

const DECISION_STYLE: Record<string, string> = {
  WATCHLIST: 'bg-amber-900 text-amber-200',
  APPROVED:  'bg-green-900 text-green-200',
  REJECTED:  'bg-red-900 text-red-200',
  PENDING:   'bg-zinc-700 text-zinc-300',
}

export function ProofFeed({ onSelect }: { onSelect: (id: string) => void }) {
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    fetchCandidates()
      .then(setCandidates)
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between items-center px-4 py-2 border-b border-zinc-800">
        <span className="text-zinc-400 text-sm font-mono uppercase tracking-widest">
          proof feed
        </span>
        <button
          onClick={load}
          className="text-xs text-zinc-500 hover:text-zinc-200 font-mono"
        >
          {loading ? 'loading…' : '↺ refresh'}
        </button>
      </div>

      {candidates.length === 0 && !loading && (
        <div className="text-zinc-600 font-mono text-sm px-4 py-8 text-center">
          no candidates yet
        </div>
      )}

      {candidates.map((c) => (
        <div
          key={c.id}
          onClick={() => onSelect(c.id)}
          className="flex items-center gap-4 px-4 py-3 hover:bg-zinc-800 cursor-pointer border-b border-zinc-900"
        >
          <span className="text-xs font-mono text-zinc-500 truncate w-64">
            {c.opportunity_type}
          </span>
          <span className={`font-mono text-sm tabular-nums w-20 ${c.worst_case_payoff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {c.worst_case_payoff >= 0 ? '+' : ''}{c.worst_case_payoff.toFixed(4)}
          </span>
          <span className="font-mono text-sm text-zinc-500 tabular-nums w-20">
            / {c.total_cost.toFixed(4)}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded font-mono ${DECISION_STYLE[c.court_decision] ?? DECISION_STYLE.PENDING}`}>
            {c.court_decision}
          </span>
          <span className="text-xs text-zinc-600 font-mono ml-auto">
            {new Date(c.created_at).toISOString().slice(0, 16).replace('T', ' ')}
          </span>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 1: Create `ProofFeed.tsx`**
- [ ] **Step 2: Run typecheck**

```bash
cd warroom && npm run typecheck
```
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add warroom/src/components/ProofFeed.tsx
git commit -m "feat: ProofFeed component — candidate list with payoff and decision badges"
```

---

### Task 25: CandidateDetail and AuditLog components

**Files:**
- Create: `warroom/src/components/CandidateDetail.tsx`
- Create: `warroom/src/components/AuditLog.tsx`
- Update: `warroom/src/App.tsx`

**`CandidateDetail` spec:**

Shows the full proof artifact for one candidate. Structured into labeled sections:
- **Header**: opportunity type, court decision badge, created at
- **Payoff Matrix**: table of legs (market_id, side, price, quantity, cost), summary row (total cost, worst-case payoff, best-case payoff)
- **Breaking Scenario**: `breaking_scenario.description` in a highlighted box — if null show "none recorded (proof incomplete)"
- **Risk Score**: three bars or numeric grid (oracle_risk, deadline_risk, semantic_risk, composite)
- **Simulation**: simulated_pnl, friction_bps, fill_probability, is_executable badge, note

```typescript
// warroom/src/components/CandidateDetail.tsx
import { useEffect, useState } from 'react'
import { fetchCandidate } from '../api/client'

interface Leg { market_id: string; side: string; price: number; quantity: number; cost: number }
interface Scenario { description: string; payoff: number }
interface PayoffMatrix {
  legs: Leg[]; total_cost: number; worst_case_payoff: number; best_case_payoff: number
  breaking_scenario: Scenario | null; opportunity_type: string; friction_bps: number
}
interface RiskScore { oracle_risk: number; deadline_risk: number; semantic_risk: number; composite: number }
interface SimResult { simulated_pnl: number; friction_bps: number; fill_probability: number; is_executable: boolean; note: string }
interface CandidateDetailData {
  id: string; opportunity_type: string; market_ids: string[]; court_decision: string
  payoff_matrix: PayoffMatrix; risk_score: RiskScore | null
  simulation_result: SimResult | null; created_at: string
}

function RiskGrid({ r }: { r: RiskScore }) {
  const cell = (label: string, val: number) => (
    <div key={label} className="flex flex-col items-center p-3 bg-zinc-900 rounded">
      <span className="text-zinc-500 text-xs font-mono mb-1">{label}</span>
      <span className={`font-mono text-lg ${val >= 0.5 ? 'text-amber-400' : 'text-zinc-300'}`}>
        {val.toFixed(2)}
      </span>
    </div>
  )
  return (
    <div className="grid grid-cols-4 gap-2">
      {cell('oracle', r.oracle_risk)}
      {cell('deadline', r.deadline_risk)}
      {cell('semantic', r.semantic_risk)}
      {cell('composite', r.composite)}
    </div>
  )
}

export function CandidateDetail({ candidateId, onBack }: { candidateId: string; onBack: () => void }) {
  const [data, setData] = useState<CandidateDetailData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchCandidate(candidateId)
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [candidateId])

  if (error) return <div className="text-red-400 font-mono p-4">{error}</div>
  if (!data) return <div className="text-zinc-600 font-mono p-4">loading…</div>

  const pm = data.payoff_matrix

  return (
    <div className="flex flex-col gap-6 p-4 max-w-3xl">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-zinc-500 hover:text-zinc-200 font-mono text-sm">← back</button>
        <span className="font-mono text-xs text-zinc-500">{data.opportunity_type}</span>
        <span className={`text-xs px-2 py-0.5 rounded font-mono ml-auto ${
          data.court_decision === 'WATCHLIST' ? 'bg-amber-900 text-amber-200' :
          data.court_decision === 'APPROVED'  ? 'bg-green-900 text-green-200' :
          'bg-red-900 text-red-200'
        }`}>{data.court_decision}</span>
      </div>

      <section>
        <h2 className="text-zinc-400 font-mono text-xs uppercase tracking-widest mb-2">payoff matrix</h2>
        <table className="w-full font-mono text-sm">
          <thead>
            <tr className="text-zinc-600 text-xs">
              <th className="text-left py-1 pr-4">market</th>
              <th className="text-left py-1 pr-4">side</th>
              <th className="text-right py-1 pr-4">price</th>
              <th className="text-right py-1 pr-4">qty</th>
              <th className="text-right py-1">cost</th>
            </tr>
          </thead>
          <tbody>
            {pm.legs.map((leg, i) => (
              <tr key={i} className="border-t border-zinc-900">
                <td className="py-1 pr-4 text-zinc-400 truncate max-w-xs">{leg.market_id}</td>
                <td className="py-1 pr-4 text-zinc-300">{leg.side}</td>
                <td className="py-1 pr-4 text-right tabular-nums text-zinc-300">{leg.price.toFixed(4)}</td>
                <td className="py-1 pr-4 text-right tabular-nums text-zinc-300">{leg.quantity.toFixed(2)}</td>
                <td className="py-1 text-right tabular-nums text-zinc-300">{leg.cost.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-zinc-700 text-zinc-200">
              <td colSpan={4} className="py-2 font-semibold">total cost</td>
              <td className="py-2 text-right tabular-nums">{pm.total_cost.toFixed(4)}</td>
            </tr>
            <tr className="text-zinc-300">
              <td colSpan={4} className="pb-1">worst-case payoff</td>
              <td className={`pb-1 text-right tabular-nums ${pm.worst_case_payoff >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {pm.worst_case_payoff >= 0 ? '+' : ''}{pm.worst_case_payoff.toFixed(4)}
              </td>
            </tr>
          </tfoot>
        </table>
      </section>

      <section>
        <h2 className="text-zinc-400 font-mono text-xs uppercase tracking-widest mb-2">breaking scenario</h2>
        {pm.breaking_scenario ? (
          <div className="bg-zinc-900 border border-zinc-700 rounded p-3 font-mono text-sm text-zinc-300">
            {pm.breaking_scenario.description}
            <span className="ml-4 text-red-400 tabular-nums">
              {pm.breaking_scenario.payoff.toFixed(4)}
            </span>
          </div>
        ) : (
          <div className="font-mono text-sm text-red-500 bg-red-950 border border-red-900 rounded p-3">
            none recorded — proof incomplete
          </div>
        )}
      </section>

      {data.risk_score && (
        <section>
          <h2 className="text-zinc-400 font-mono text-xs uppercase tracking-widest mb-2">risk score</h2>
          <RiskGrid r={data.risk_score} />
        </section>
      )}

      {data.simulation_result && (
        <section>
          <h2 className="text-zinc-400 font-mono text-xs uppercase tracking-widest mb-2">simulation</h2>
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-zinc-900 rounded p-3">
              <div className="text-zinc-500 text-xs font-mono mb-1">simulated pnl</div>
              <div className={`font-mono text-lg tabular-nums ${data.simulation_result.simulated_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {data.simulation_result.simulated_pnl >= 0 ? '+' : ''}{data.simulation_result.simulated_pnl.toFixed(4)}
              </div>
            </div>
            <div className="bg-zinc-900 rounded p-3">
              <div className="text-zinc-500 text-xs font-mono mb-1">friction</div>
              <div className="font-mono text-lg text-zinc-300">{data.simulation_result.friction_bps} bps</div>
            </div>
            <div className="bg-zinc-900 rounded p-3">
              <div className="text-zinc-500 text-xs font-mono mb-1">executable</div>
              <div className={`font-mono text-lg ${data.simulation_result.is_executable ? 'text-green-400' : 'text-red-500'}`}>
                {data.simulation_result.is_executable ? 'YES' : 'NO'}
              </div>
            </div>
          </div>
          <div className="text-zinc-600 font-mono text-xs mt-2">{data.simulation_result.note}</div>
        </section>
      )}
    </div>
  )
}
```

**`AuditLog` spec:**

Paginated, newest-first audit event log. Each row: event_type, entity_id (truncated), timestamp. Click row to expand payload JSON.

```typescript
// warroom/src/components/AuditLog.tsx
import { useEffect, useState } from 'react'
import { fetchAuditLog } from '../api/client'

interface AuditEvent {
  id: string; event_type: string; entity_id: string | null
  payload: Record<string, unknown>; created_at: string
}

export function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const LIMIT = 50

  const load = (off = offset) => {
    fetchAuditLog({ limit: LIMIT, offset: off })
      .then((rows: AuditEvent[]) => {
        if (off === 0) setEvents(rows)
        else setEvents(prev => [...prev, ...rows])
      })
  }

  useEffect(() => { load(0) }, [])

  return (
    <div className="flex flex-col gap-1">
      <div className="flex justify-between items-center px-4 py-2 border-b border-zinc-800">
        <span className="text-zinc-400 text-sm font-mono uppercase tracking-widest">audit log</span>
        <button onClick={() => { setOffset(0); load(0) }}
          className="text-xs text-zinc-500 hover:text-zinc-200 font-mono">
          ↺ refresh
        </button>
      </div>

      {events.map(e => (
        <div key={e.id}
          className="border-b border-zinc-900"
          onClick={() => setExpanded(expanded === e.id ? null : e.id)}
        >
          <div className="flex items-center gap-4 px-4 py-2 hover:bg-zinc-800 cursor-pointer">
            <span className="font-mono text-xs text-amber-400 w-48 truncate">{e.event_type}</span>
            <span className="font-mono text-xs text-zinc-500 w-48 truncate">{e.entity_id ?? '—'}</span>
            <span className="font-mono text-xs text-zinc-600 ml-auto">
              {new Date(e.created_at).toISOString().slice(0, 19).replace('T', ' ')}
            </span>
          </div>
          {expanded === e.id && (
            <pre className="px-4 py-2 text-xs font-mono text-zinc-400 bg-zinc-900 overflow-x-auto">
              {JSON.stringify(e.payload, null, 2)}
            </pre>
          )}
        </div>
      ))}

      <button
        onClick={() => { const next = offset + LIMIT; setOffset(next); load(next) }}
        className="text-zinc-500 hover:text-zinc-200 font-mono text-xs py-3 text-center"
      >
        load more
      </button>
    </div>
  )
}
```

**`App.tsx` — wire all three components:**

```typescript
// warroom/src/App.tsx
import { useState } from 'react'
import { ProofFeed } from './components/ProofFeed'
import { CandidateDetail } from './components/CandidateDetail'
import { AuditLog } from './components/AuditLog'

type View = 'feed' | 'audit'

export function App() {
  const [view, setView] = useState<View>('feed')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="border-b border-zinc-800 px-6 py-3 flex items-center gap-8">
        <span className="font-mono text-sm font-semibold tracking-widest text-zinc-200">
          PARALLAX
        </span>
        <nav className="flex gap-4">
          {(['feed', 'audit'] as View[]).map(v => (
            <button key={v}
              onClick={() => { setView(v); setSelectedId(null) }}
              className={`font-mono text-xs uppercase tracking-widest py-1 px-2 rounded ${
                view === v ? 'text-zinc-100 bg-zinc-800' : 'text-zinc-500 hover:text-zinc-300'
              }`}
            >{v}</button>
          ))}
        </nav>
      </header>

      <main className="max-w-5xl mx-auto py-4">
        {view === 'feed' && !selectedId && (
          <ProofFeed onSelect={setSelectedId} />
        )}
        {view === 'feed' && selectedId && (
          <CandidateDetail candidateId={selectedId} onBack={() => setSelectedId(null)} />
        )}
        {view === 'audit' && <AuditLog />}
      </main>
    </div>
  )
}
```

- [ ] **Step 1: Create `CandidateDetail.tsx`, `AuditLog.tsx`, update `App.tsx`**

- [ ] **Step 2: Typecheck**

```bash
cd warroom && npm run typecheck
```
Expected: no errors

- [ ] **Step 3: Start dev server and smoke-test against running API**

```bash
# Terminal 1
make dev   # starts PostgreSQL + API on port 8000

# Terminal 2
cd warroom && npm run dev   # starts on port 5173
```

Open `http://localhost:5173`. Verify:
- [ ] Header renders with PARALLAX title
- [ ] "feed" tab shows "no candidates yet" when DB is empty
- [ ] "audit" tab shows empty audit log
- [ ] No console errors
- [ ] Manual refresh button responds

- [ ] **Step 4: Commit**

```bash
git add warroom/src/
git commit -m "feat: War Room UI — ProofFeed, CandidateDetail, AuditLog components"
```

---

## Plan Self-Review

### Coverage check

| Phase | Tasks | TDD steps | Interfaces designed to final spec |
|-------|-------|-----------|----------------------------------|
| Phase 0 (Foundation) | 5 | Yes (all) | Config, shared schemas, all 9 DB models, Alembic |
| Phase 1 (Data Pipeline) | 4 | Yes (all) | PlatformAdapter, CompilerProvider, MarketRepository, ContractRepository |
| Phase 2 (Semantic Layer) | 4 | Yes (all) | GraphRepository, Stage1ConstraintDetector, ProverService |
| Phase 3 (Risk + Stubs) | 6 | Yes (all) | DivergenceService, TrackerService, CourtService, SimulatorService, AutopsyService, PipelineRunner |
| Phase 4 (API + UI) | 6 | Partial (API unit tests; UI typecheck only — no E2E) | FastAPI routes, War Room components |

**Total: 25 tasks.** Every task follows: failing test → implement → pass → commit.

### ADR compliance check

| ADR | Requirement | Implementation |
|-----|-------------|----------------|
| 0001 | Intra-platform logical consistency first | Stage1ConstraintDetector uses `group_id` grouping; no cross-platform logic in Slice 1 |
| 0002 | Claude Sonnet 4.6, prompt caching, CompilerProvider ABC | AnthropicCompilerProvider with `cache_control` headers; ABC in `provider.py` |
| 0003 | Polymarket-only, PlatformAdapter interface | PolymarketAdapter implements PlatformAdapter ABC; no other adapters in Slice 1 |
| 0004 | PostgreSQL adjacency table, GraphRepository ABC | PostgresGraphRepository implements GraphRepository ABC |
| 0005 | Stage 1 constraint rules first, LLM second | Stage1ConstraintDetector filters candidates; AnthropicCompilerProvider handles Stage 2 |

### Invariant check

Every invariant from the original design is enforced:

| Invariant | Enforcement point |
|-----------|-------------------|
| `breaking_scenario` MUST exist for any approved candidate | `ProverService.prove_group()` returns `None` if `net_payoff ≤ 0`; breaking scenario is always set |
| Audit log is append-only | `AuditRepository` has no `delete` or `update` methods |
| `counterexamples` mandatory in LLM contract | Anthropic tool schema has `"minItems": 1` |
| No cross-platform logic in Slice 1 | `IdentityService` uses `"{platform}:{group_id}"` — same platform always |
| War Room is read-only | All API routes are `GET` only; no mutation endpoints |
| Friction applied before emitting positive payoff | `ProverService` applies `friction_bps` in `net_payoff` calculation |
| All timestamps are timezone-aware | `datetime.now(timezone.utc)` throughout; `_now()` helper in DB models |
| Single source of truth for shared schemas | All Pydantic types defined once in `shared/schemas.py` — no duplicates across phases |

### Known gaps (Slice 2)

- Trade Court adversarial review (Prosecutor/Defense/Judge) → `CourtService` is stubbed
- Real execution simulator (order book, slippage) → `SimulatorService` is stubbed
- Calibration loop (Autopsy → Stage 1/2 tuning) → `AutopsyService` records but does not tune
- Cross-platform semantic equivalence → `PlatformAdapter` interface is final; Kalshi adapter not yet implemented
- WebSocket real-time feed → polling only in Slice 1; War Room has manual refresh
- Stage 2 LLM relation detection → `Stage1ConstraintDetector` only in Slice 1; `Stage2LLMDetector` not yet built
- Payoff Prover for `subset` / `equivalent` relation types → only `mutually_exclusive` in Slice 1

### Risks accepted in this plan

| Risk | Mitigation |
|------|------------|
| Polymarket API schema may change | `RawMarketData` normalization layer isolates schema; `raw_payload` preserved |
| Anthropic tool_use schema may not enforce `minItems` at runtime | `CompilerService` validates output before storing |
| PostgreSQL adjacency table performance for multi-hop traversal | Composite indexes on `(from_market_id, relation_type)` and `(to_market_id, relation_type)`; migration to Neo4j triggered at 10k nodes per ADR-0004 |
| Stage 1 thresholds (0.97 price sum) may be too tight or loose | `AutopsyService` records `identity_error` flag; ADR-0005 specifies loosening if >15% of false negatives trace to Stage 1 filtering |

---

## Execution Instructions

This plan is designed for `superpowers:subagent-driven-development` or `superpowers:executing-plans`.

**Before starting:**
1. Confirm Docker is running: `docker info`
2. Confirm `uv` is installed: `uv --version`
3. Confirm `node` ≥ 20: `node --version`
4. Run: `git status` — must be on `main`, clean working tree

**Starting point:** Task 1, Step 1.

**Never skip the failing-test step.** Every task starts with a red test. Red → Green → Commit.

**Never implement multiple tasks in one commit.** Each task ends with a named commit.

**If a test unexpectedly passes before implementation:** investigate — the module may already exist from a prior session. Do not proceed without understanding why.

**Gate between phases:** Run `uv run pytest tests/ -v` before starting Phase 1, Phase 2, Phase 3, Phase 4. All prior tests must pass before proceeding.

---

*— End of Plan —*
