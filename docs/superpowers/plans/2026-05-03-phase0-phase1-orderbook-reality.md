# Orderbook Reality Layer — Fase 0 + Fase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PARALLAX's heuristic execution simulator with a snapshot-based orderbook reality layer for Polymarket and Kalshi, anchoring `displayed_edge` and `executable_edge` to real market depth.

**Architecture:** A new `src/parallax/execution/` package provides read-only CLOB/quote adapters, snapshot persistence, and depth-aware fill estimation. `SimulatorService` gains a `simulate_snapshot()` path that uses live book depth; `CourtService` gains three new gates activated when snapshot data is present: stale-quote, depth-unsupported, and partial-fill-inversion. Existing heuristic path is unchanged and remains the fallback for degraded or unconfigured runs.

**Tech Stack:** Python 3.13, httpx (already present), SQLAlchemy 2.0, Pydantic v2, Polymarket CLOB API (`https://clob.polymarket.com`), Kalshi Trade API v2 (`https://api.elections.kalshi.com/trade-api/v2`), pytest + anyio.

---

## Fase 0 — Verification Runbook

This is not a coding task. It is a pre-build gate. Complete Fase 0 before writing any Fase 1 code.

### 0.1 Required environment

```bash
# .env minimum (copy .env.example if present)
DATABASE_URL=postgresql://parallax:dev_password@localhost:5432/parallax
ANTHROPIC_API_KEY=sk-ant-...   # optional; pipeline degrades gracefully without it
```

### 0.2 Start services and migrate

```bash
make up          # starts postgres + any compose services
make migrate     # applies all 9 migrations; expected: "Running upgrade ... -> 0009"
```

### 0.3 Run the pipeline once

```bash
make pipeline
# or directly:
uv run python -c "
import asyncio
from parallax.pipeline.runner import PipelineRunner
from parallax.db.session import session_scope
runner = PipelineRunner(session_scope)
result = asyncio.run(runner.run())
print(result)
"
```

### 0.4 Evidence checkpoints

After the run, query the DB:

```bash
uv run python -c "
from parallax.db.session import session_scope
from parallax.db.models import (
    RawMarket, CanonicalEvent, OpportunityCandidate, PaperPosition,
    RunProofRecord, AutopsyRecord
)
with session_scope() as s:
    print('markets:', s.query(RawMarket).count())
    print('events:', s.query(CanonicalEvent).count())
    print('candidates:', s.query(OpportunityCandidate).count())
    print('positions:', s.query(PaperPosition).count())
    rp = s.query(RunProofRecord).order_by(RunProofRecord.started_at.desc()).first()
    if rp:
        print('last run:', rp.run_status, 'markets_ingested:', rp.markets_ingested,
              'candidates:', rp.candidates_found, 'fatal_errors:', rp.fatal_errors)
"
```

### 0.5 API endpoints to check

```bash
curl http://localhost:8000/api/v1/markets | python3 -m json.tool | head -40
curl http://localhost:8000/api/v1/candidates | python3 -m json.tool
curl http://localhost:8000/api/v1/ops/runtime | python3 -m json.tool
```

### 0.6 Manual paper position cycle (if a candidate exists)

```bash
# Get a candidate id from the candidates list, then:
CAND_ID=<uuid-from-above>

# Open position
curl -X POST http://localhost:8000/api/v1/candidates/$CAND_ID/positions

# Settle (manual close)
POS_ID=<uuid-from-response>
curl -X POST "http://localhost:8000/api/v1/positions/$POS_ID/settle" \
  -H "Content-Type: application/json" \
  -d '{"outcome": "resolved_yes", "actual_pnl": 0.02}'

# Check autopsy
curl http://localhost:8000/api/v1/candidates/$CAND_ID | python3 -m json.tool
```

### 0.7 Success criteria

| Check | Pass | Fail |
|-------|------|------|
| `make up` | services healthy | postgres error → check compose |
| `make migrate` | all 9 applied | SQL error → check DATABASE_URL |
| Pipeline run | `run_status = completed` | `fatal_errors` non-empty → fix before Fase 1 |
| Markets ingested | > 0 | 0 → adapter network issue; check httpx timeout |
| Events resolved | > 0 | 0 with markets > 0 → identity service broken |
| Fatal errors | `[]` | any entry → read error, fix root cause |
| Candidates | ≥ 0 | zero is **acceptable** if markets are thin |
| API responds | HTTP 200 | 500 → check api logs |

### 0.8 How to distinguish "zero candidates" from broken pipeline

Zero candidates is valid when:
- `RunProofRecord.markets_ingested > 0` (ingestion worked)
- `RunProofRecord.events_resolved > 0` (identity worked)
- `RunProofRecord.relations_detected == 0` (no relation found — thin market, correct)

Broken pipeline is:
- `RunProofRecord.fatal_errors != []`
- `RunProofRecord.markets_ingested == 0` with no network error
- Exception traceback in logs

### 0.9 Evidence to save

After Fase 0 passes, commit the following to `docs/STATUS.md`:
- Date of successful end-to-end run
- Market counts (polymarket/kalshi)
- Whether any candidate was generated
- Whether autopsy cycle completed

Do not proceed to Fase 1 if any fatal error exists.

---

## Fase 1 — Orderbook Reality Layer

### File map

**New files:**
- `src/parallax/execution/__init__.py`
- `src/parallax/execution/schemas.py`
- `src/parallax/execution/token_registry.py`
- `src/parallax/execution/snapshot_store.py`
- `src/parallax/execution/polymarket_clob.py`
- `src/parallax/execution/kalshi_quotes.py`
- `src/parallax/execution/depth_estimator.py`
- `src/parallax/execution/fill_simulator.py`
- `src/parallax/execution/fetcher.py`
- `alembic/versions/0010_venue_tokens.py`
- `alembic/versions/0011_orderbook_snapshots.py`
- `tests/unit/test_execution_schemas.py`
- `tests/unit/test_execution_token_registry.py`
- `tests/unit/test_polymarket_clob_adapter.py`
- `tests/unit/test_kalshi_quote_adapter.py`
- `tests/unit/test_depth_estimator.py`
- `tests/unit/test_fill_simulator.py`
- `tests/unit/test_orderbook_fetcher.py`
- `tests/unit/test_simulator_snapshot_mode.py`
- `tests/unit/test_court_orderbook_gates.py`

**Modified files:**
- `src/parallax/shared/schemas.py` — extend `SimulationResult`
- `src/parallax/config.py` — add orderbook settings
- `src/parallax/db/models.py` — add `VenueToken`, `OrderbookSnapshotRecord`
- `src/parallax/simulator/service.py` — add `simulate_snapshot()` path
- `src/parallax/court/service.py` — add snapshot-aware gates
- `src/parallax/pipeline/runner.py` — wire `OrderbookFetcher`
- `docs/STATUS.md` — update heuristic status

---

### Task 1: Execution schemas

**Files:**
- Create: `src/parallax/execution/__init__.py`
- Create: `src/parallax/execution/schemas.py`
- Create: `tests/unit/test_execution_schemas.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_execution_schemas.py
from datetime import datetime, timezone
from parallax.execution.schemas import (
    ExecutionMode,
    OrderbookLevel,
    OrderbookSide,
    OrderbookSnapshot,
    DepthAnalysis,
)

def test_orderbook_side_total_depth():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.45, size=100.0),
        OrderbookLevel(price=0.44, size=50.0),
    ])
    assert side.total_depth == 150.0

def test_orderbook_side_depth_at_or_better_bid():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.45, size=100.0),
        OrderbookLevel(price=0.44, size=50.0),
        OrderbookLevel(price=0.42, size=80.0),
    ])
    # bids at 0.44 or better (>= 0.44)
    assert side.depth_at_or_better(0.44, "bid") == 150.0

def test_orderbook_side_vwap_exact_fill():
    side = OrderbookSide(levels=[
        OrderbookLevel(price=0.46, size=50.0),
        OrderbookLevel(price=0.47, size=100.0),
    ])
    # asks sorted ascending: fill 60 contracts
    vwap = side.vwap(60.0, side="ask")
    assert vwap is not None
    # 50 at 0.46, 10 at 0.47 → (50*0.46 + 10*0.47) / 60
    expected = (50 * 0.46 + 10 * 0.47) / 60
    assert abs(vwap - expected) < 1e-9

def test_orderbook_side_vwap_insufficient_depth_returns_none():
    side = OrderbookSide(levels=[OrderbookLevel(price=0.46, size=10.0)])
    assert side.vwap(100.0, side="ask") is None

def test_orderbook_snapshot_staleness():
    old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc)
    snap = OrderbookSnapshot(
        id="test-id",
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=old_ts,
        bids=OrderbookSide(),
        asks=OrderbookSide(),
    )
    assert snap.is_stale is True
    assert snap.staleness_seconds > 0

def test_orderbook_snapshot_fresh():
    from datetime import timedelta
    snap = OrderbookSnapshot(
        id="test-id",
        platform="kalshi",
        market_id="KXSOME-24NOV-B0.5",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(),
        asks=OrderbookSide(),
    )
    assert snap.is_stale is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_execution_schemas.py -v 2>&1 | head -20
# Expected: ModuleNotFoundError or ImportError
```

- [ ] **Step 3: Create `src/parallax/execution/__init__.py`**

```python
```
(empty file)

- [ ] **Step 4: Create `src/parallax/execution/schemas.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

ExecutionMode = Literal["heuristic", "snapshot_based", "replay_based", "degraded"]


class OrderbookLevel(BaseModel):
    price: float  # 0.0–1.0 (probability / dollar price per contract)
    size: float   # number of contracts


class OrderbookSide(BaseModel):
    levels: list[OrderbookLevel] = Field(default_factory=list)

    @property
    def total_depth(self) -> float:
        return sum(level.size for level in self.levels)

    def depth_at_or_better(self, price: float, side: Literal["bid", "ask"]) -> float:
        if side == "bid":
            return sum(l.size for l in self.levels if l.price >= price)
        return sum(l.size for l in self.levels if l.price <= price)

    def vwap(self, size: float, *, side: Literal["bid", "ask"] = "ask") -> float | None:
        """VWAP to fill `size` contracts from this side of the book."""
        if not self.levels or size <= 0:
            return None
        reverse = side == "bid"
        sorted_levels = sorted(self.levels, key=lambda l: l.price, reverse=reverse)
        filled = 0.0
        cost = 0.0
        for level in sorted_levels:
            take = min(level.size, size - filled)
            cost += take * level.price
            filled += take
            if filled >= size:
                break
        if filled < size - 1e-9:
            return None
        return cost / filled


class OrderbookSnapshot(BaseModel):
    id: str
    platform: Literal["polymarket", "kalshi"]
    market_id: str
    token_id: str | None = None  # Polymarket CLOB token id; None for Kalshi
    outcome: str                  # "YES" or "NO"
    captured_at: datetime
    bids: OrderbookSide = Field(default_factory=OrderbookSide)
    asks: OrderbookSide = Field(default_factory=OrderbookSide)
    mid_price: float | None = None
    spread_bps: float | None = None

    @property
    def staleness_seconds(self) -> float:
        ts = self.captured_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())

    @property
    def is_stale(self) -> bool:
        return self.staleness_seconds > 60.0


class DepthAnalysis(BaseModel):
    market_id: str
    outcome: str
    required_size: float
    available_depth: float
    is_supported: bool
    vwap_price: float | None = None
    price_impact_bps: float | None = None
    snapshot_id: str | None = None
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_execution_schemas.py -v
# Expected: all PASS
```

- [ ] **Step 6: Commit**

```bash
git add src/parallax/execution/ tests/unit/test_execution_schemas.py
git commit -m "feat(execution): add execution schemas — OrderbookLevel, OrderbookSide, OrderbookSnapshot, DepthAnalysis"
```

---

### Task 2: Extend SimulationResult and add ExecutionMode

**Files:**
- Modify: `src/parallax/shared/schemas.py`

- [ ] **Step 1: Write a test verifying the new fields exist with defaults**

Add to `tests/unit/test_shared_schemas.py`:

```python
def test_simulation_result_new_fields_have_defaults():
    from parallax.shared.schemas import SimulationResult
    result = SimulationResult(
        candidate_id="test",
        simulated_pnl=0.01,
        friction_bps=50,
        fill_probability=0.8,
        is_executable=True,
        note="test",
    )
    assert result.execution_model == "heuristic"
    assert result.quote_staleness_seconds is None
    assert result.snapshot_ids == []
    assert result.depth_support is None
    assert result.partial_fill_risk == 0.0

def test_simulation_result_snapshot_mode():
    from parallax.shared.schemas import SimulationResult
    result = SimulationResult(
        candidate_id="test",
        simulated_pnl=0.01,
        friction_bps=50,
        fill_probability=0.85,
        is_executable=True,
        note="snapshot-based",
        execution_model="snapshot_based",
        quote_staleness_seconds=12.3,
        snapshot_ids=["uuid-1", "uuid-2"],
        depth_support=True,
        partial_fill_risk=0.05,
    )
    assert result.execution_model == "snapshot_based"
    assert result.depth_support is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_shared_schemas.py -k "new_fields" -v
# Expected: AttributeError
```

- [ ] **Step 3: Add fields to `SimulationResult` in `src/parallax/shared/schemas.py`**

Find the `SimulationResult` class and add after the last existing field (`model_version`):

```python
    # Snapshot-based execution fields (default to neutral when heuristic mode)
    execution_model: Literal["heuristic", "snapshot_based", "replay_based", "degraded"] = "heuristic"
    quote_staleness_seconds: float | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    depth_support: bool | None = None
    partial_fill_risk: float = 0.0
```

Also add `Literal` to the import from `typing` if not already present.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_shared_schemas.py -v
# Expected: all PASS
uv run pytest tests/unit/ -v --tb=short -q
# Expected: full unit suite still passes
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/shared/schemas.py tests/unit/test_shared_schemas.py
git commit -m "feat(schemas): extend SimulationResult with execution_model, snapshot_ids, depth_support, partial_fill_risk"
```

---

### Task 3: Config — orderbook settings

**Files:**
- Modify: `src/parallax/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_config.py`:

```python
def test_orderbook_config_defaults():
    from parallax.config import settings
    assert settings.court_max_quote_staleness_seconds == 60.0
    assert settings.court_min_depth_size == 10.0
    assert settings.orderbook_snapshot_ttl_seconds == 45.0
    assert settings.orderbook_fetch_timeout_seconds == 5.0
    assert settings.orderbook_enabled is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_config.py -k "orderbook" -v
```

- [ ] **Step 3: Add settings to `src/parallax/config.py`**

Add after `runtime_max_candidate_concurrency`:

```python
    # Orderbook reality layer
    orderbook_enabled: bool = False
    orderbook_snapshot_ttl_seconds: float = 45.0
    orderbook_fetch_timeout_seconds: float = 5.0
    court_max_quote_staleness_seconds: float = 60.0
    court_min_depth_size: float = 10.0          # minimum contracts in book to consider depth supported
    court_partial_fill_inversion_threshold: float = 0.4  # partial_fill_risk above this triggers review
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/config.py tests/unit/test_config.py
git commit -m "feat(config): add orderbook_enabled, snapshot TTL, staleness, depth_size settings"
```

---

### Task 4: DB models — VenueToken and OrderbookSnapshotRecord

**Files:**
- Modify: `src/parallax/db/models.py`
- Modify: `tests/unit/test_db_models.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_db_models.py`:

```python
def test_venue_token_model_exists():
    from parallax.db.models import VenueToken
    row = VenueToken(
        platform="polymarket",
        raw_market_id="0xabc123",
        token_id="71321045679252212594626385532706912750332728571942532289631379312455583992745",
        outcome="YES",
    )
    assert row.platform == "polymarket"
    assert row.outcome == "YES"

def test_orderbook_snapshot_record_model_exists():
    from parallax.db.models import OrderbookSnapshotRecord
    from datetime import datetime, timezone
    row = OrderbookSnapshotRecord(
        platform="kalshi",
        raw_market_id="KXSOME-24NOV-B0.5",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bid_levels=[{"price": 0.45, "size": 100.0}],
        ask_levels=[{"price": 0.47, "size": 200.0}],
        mid_price=0.46,
        spread_bps=43.5,
        total_bid_depth=100.0,
        total_ask_depth=200.0,
    )
    assert row.platform == "kalshi"
    assert row.mid_price == 0.46
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_db_models.py -k "venue_token or orderbook_snapshot" -v
```

- [ ] **Step 3: Add models to `src/parallax/db/models.py`**

Add `UniqueConstraint` to the imports from `sqlalchemy` if not present. Then append after the last model:

```python
class VenueToken(Base):
    __tablename__ = "venue_tokens"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(50), index=True)
    raw_market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str] = mapped_column(String(512), index=True)
    outcome: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)

    __table_args__ = (
        UniqueConstraint("platform", "raw_market_id", "outcome", name="uq_venue_tokens_platform_market_outcome"),
    )


class OrderbookSnapshotRecord(Base):
    __tablename__ = "orderbook_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(50), index=True)
    raw_market_id: Mapped[str] = mapped_column(String(255), index=True)
    token_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    outcome: Mapped[str] = mapped_column(String(50))
    captured_at: Mapped[datetime] = mapped_column(_TZ, index=True)
    bid_levels: Mapped[list] = mapped_column(JSON, default=list)
    ask_levels: Mapped[list] = mapped_column(JSON, default=list)
    mid_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_bid_depth: Mapped[float] = mapped_column(Float, default=0.0)
    total_ask_depth: Mapped[float] = mapped_column(Float, default=0.0)
    fetcher_version: Mapped[str] = mapped_column(String(50), default="snapshot-v1")
    created_at: Mapped[datetime] = mapped_column(_TZ, default=_now)

    __table_args__ = (
        Index("ix_orderbook_snapshots_market_captured", "raw_market_id", "captured_at"),
    )
```

Also add `Float` to the SQLAlchemy imports if not already present.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_db_models.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/db/models.py tests/unit/test_db_models.py
git commit -m "feat(db): add VenueToken and OrderbookSnapshotRecord models"
```

---

### Task 5: Migration 0010 — venue_tokens

**Files:**
- Create: `alembic/versions/0010_venue_tokens.py`

- [ ] **Step 1: Create migration file**

```python
# alembic/versions/0010_venue_tokens.py
"""venue_tokens table

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "venue_tokens",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("raw_market_id", sa.String(255), nullable=False),
        sa.Column("token_id", sa.String(512), nullable=False),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "platform", "raw_market_id", "outcome",
            name="uq_venue_tokens_platform_market_outcome",
        ),
    )
    op.create_index("ix_venue_tokens_platform", "venue_tokens", ["platform"])
    op.create_index("ix_venue_tokens_raw_market_id", "venue_tokens", ["raw_market_id"])
    op.create_index("ix_venue_tokens_token_id", "venue_tokens", ["token_id"])


def downgrade() -> None:
    op.drop_index("ix_venue_tokens_token_id", "venue_tokens")
    op.drop_index("ix_venue_tokens_raw_market_id", "venue_tokens")
    op.drop_index("ix_venue_tokens_platform", "venue_tokens")
    op.drop_table("venue_tokens")
```

- [ ] **Step 2: Verify the down_revision matches the actual head**

```bash
uv run alembic history | head -5
# Confirm the last applied migration ID matches down_revision = "0009"
```

- [ ] **Step 3: Apply migration (requires running postgres)**

```bash
make migrate
# Expected: "Running upgrade 0009 -> 0010"
```

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/0010_venue_tokens.py
git commit -m "feat(migration): 0010 venue_tokens table"
```

---

### Task 6: Migration 0011 — orderbook_snapshots

**Files:**
- Create: `alembic/versions/0011_orderbook_snapshots.py`

- [ ] **Step 1: Create migration file**

```python
# alembic/versions/0011_orderbook_snapshots.py
"""orderbook_snapshots table

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orderbook_snapshots",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("raw_market_id", sa.String(255), nullable=False),
        sa.Column("token_id", sa.String(512), nullable=True),
        sa.Column("outcome", sa.String(50), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid_levels", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("ask_levels", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("mid_price", sa.Float, nullable=True),
        sa.Column("spread_bps", sa.Float, nullable=True),
        sa.Column("total_bid_depth", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_ask_depth", sa.Float, nullable=False, server_default="0"),
        sa.Column("fetcher_version", sa.String(50), nullable=False, server_default="snapshot-v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_orderbook_snapshots_platform", "orderbook_snapshots", ["platform"])
    op.create_index("ix_orderbook_snapshots_raw_market_id", "orderbook_snapshots", ["raw_market_id"])
    op.create_index("ix_orderbook_snapshots_captured_at", "orderbook_snapshots", ["captured_at"])
    op.create_index(
        "ix_orderbook_snapshots_market_captured",
        "orderbook_snapshots",
        ["raw_market_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_orderbook_snapshots_market_captured", "orderbook_snapshots")
    op.drop_index("ix_orderbook_snapshots_captured_at", "orderbook_snapshots")
    op.drop_index("ix_orderbook_snapshots_raw_market_id", "orderbook_snapshots")
    op.drop_index("ix_orderbook_snapshots_platform", "orderbook_snapshots")
    op.drop_table("orderbook_snapshots")
```

- [ ] **Step 2: Apply migration**

```bash
make migrate
# Expected: "Running upgrade 0010 -> 0011"
```

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0011_orderbook_snapshots.py
git commit -m "feat(migration): 0011 orderbook_snapshots table"
```

---

### Task 7: VenueTokenRegistry

**Files:**
- Create: `src/parallax/execution/token_registry.py`
- Create: `tests/unit/test_execution_token_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_execution_token_registry.py
from unittest.mock import MagicMock, patch
import uuid

def _make_market(platform: str, market_id: str, raw_payload: dict) -> MagicMock:
    m = MagicMock()
    m.platform = platform
    m.id = market_id
    m.raw_payload = raw_payload
    return m

def test_extract_polymarket_tokens():
    from parallax.execution.token_registry import VenueTokenRegistry
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    registry = VenueTokenRegistry(session)
    market = _make_market("polymarket", "0xabc", {
        "tokens": [
            {"token_id": "11111", "outcome": "Yes"},
            {"token_id": "22222", "outcome": "No"},
        ]
    })
    tokens = registry.extract_and_store(market)
    assert len(tokens) == 2
    assert session.add.call_count == 2
    outcomes = {t.outcome for t in tokens}
    assert outcomes == {"Yes", "No"}

def test_extract_polymarket_skips_missing_token_id():
    from parallax.execution.token_registry import VenueTokenRegistry
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    registry = VenueTokenRegistry(session)
    market = _make_market("polymarket", "0xabc", {
        "tokens": [{"token_id": "", "outcome": "Yes"}]
    })
    tokens = registry.extract_and_store(market)
    assert tokens == []

def test_ensure_kalshi_tokens_creates_yes_and_no():
    from parallax.execution.token_registry import VenueTokenRegistry
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    registry = VenueTokenRegistry(session)
    market = _make_market("kalshi", "KXSOME-24NOV-B0.5", {})
    tokens = registry.extract_and_store(market)
    assert len(tokens) == 2
    outcomes = {t.outcome for t in tokens}
    assert outcomes == {"Yes", "No"}
    for t in tokens:
        assert t.token_id == "KXSOME-24NOV-B0.5"

def test_get_token_id_returns_none_when_missing():
    from parallax.execution.token_registry import VenueTokenRegistry
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    registry = VenueTokenRegistry(session)
    result = registry.get_token_id("polymarket", "0xabc", "Yes")
    assert result is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_execution_token_registry.py -v 2>&1 | head -20
```

- [ ] **Step 3: Create `src/parallax/execution/token_registry.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from parallax.db.models import VenueToken


class VenueTokenRegistry:
    """Extract and persist venue-specific token IDs from raw market payloads."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def extract_and_store(self, market: object) -> list[VenueToken]:
        if market.platform == "polymarket":  # type: ignore[attr-defined]
            return self._extract_polymarket(market)
        if market.platform == "kalshi":  # type: ignore[attr-defined]
            return self._ensure_kalshi(market)
        return []

    def _extract_polymarket(self, market: object) -> list[VenueToken]:
        tokens_raw = (getattr(market, "raw_payload", None) or {}).get("tokens", [])
        result: list[VenueToken] = []
        for token in tokens_raw:
            token_id = str(token.get("token_id") or "").strip()
            outcome = str(token.get("outcome") or "").strip()
            if not token_id or not outcome:
                continue
            existing = self._get(market.platform, market.id, outcome)  # type: ignore[attr-defined]
            if existing:
                result.append(existing)
                continue
            row = VenueToken(
                id=uuid.uuid4(),
                platform=market.platform,  # type: ignore[attr-defined]
                raw_market_id=market.id,  # type: ignore[attr-defined]
                token_id=token_id,
                outcome=outcome,
            )
            self._session.add(row)
            result.append(row)
        return result

    def _ensure_kalshi(self, market: object) -> list[VenueToken]:
        result: list[VenueToken] = []
        for outcome in ("Yes", "No"):
            existing = self._get(market.platform, market.id, outcome)  # type: ignore[attr-defined]
            if existing:
                result.append(existing)
                continue
            row = VenueToken(
                id=uuid.uuid4(),
                platform=market.platform,  # type: ignore[attr-defined]
                raw_market_id=market.id,  # type: ignore[attr-defined]
                token_id=market.id,  # ticker is the effective token id for Kalshi  # type: ignore[attr-defined]
                outcome=outcome,
            )
            self._session.add(row)
            result.append(row)
        return result

    def get_token_id(self, platform: str, raw_market_id: str, outcome: str) -> str | None:
        row = self._get(platform, raw_market_id, outcome)
        return row.token_id if row else None

    def _get(self, platform: str, raw_market_id: str, outcome: str) -> VenueToken | None:
        return (
            self._session.query(VenueToken)
            .filter_by(platform=platform, raw_market_id=raw_market_id, outcome=outcome)
            .first()
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_execution_token_registry.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/execution/token_registry.py tests/unit/test_execution_token_registry.py
git commit -m "feat(execution): VenueTokenRegistry — extract and persist CLOB token IDs from raw market payloads"
```

---

### Task 8: OrderbookSnapshotStore

**Files:**
- Create: `src/parallax/execution/snapshot_store.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/unit/test_execution_token_registry.py` or new file `tests/unit/test_snapshot_store.py`:

```python
# tests/unit/test_snapshot_store.py
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

def _make_db_row(market_id: str, outcome: str, captured_at: datetime) -> MagicMock:
    row = MagicMock()
    row.id = "snap-uuid"
    row.platform = "polymarket"
    row.raw_market_id = market_id
    row.token_id = "11111"
    row.outcome = outcome
    row.captured_at = captured_at
    row.bid_levels = [{"price": 0.45, "size": 100.0}]
    row.ask_levels = [{"price": 0.47, "size": 200.0}]
    row.mid_price = 0.46
    row.spread_bps = 43.5
    return row

def test_get_recent_returns_none_when_no_row():
    from parallax.execution.snapshot_store import OrderbookSnapshotStore
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    store = OrderbookSnapshotStore(session)
    result = store.get_recent("0xabc", "YES", ttl_seconds=45.0)
    assert result is None

def test_get_recent_returns_snapshot_when_fresh():
    from parallax.execution.snapshot_store import OrderbookSnapshotStore
    from parallax.execution.schemas import OrderbookSnapshot
    session = MagicMock()
    row = _make_db_row("0xabc", "YES", datetime.now(timezone.utc) - timedelta(seconds=10))
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = row
    store = OrderbookSnapshotStore(session)
    result = store.get_recent("0xabc", "YES", ttl_seconds=45.0)
    assert isinstance(result, OrderbookSnapshot)
    assert result.market_id == "0xabc"

def test_persist_writes_record():
    from parallax.execution.snapshot_store import OrderbookSnapshotStore
    from parallax.execution.schemas import OrderbookSnapshot, OrderbookSide, OrderbookLevel
    session = MagicMock()
    snap = OrderbookSnapshot(
        id="snap-1",
        platform="kalshi",
        market_id="KXSOME",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=0.44, size=80.0)]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=0.46, size=120.0)]),
        mid_price=0.45,
        spread_bps=44.4,
    )
    store = OrderbookSnapshotStore(session)
    store.persist(snap)
    session.add.assert_called_once()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_snapshot_store.py -v 2>&1 | head -20
```

- [ ] **Step 3: Create `src/parallax/execution/snapshot_store.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from parallax.db.models import OrderbookSnapshotRecord
from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot


class OrderbookSnapshotStore:
    """Persist and retrieve orderbook snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist(self, snapshot: OrderbookSnapshot) -> OrderbookSnapshotRecord:
        row = OrderbookSnapshotRecord(
            id=uuid.uuid4(),
            platform=snapshot.platform,
            raw_market_id=snapshot.market_id,
            token_id=snapshot.token_id,
            outcome=snapshot.outcome,
            captured_at=snapshot.captured_at,
            bid_levels=[{"price": l.price, "size": l.size} for l in snapshot.bids.levels],
            ask_levels=[{"price": l.price, "size": l.size} for l in snapshot.asks.levels],
            mid_price=snapshot.mid_price,
            spread_bps=snapshot.spread_bps,
            total_bid_depth=snapshot.bids.total_depth,
            total_ask_depth=snapshot.asks.total_depth,
        )
        self._session.add(row)
        return row

    def get_recent(
        self,
        market_id: str,
        outcome: str,
        ttl_seconds: float,
    ) -> OrderbookSnapshot | None:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
        row = (
            self._session.query(OrderbookSnapshotRecord)
            .filter(
                OrderbookSnapshotRecord.raw_market_id == market_id,
                OrderbookSnapshotRecord.outcome == outcome,
                OrderbookSnapshotRecord.captured_at >= cutoff,
            )
            .order_by(OrderbookSnapshotRecord.captured_at.desc())
            .first()
        )
        if row is None:
            return None
        return self._to_schema(row)

    def _to_schema(self, row: OrderbookSnapshotRecord) -> OrderbookSnapshot:
        bids = OrderbookSide(
            levels=[OrderbookLevel(price=l["price"], size=l["size"]) for l in (row.bid_levels or [])]
        )
        asks = OrderbookSide(
            levels=[OrderbookLevel(price=l["price"], size=l["size"]) for l in (row.ask_levels or [])]
        )
        return OrderbookSnapshot(
            id=str(row.id),
            platform=row.platform,  # type: ignore[arg-type]
            market_id=row.raw_market_id,
            token_id=row.token_id,
            outcome=row.outcome,
            captured_at=row.captured_at,
            bids=bids,
            asks=asks,
            mid_price=row.mid_price,
            spread_bps=row.spread_bps,
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_snapshot_store.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/execution/snapshot_store.py tests/unit/test_snapshot_store.py
git commit -m "feat(execution): OrderbookSnapshotStore — persist and retrieve snapshots from DB"
```

---

### Task 9: PolymarketCLOBAdapter

**Files:**
- Create: `src/parallax/execution/polymarket_clob.py`
- Create: `tests/unit/test_polymarket_clob_adapter.py`

API reference: `GET https://clob.polymarket.com/book?token_id=<token_id>`
Response: `{"market": "<condition_id>", "asset_id": "<token_id>", "bids": [{"price": "0.450", "size": "100.00"}], "asks": [...]}`
Auth: none required for read-only book data.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_polymarket_clob_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

SAMPLE_CLOB_RESPONSE = {
    "market": "0xabc123",
    "asset_id": "71321045",
    "bids": [
        {"price": "0.450", "size": "100.00"},
        {"price": "0.440", "size": "50.00"},
    ],
    "asks": [
        {"price": "0.470", "size": "200.00"},
        {"price": "0.480", "size": "80.00"},
    ],
}

@pytest.mark.anyio
async def test_fetch_orderbook_parses_bids_and_asks():
    from parallax.execution.polymarket_clob import PolymarketCLOBAdapter
    from parallax.execution.schemas import OrderbookSnapshot

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = SAMPLE_CLOB_RESPONSE

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    adapter = PolymarketCLOBAdapter(http_client=mock_client)
    snap = await adapter.fetch_orderbook("71321045", outcome="YES")

    assert isinstance(snap, OrderbookSnapshot)
    assert snap.platform == "polymarket"
    assert snap.token_id == "71321045"
    assert snap.outcome == "YES"
    assert len(snap.bids.levels) == 2
    assert len(snap.asks.levels) == 2
    assert snap.bids.levels[0].price == pytest.approx(0.450)
    assert snap.asks.levels[0].price == pytest.approx(0.470)

@pytest.mark.anyio
async def test_fetch_orderbook_computes_mid_and_spread():
    from parallax.execution.polymarket_clob import PolymarketCLOBAdapter

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = SAMPLE_CLOB_RESPONSE

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    adapter = PolymarketCLOBAdapter(http_client=mock_client)
    snap = await adapter.fetch_orderbook("71321045", outcome="YES")

    assert snap.mid_price == pytest.approx(0.46, abs=0.01)
    assert snap.spread_bps is not None
    assert snap.spread_bps > 0

@pytest.mark.anyio
async def test_fetch_orderbook_empty_book():
    from parallax.execution.polymarket_clob import PolymarketCLOBAdapter

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"market": "0xabc", "asset_id": "111", "bids": [], "asks": []}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    adapter = PolymarketCLOBAdapter(http_client=mock_client)
    snap = await adapter.fetch_orderbook("111", outcome="YES")

    assert snap.bids.total_depth == 0.0
    assert snap.asks.total_depth == 0.0
    assert snap.mid_price is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_polymarket_clob_adapter.py -v 2>&1 | head -20
```

- [ ] **Step 3: Create `src/parallax/execution/polymarket_clob.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx

from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot

_CLOB_BASE = "https://clob.polymarket.com"


class PolymarketCLOBAdapter:
    """Read-only adapter for the Polymarket CLOB orderbook API.

    No authentication required. Rate limit: 10 req/s per IP (public tier).
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._client = http_client
        self._timeout = timeout

    async def fetch_orderbook(self, token_id: str, *, outcome: str = "YES") -> OrderbookSnapshot:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own = self._client is None
        try:
            resp = await client.get(f"{_CLOB_BASE}/book", params={"token_id": token_id})
            resp.raise_for_status()
            data = resp.json()
            return self._parse(token_id, outcome, data)
        finally:
            if own:
                await client.aclose()

    def _parse(self, token_id: str, outcome: str, data: dict) -> OrderbookSnapshot:
        bids = OrderbookSide(levels=[
            OrderbookLevel(price=float(b["price"]), size=float(b["size"]))
            for b in data.get("bids", [])
        ])
        asks = OrderbookSide(levels=[
            OrderbookLevel(price=float(a["price"]), size=float(a["size"]))
            for a in data.get("asks", [])
        ])
        mid_price = None
        spread_bps = None
        if bids.levels and asks.levels:
            best_bid = max(l.price for l in bids.levels)
            best_ask = min(l.price for l in asks.levels)
            mid_price = round((best_bid + best_ask) / 2.0, 6)
            if mid_price > 0:
                spread_bps = round((best_ask - best_bid) / mid_price * 10_000, 1)
        return OrderbookSnapshot(
            id=str(uuid.uuid4()),
            platform="polymarket",
            market_id=str(data.get("market", "")),
            token_id=token_id,
            outcome=outcome,
            captured_at=datetime.now(timezone.utc),
            bids=bids,
            asks=asks,
            mid_price=mid_price,
            spread_bps=spread_bps,
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_polymarket_clob_adapter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/execution/polymarket_clob.py tests/unit/test_polymarket_clob_adapter.py
git commit -m "feat(execution): PolymarketCLOBAdapter — read-only CLOB book fetch"
```

---

### Task 10: KalshiQuoteAdapter

**Files:**
- Create: `src/parallax/execution/kalshi_quotes.py`
- Create: `tests/unit/test_kalshi_quote_adapter.py`

API reference: `GET https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}/orderbook`
Response: `{"orderbook": {"yes": [[price_cents, qty], ...], "no": [[price_cents, qty], ...]}}`
Auth: none required for orderbook read.

Kalshi prices are in cents (0–99 integer). Convert to 0.0–1.0 by dividing by 100.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_kalshi_quote_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock

SAMPLE_KALSHI_RESPONSE = {
    "orderbook": {
        "yes": [[45, 100], [44, 50]],
        "no": [[54, 80], [53, 120]],
    }
}

@pytest.mark.anyio
async def test_fetch_orderbook_returns_two_snapshots():
    from parallax.execution.kalshi_quotes import KalshiQuoteAdapter
    from parallax.execution.schemas import OrderbookSnapshot

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = SAMPLE_KALSHI_RESPONSE

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    adapter = KalshiQuoteAdapter(http_client=mock_client)
    yes_snap, no_snap = await adapter.fetch_orderbook("KXSOME-24NOV-B0.5")

    assert isinstance(yes_snap, OrderbookSnapshot)
    assert isinstance(no_snap, OrderbookSnapshot)
    assert yes_snap.outcome == "YES"
    assert no_snap.outcome == "NO"
    assert yes_snap.platform == "kalshi"
    assert yes_snap.market_id == "KXSOME-24NOV-B0.5"

@pytest.mark.anyio
async def test_yes_prices_converted_from_cents():
    from parallax.execution.kalshi_quotes import KalshiQuoteAdapter
    import pytest

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = SAMPLE_KALSHI_RESPONSE

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    adapter = KalshiQuoteAdapter(http_client=mock_client)
    yes_snap, _ = await adapter.fetch_orderbook("KXSOME")

    # YES bid at 45 cents → 0.45
    prices = [l.price for l in yes_snap.bids.levels]
    assert 0.45 in prices

@pytest.mark.anyio
async def test_mid_price_computed():
    from parallax.execution.kalshi_quotes import KalshiQuoteAdapter
    import pytest

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = SAMPLE_KALSHI_RESPONSE

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    adapter = KalshiQuoteAdapter(http_client=mock_client)
    yes_snap, no_snap = await adapter.fetch_orderbook("KXSOME")

    # YES: best bid 0.45, implied ask from no_bid 1-0.54=0.46 → mid≈0.455
    assert yes_snap.mid_price is not None
    assert 0.44 < yes_snap.mid_price < 0.47
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_kalshi_quote_adapter.py -v 2>&1 | head -20
```

- [ ] **Step 3: Create `src/parallax/execution/kalshi_quotes.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx

from parallax.execution.schemas import OrderbookLevel, OrderbookSide, OrderbookSnapshot

_KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiQuoteAdapter:
    """Read-only adapter for the Kalshi binary market orderbook.

    Returns a (YES snapshot, NO snapshot) pair.
    Kalshi prices are in integer cents (0–99). Converted to 0.0–1.0 here.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._client = http_client
        self._timeout = timeout

    async def fetch_orderbook(self, ticker: str) -> tuple[OrderbookSnapshot, OrderbookSnapshot]:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        own = self._client is None
        try:
            resp = await client.get(f"{_KALSHI_BASE}/markets/{ticker}/orderbook")
            resp.raise_for_status()
            data = resp.json()
            return self._parse(ticker, data)
        finally:
            if own:
                await client.aclose()

    def _parse(self, ticker: str, data: dict) -> tuple[OrderbookSnapshot, OrderbookSnapshot]:
        book = data.get("orderbook", {})
        now = datetime.now(timezone.utc)

        yes_bids = self._to_side(book.get("yes", []))
        no_bids = self._to_side(book.get("no", []))

        # For YES: bids are YES buyers; asks are implied from NO bidders (1 - no_bid_price)
        yes_asks = OrderbookSide(levels=[
            OrderbookLevel(price=round(1.0 - l.price, 4), size=l.size)
            for l in no_bids.levels
        ])
        # For NO: bids are NO buyers; asks are implied from YES bidders
        no_asks = OrderbookSide(levels=[
            OrderbookLevel(price=round(1.0 - l.price, 4), size=l.size)
            for l in yes_bids.levels
        ])

        yes_snap = self._make_snapshot(ticker, "YES", yes_bids, yes_asks, now)
        no_snap = self._make_snapshot(ticker, "NO", no_bids, no_asks, now)
        return yes_snap, no_snap

    @staticmethod
    def _to_side(raw: list) -> OrderbookSide:
        levels = [
            OrderbookLevel(price=round(price_cents / 100.0, 4), size=float(qty))
            for price_cents, qty in raw
        ]
        return OrderbookSide(levels=sorted(levels, key=lambda l: l.price, reverse=True))

    @staticmethod
    def _make_snapshot(
        ticker: str,
        outcome: str,
        bids: OrderbookSide,
        asks: OrderbookSide,
        now: datetime,
    ) -> OrderbookSnapshot:
        mid_price = None
        spread_bps = None
        if bids.levels and asks.levels:
            best_bid = max(l.price for l in bids.levels)
            best_ask = min(l.price for l in asks.levels)
            mid_price = round((best_bid + best_ask) / 2.0, 6)
            if mid_price > 0:
                spread_bps = round((best_ask - best_bid) / mid_price * 10_000, 1)
        return OrderbookSnapshot(
            id=str(uuid.uuid4()),
            platform="kalshi",
            market_id=ticker,
            token_id=None,
            outcome=outcome,
            captured_at=now,
            bids=bids,
            asks=asks,
            mid_price=mid_price,
            spread_bps=spread_bps,
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_kalshi_quote_adapter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/execution/kalshi_quotes.py tests/unit/test_kalshi_quote_adapter.py
git commit -m "feat(execution): KalshiQuoteAdapter — read-only orderbook fetch with YES/NO conversion"
```

---

### Task 11: DepthAwareExecutablePriceEstimator and DepthAwareFillSimulator

**Files:**
- Create: `src/parallax/execution/depth_estimator.py`
- Create: `src/parallax/execution/fill_simulator.py`
- Create: `tests/unit/test_depth_estimator.py`
- Create: `tests/unit/test_fill_simulator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_depth_estimator.py
from parallax.execution.schemas import (
    DepthAnalysis, OrderbookLevel, OrderbookSide, OrderbookSnapshot
)
from datetime import datetime, timezone

def _snap(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id="test",
        platform="polymarket",
        market_id="0xabc",
        outcome="YES",
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=p, size=s) for p, s in bids]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=p, size=s) for p, s in asks]),
        mid_price=0.46,
    )

def test_depth_supported_when_enough_ask_depth():
    from parallax.execution.depth_estimator import DepthAwareExecutablePriceEstimator
    estimator = DepthAwareExecutablePriceEstimator()
    snap = _snap([], [(0.47, 200.0)])
    analysis = estimator.analyze(snap, side="buy", size=100.0)
    assert analysis.is_supported is True
    assert analysis.vwap_price == 0.47

def test_depth_unsupported_when_insufficient_ask_depth():
    from parallax.execution.depth_estimator import DepthAwareExecutablePriceEstimator
    estimator = DepthAwareExecutablePriceEstimator()
    snap = _snap([], [(0.47, 5.0)])
    analysis = estimator.analyze(snap, side="buy", size=100.0)
    assert analysis.is_supported is False
    assert analysis.vwap_price is None

def test_price_impact_bps_computed():
    from parallax.execution.depth_estimator import DepthAwareExecutablePriceEstimator
    estimator = DepthAwareExecutablePriceEstimator()
    # mid=0.46, fill at 0.47 → impact = (0.47-0.46)/0.46 * 10000 ≈ 217 bps
    snap = _snap([], [(0.47, 200.0)])
    snap.mid_price  # already set
    analysis = estimator.analyze(snap, side="buy", size=100.0)
    assert analysis.price_impact_bps is not None
    assert analysis.price_impact_bps > 0
```

```python
# tests/unit/test_fill_simulator.py
from parallax.execution.schemas import DepthAnalysis

def _analysis(is_supported: bool, impact_bps: float | None = 20.0) -> DepthAnalysis:
    return DepthAnalysis(
        market_id="0xabc",
        outcome="YES",
        required_size=100.0,
        available_depth=200.0 if is_supported else 5.0,
        is_supported=is_supported,
        vwap_price=0.47 if is_supported else None,
        price_impact_bps=impact_bps,
        snapshot_id="snap-1",
    )

def test_fill_probability_high_when_low_impact():
    from parallax.execution.fill_simulator import DepthAwareFillSimulator
    sim = DepthAwareFillSimulator()
    prob = sim.estimate_fill_probability([_analysis(True, impact_bps=5.0)])
    assert prob >= 0.88

def test_fill_probability_degraded_when_unsupported():
    from parallax.execution.fill_simulator import DepthAwareFillSimulator
    sim = DepthAwareFillSimulator()
    prob = sim.estimate_fill_probability([_analysis(False)])
    assert prob <= 0.35

def test_partial_fill_risk_low_when_all_supported():
    from parallax.execution.fill_simulator import DepthAwareFillSimulator
    sim = DepthAwareFillSimulator()
    risk = sim.estimate_partial_fill_risk([_analysis(True), _analysis(True)])
    assert risk <= 0.1

def test_partial_fill_risk_high_when_unsupported():
    from parallax.execution.fill_simulator import DepthAwareFillSimulator
    sim = DepthAwareFillSimulator()
    risk = sim.estimate_partial_fill_risk([_analysis(True), _analysis(False)])
    assert risk >= 0.3
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/unit/test_depth_estimator.py tests/unit/test_fill_simulator.py -v 2>&1 | head -25
```

- [ ] **Step 3: Create `src/parallax/execution/depth_estimator.py`**

```python
from __future__ import annotations

from typing import Literal

from parallax.execution.schemas import DepthAnalysis, OrderbookSnapshot

_DEFAULT_SIZE = 100.0


class DepthAwareExecutablePriceEstimator:
    """Estimate executable price and depth support from an orderbook snapshot."""

    def analyze(
        self,
        snapshot: OrderbookSnapshot,
        *,
        side: Literal["buy", "sell"] = "buy",
        size: float = _DEFAULT_SIZE,
    ) -> DepthAnalysis:
        book_side = snapshot.asks if side == "buy" else snapshot.bids
        vwap_side: Literal["ask", "bid"] = "ask" if side == "buy" else "bid"

        vwap = book_side.vwap(size, side=vwap_side)
        available = book_side.total_depth
        is_supported = available >= size and vwap is not None

        price_impact_bps = None
        if is_supported and snapshot.mid_price and vwap is not None and snapshot.mid_price > 0:
            price_impact_bps = round(abs(vwap - snapshot.mid_price) / snapshot.mid_price * 10_000, 1)

        return DepthAnalysis(
            market_id=snapshot.market_id,
            outcome=snapshot.outcome,
            required_size=size,
            available_depth=available,
            is_supported=is_supported,
            vwap_price=round(vwap, 6) if vwap is not None else None,
            price_impact_bps=price_impact_bps,
            snapshot_id=snapshot.id,
        )
```

- [ ] **Step 4: Create `src/parallax/execution/fill_simulator.py`**

```python
from __future__ import annotations

from parallax.execution.schemas import DepthAnalysis


class DepthAwareFillSimulator:
    """Estimate fill probability and partial fill risk from depth analyses."""

    def estimate_fill_probability(self, analyses: list[DepthAnalysis]) -> float:
        if not analyses:
            return 0.5
        if not all(a.is_supported for a in analyses):
            return 0.3
        impacts = [a.price_impact_bps for a in analyses if a.price_impact_bps is not None]
        if not impacts:
            return 0.80
        avg_impact = sum(impacts) / len(impacts)
        if avg_impact < 10:
            return 0.92
        if avg_impact < 30:
            return 0.80
        if avg_impact < 60:
            return 0.65
        return 0.45

    def estimate_slippage_bps(self, analyses: list[DepthAnalysis]) -> int:
        impacts = [a.price_impact_bps for a in analyses if a.price_impact_bps is not None]
        if not impacts:
            return 15
        return int(round(sum(impacts) / len(impacts)))

    def estimate_partial_fill_risk(self, analyses: list[DepthAnalysis]) -> float:
        """Probability that at least one leg is partially filled."""
        unsupported = sum(1 for a in analyses if not a.is_supported)
        if unsupported == 0:
            return 0.05
        return min(0.95, 0.3 + 0.25 * unsupported)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_depth_estimator.py tests/unit/test_fill_simulator.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/parallax/execution/depth_estimator.py src/parallax/execution/fill_simulator.py \
        tests/unit/test_depth_estimator.py tests/unit/test_fill_simulator.py
git commit -m "feat(execution): DepthAwareExecutablePriceEstimator and DepthAwareFillSimulator"
```

---

### Task 12: OrderbookFetcher facade

**Files:**
- Create: `src/parallax/execution/fetcher.py`
- Create: `tests/unit/test_orderbook_fetcher.py`

The fetcher is the main entry point used by SimulatorService. It:
1. Checks snapshot store for a recent cached snapshot
2. If absent or stale, fetches live from CLOB/quote adapter
3. Persists fresh snapshots
4. Returns `(list[OrderbookSnapshot], ExecutionMode)`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_orderbook_fetcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from parallax.execution.schemas import (
    ExecutionMode, OrderbookLevel, OrderbookSide, OrderbookSnapshot
)
from parallax.shared.schemas import Leg

def _fresh_snap(market_id: str, outcome: str) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id="fresh-snap",
        platform="polymarket",
        market_id=market_id,
        token_id="11111",
        outcome=outcome,
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=0.44, size=100.0)]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=0.46, size=200.0)]),
        mid_price=0.45,
    )

@pytest.mark.anyio
async def test_fetcher_returns_cached_snapshot_when_fresh():
    from parallax.execution.fetcher import OrderbookFetcher

    session = MagicMock()
    store = MagicMock()
    snap = _fresh_snap("0xabc", "YES")
    store.get_recent = MagicMock(return_value=snap)

    fetcher = OrderbookFetcher(session, snapshot_store=store)
    leg = Leg(market_id="0xabc", side="YES", price=0.45, platform="polymarket")
    snaps, mode = await fetcher.fetch_for_legs([leg])

    assert mode == "snapshot_based"
    assert len(snaps) == 1
    store.persist.assert_not_called()  # no live fetch needed

@pytest.mark.anyio
async def test_fetcher_mode_degraded_when_no_snapshot_and_no_adapter():
    from parallax.execution.fetcher import OrderbookFetcher

    session = MagicMock()
    store = MagicMock()
    store.get_recent = MagicMock(return_value=None)

    fetcher = OrderbookFetcher(session, snapshot_store=store, polymarket_clob=None, kalshi_quotes=None)
    leg = Leg(market_id="0xabc", side="YES", price=0.45, platform="polymarket")
    snaps, mode = await fetcher.fetch_for_legs([leg])

    assert mode == "degraded"
    assert snaps == []

@pytest.mark.anyio
async def test_fetcher_fetches_live_polymarket_when_no_cache():
    from parallax.execution.fetcher import OrderbookFetcher

    session = MagicMock()
    store = MagicMock()
    store.get_recent = MagicMock(return_value=None)
    store.persist = MagicMock()

    snap = _fresh_snap("0xabc", "YES")
    clob = AsyncMock()
    clob.fetch_orderbook = AsyncMock(return_value=snap)

    # token registry mock
    token_reg = MagicMock()
    token_reg.get_token_id = MagicMock(return_value="11111")

    fetcher = OrderbookFetcher(session, snapshot_store=store, polymarket_clob=clob)
    fetcher._token_registry = token_reg

    leg = Leg(market_id="0xabc", side="YES", price=0.45, platform="polymarket")
    snaps, mode = await fetcher.fetch_for_legs([leg])

    assert mode == "snapshot_based"
    assert len(snaps) == 1
    store.persist.assert_called_once()
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/unit/test_orderbook_fetcher.py -v 2>&1 | head -25
```

- [ ] **Step 3: Create `src/parallax/execution/fetcher.py`**

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from parallax.execution.kalshi_quotes import KalshiQuoteAdapter
from parallax.execution.polymarket_clob import PolymarketCLOBAdapter
from parallax.execution.schemas import ExecutionMode, OrderbookSnapshot
from parallax.execution.snapshot_store import OrderbookSnapshotStore
from parallax.execution.token_registry import VenueTokenRegistry

if TYPE_CHECKING:
    from parallax.shared.schemas import Leg

log = logging.getLogger(__name__)


class OrderbookFetcher:
    """Facade that provides orderbook snapshots for candidate trade legs.

    Tries the snapshot cache first; falls back to a live fetch; degrades
    gracefully when the live adapter fails or is not configured.
    """

    def __init__(
        self,
        session: Session,
        *,
        snapshot_store: OrderbookSnapshotStore | None = None,
        polymarket_clob: PolymarketCLOBAdapter | None = None,
        kalshi_quotes: KalshiQuoteAdapter | None = None,
        ttl_seconds: float = 45.0,
    ) -> None:
        self._session = session
        self._store = snapshot_store or OrderbookSnapshotStore(session)
        self._polymarket = polymarket_clob
        self._kalshi = kalshi_quotes
        self._ttl = ttl_seconds
        self._token_registry = VenueTokenRegistry(session)

    async def fetch_for_legs(
        self, legs: list[Leg]
    ) -> tuple[list[OrderbookSnapshot], ExecutionMode]:
        snapshots: list[OrderbookSnapshot] = []
        any_degraded = False

        for leg in legs:
            snap = await self._fetch_one(leg)
            if snap is None:
                any_degraded = True
                log.debug("No snapshot for leg %s/%s", leg.market_id, leg.side)
                continue
            if snap.is_stale:
                any_degraded = True
            snapshots.append(snap)

        if not snapshots:
            return [], "degraded"
        mode: ExecutionMode = "degraded" if any_degraded else "snapshot_based"
        return snapshots, mode

    async def _fetch_one(self, leg: Leg) -> OrderbookSnapshot | None:
        # 1. Check cache
        cached = self._store.get_recent(leg.market_id, leg.side, self._ttl)
        if cached is not None:
            return cached

        # 2. Live fetch
        try:
            snap = await self._fetch_live(leg)
        except Exception as exc:
            log.warning("Orderbook fetch failed for %s: %s", leg.market_id, exc)
            return None

        if snap is not None:
            self._store.persist(snap)
        return snap

    async def _fetch_live(self, leg: Leg) -> OrderbookSnapshot | None:
        platform = leg.platform or ""
        if platform == "polymarket":
            return await self._fetch_polymarket(leg)
        if platform == "kalshi":
            return await self._fetch_kalshi(leg)
        return None

    async def _fetch_polymarket(self, leg: Leg) -> OrderbookSnapshot | None:
        if self._polymarket is None:
            return None
        token_id = self._token_registry.get_token_id("polymarket", leg.market_id, leg.side)
        if not token_id:
            log.debug("No token_id for polymarket %s/%s", leg.market_id, leg.side)
            return None
        return await self._polymarket.fetch_orderbook(token_id, outcome=leg.side)

    async def _fetch_kalshi(self, leg: Leg) -> OrderbookSnapshot | None:
        if self._kalshi is None:
            return None
        yes_snap, no_snap = await self._kalshi.fetch_orderbook(leg.market_id)
        return yes_snap if leg.side.upper() == "YES" else no_snap
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_orderbook_fetcher.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/execution/fetcher.py tests/unit/test_orderbook_fetcher.py
git commit -m "feat(execution): OrderbookFetcher facade — cache + live fetch + persist"
```

---

### Task 13: SimulatorService — add snapshot path

**Files:**
- Modify: `src/parallax/simulator/service.py`
- Create: `tests/unit/test_simulator_snapshot_mode.py`

Design: keep `simulate(candidate_id)` unchanged (heuristic). Add `simulate_snapshot(candidate_id, snapshots, mode)` that uses depth-based analysis. CourtService will call whichever is appropriate.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_simulator_snapshot_mode.py
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
import uuid

from parallax.execution.schemas import (
    OrderbookLevel, OrderbookSide, OrderbookSnapshot
)

def _make_candidate(market_ids=None):
    c = MagicMock()
    c.id = str(uuid.uuid4())
    c.market_ids = market_ids or ["0xabc", "0xdef"]
    c.opportunity_type = "mutually_exclusive_mispricing"
    c.risk_scores = None
    c.payoff_matrix = {
        "legs": [
            {"market_id": "0xabc", "side": "NO", "price": 0.52, "platform": "polymarket"},
            {"market_id": "0xdef", "side": "NO", "price": 0.54, "platform": "polymarket"},
        ],
        "total_cost": 1.06,
        "scenarios": [],
        "worst_case_payoff": 0.03,
        "best_case_payoff": 0.03,
        "breaking_scenario": None,
        "opportunity_type": "mutually_exclusive_mispricing",
        "friction_bps": 50,
    }
    return c

def _make_snap(market_id: str, outcome: str) -> OrderbookSnapshot:
    return OrderbookSnapshot(
        id=str(uuid.uuid4()),
        platform="polymarket",
        market_id=market_id,
        token_id="11111",
        outcome=outcome,
        captured_at=datetime.now(timezone.utc),
        bids=OrderbookSide(levels=[OrderbookLevel(price=0.44, size=200.0)]),
        asks=OrderbookSide(levels=[OrderbookLevel(price=0.46, size=300.0)]),
        mid_price=0.45,
    )

def test_simulate_snapshot_returns_snapshot_based_mode():
    from parallax.simulator.service import SimulatorService

    session = MagicMock()
    candidate = _make_candidate()
    repo = MagicMock()
    repo.get = MagicMock(return_value=candidate)
    graph_repo = MagicMock()
    graph_repo.get_relations = MagicMock(return_value=[])

    svc = SimulatorService(session)
    svc._repo = repo
    svc._graph_repo = graph_repo

    snaps = [_make_snap("0xabc", "NO"), _make_snap("0xdef", "NO")]
    result = svc.simulate_snapshot(str(candidate.id), snaps, "snapshot_based")

    assert result.execution_model == "snapshot_based"
    assert result.depth_support is not None
    assert len(result.snapshot_ids) == 2

def test_simulate_snapshot_degraded_propagates_mode():
    from parallax.simulator.service import SimulatorService

    session = MagicMock()
    candidate = _make_candidate()
    repo = MagicMock()
    repo.get = MagicMock(return_value=candidate)
    graph_repo = MagicMock()
    graph_repo.get_relations = MagicMock(return_value=[])

    svc = SimulatorService(session)
    svc._repo = repo
    svc._graph_repo = graph_repo

    snaps = [_make_snap("0xabc", "NO")]  # only one snap, missing one leg
    result = svc.simulate_snapshot(str(candidate.id), snaps, "degraded")

    assert result.execution_model == "degraded"

def test_simulate_unchanged_returns_heuristic():
    from parallax.simulator.service import SimulatorService

    session = MagicMock()
    candidate = _make_candidate()
    repo = MagicMock()
    repo.get = MagicMock(return_value=candidate)
    graph_repo = MagicMock()
    graph_repo.get_relations = MagicMock(return_value=[])

    svc = SimulatorService(session)
    svc._repo = repo
    svc._graph_repo = graph_repo

    result = svc.simulate(str(candidate.id))
    assert result.execution_model == "heuristic"
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/unit/test_simulator_snapshot_mode.py -v 2>&1 | head -25
```

- [ ] **Step 3: Add `simulate_snapshot()` to `src/parallax/simulator/service.py`**

Add these imports at the top:

```python
from parallax.execution.depth_estimator import DepthAwareExecutablePriceEstimator
from parallax.execution.fill_simulator import DepthAwareFillSimulator
from parallax.execution.schemas import ExecutionMode, OrderbookSnapshot
```

Add these attributes to `__init__`:

```python
        self._depth_estimator = DepthAwareExecutablePriceEstimator()
        self._fill_simulator = DepthAwareFillSimulator()
```

Add this method to `SimulatorService` (after `simulate()`):

```python
    def simulate_snapshot(
        self,
        candidate_id: str,
        snapshots: list[OrderbookSnapshot],
        mode: ExecutionMode,
    ) -> SimulationResult:
        """Snapshot-based simulation. Uses book depth instead of heuristic formulas."""
        candidate = self._repo.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} not found")

        matrix = PayoffMatrix.model_validate(candidate.payoff_matrix)
        risk = RiskScore.model_validate(candidate.risk_scores) if candidate.risk_scores else None
        relation = self._load_primary_relation(candidate.market_ids)
        relation_signals = get_relation_signals(relation)
        opportunity_type = OpportunityType(candidate.opportunity_type)

        snap_by_market = {(s.market_id, s.outcome.upper()): s for s in snapshots}
        analyses = []
        for leg in matrix.legs:
            snap = snap_by_market.get((leg.market_id, leg.side.upper()))
            if snap is not None:
                analyses.append(self._depth_estimator.analyze(snap, side="buy", size=100.0))

        slippage_bps = self._fill_simulator.estimate_slippage_bps(analyses) if analyses else 25
        fill_probability = (
            self._fill_simulator.estimate_fill_probability(analyses)
            if analyses
            else self._estimate_fill_probability(
                len(matrix.legs), risk, opportunity_type, relation_signals,
                [leg.platform or "unknown" for leg in matrix.legs]
            )
        )
        partial_fill_risk = self._fill_simulator.estimate_partial_fill_risk(analyses) if analyses else 0.3
        depth_support = all(a.is_supported for a in analyses) if analyses else None

        slippage_cost = matrix.total_cost * slippage_bps / 10_000
        spread_cross_cost = self._spread_cross_cost(
            matrix.total_cost,
            [leg.platform or "unknown" for leg in matrix.legs],
            opportunity_type,
        )
        stale_quote_cost = 0.0  # snapshot-based; staleness tracked separately
        partial_fill_cost = self._partial_fill_cost(
            matrix.worst_case_payoff, fill_probability, opportunity_type
        )
        non_execution_cost = self._non_execution_cost(matrix.total_cost, fill_probability)
        total_drag = slippage_cost + spread_cross_cost + stale_quote_cost + partial_fill_cost + non_execution_cost
        simulated_pnl = matrix.worst_case_payoff - total_drag

        staleness = max(
            (s.staleness_seconds for s in snapshots), default=None
        ) if snapshots else None

        note = (
            f"{mode} execution model: {len(analyses)}/{len(matrix.legs)} legs with depth, "
            f"slippage {slippage_bps}bps, fill_prob {fill_probability:.3f}"
        )

        return SimulationResult(
            candidate_id=candidate_id,
            displayed_edge=round(matrix.worst_case_payoff, 6),
            executable_edge=round(simulated_pnl, 6),
            simulated_pnl=round(simulated_pnl, 6),
            friction_bps=matrix.friction_bps,
            fill_probability=fill_probability,
            is_executable=simulated_pnl > 0,
            note=note,
            estimated_slippage_bps=slippage_bps,
            estimated_slippage_cost=round(slippage_cost, 6),
            spread_cross_cost=round(spread_cross_cost, 6),
            stale_quote_cost=0.0,
            partial_fill_cost=round(partial_fill_cost, 6),
            non_execution_cost=round(non_execution_cost, 6),
            execution_quality=self._execution_quality(fill_probability),
            risk_flags=self._risk_flags(
                opportunity_type, relation_signals, risk,
                [leg.platform or "unknown" for leg in matrix.legs], fill_probability
            ),
            venue_breakdown=self._venue_breakdown(
                [leg.platform or "unknown" for leg in matrix.legs], opportunity_type
            ),
            execution_model=mode,
            quote_staleness_seconds=round(staleness, 1) if staleness is not None else None,
            snapshot_ids=[s.id for s in snapshots],
            depth_support=depth_support,
            partial_fill_risk=round(partial_fill_risk, 4),
        )
```

Also update `simulate()` to set `execution_model="heuristic"` in the returned `SimulationResult`:

In the `return SimulationResult(...)` block of `simulate()`, add `execution_model="heuristic"`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_simulator_snapshot_mode.py tests/unit/test_prover_service.py -v
# Full suite:
uv run pytest tests/unit/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/simulator/service.py tests/unit/test_simulator_snapshot_mode.py
git commit -m "feat(simulator): add simulate_snapshot() — depth-aware path with execution_model, depth_support, partial_fill_risk"
```

---

### Task 14: CourtService — orderbook-aware gates

**Files:**
- Modify: `src/parallax/court/service.py`
- Create: `tests/unit/test_court_orderbook_gates.py`

Three new gates (only active when `simulation.execution_model != "heuristic"`):
1. `stale_quote`: WATCHLIST if `quote_staleness_seconds > settings.court_max_quote_staleness_seconds`
2. `depth_unsupported`: WATCHLIST if `depth_support == False`
3. `partial_fill_inversion`: REJECT if `partial_fill_risk > settings.court_partial_fill_inversion_threshold` AND `simulated_pnl < settings.court_min_simulated_pnl`

Also add `assess_with_snapshots(candidate_id, snapshots, mode)` that calls `simulate_snapshot()` instead of `simulate()`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_court_orderbook_gates.py
from unittest.mock import MagicMock
import uuid

from parallax.shared.schemas import (
    CourtDecision, PayoffMatrix, RiskScore, SimulationResult
)

def _base_simulation(**overrides) -> SimulationResult:
    defaults = dict(
        candidate_id="test-id",
        displayed_edge=0.05,
        executable_edge=0.03,
        simulated_pnl=0.03,
        friction_bps=50,
        fill_probability=0.85,
        is_executable=True,
        note="test",
        execution_model="snapshot_based",
        quote_staleness_seconds=5.0,
        snapshot_ids=["snap-1", "snap-2"],
        depth_support=True,
        partial_fill_risk=0.05,
    )
    defaults.update(overrides)
    return SimulationResult(**defaults)

def _make_court_service():
    from parallax.court.service import CourtService
    session = MagicMock()
    svc = CourtService.__new__(CourtService)
    svc._session = session
    svc._repo = MagicMock()
    svc._market_repo = MagicMock()
    svc._graph_repo = MagicMock()
    svc._simulator = MagicMock()
    return svc

def test_stale_quote_gate_triggers_watchlist():
    from parallax.court.service import CourtService
    from parallax.config import settings

    svc = _make_court_service()
    sim = _base_simulation(quote_staleness_seconds=settings.court_max_quote_staleness_seconds + 30.0)

    gates = svc._orderbook_gates(sim)
    statuses = {g.name: g.status for g in gates}
    assert statuses.get("stale_quote") == "watchlist"

def test_depth_unsupported_gate_triggers_watchlist():
    svc = _make_court_service()
    sim = _base_simulation(depth_support=False)

    gates = svc._orderbook_gates(sim)
    statuses = {g.name: g.status for g in gates}
    assert statuses.get("depth_unsupported") == "watchlist"

def test_partial_fill_inversion_gate_triggers_reject():
    from parallax.config import settings

    svc = _make_court_service()
    sim = _base_simulation(
        partial_fill_risk=settings.court_partial_fill_inversion_threshold + 0.1,
        simulated_pnl=settings.court_min_simulated_pnl - 0.005,
    )

    gates = svc._orderbook_gates(sim)
    statuses = {g.name: g.status for g in gates}
    assert statuses.get("partial_fill_inversion") == "reject"

def test_no_gates_fire_when_heuristic_mode():
    svc = _make_court_service()
    sim = _base_simulation(
        execution_model="heuristic",
        depth_support=False,  # would trigger watchlist if snapshot_based
        quote_staleness_seconds=999.0,
    )

    gates = svc._orderbook_gates(sim)
    assert all(g.status == "info" for g in gates)

def test_clean_snapshot_passes_all_gates():
    svc = _make_court_service()
    sim = _base_simulation(
        execution_model="snapshot_based",
        quote_staleness_seconds=10.0,
        depth_support=True,
        partial_fill_risk=0.05,
        simulated_pnl=0.03,
    )
    gates = svc._orderbook_gates(sim)
    assert all(g.status in ("pass", "info") for g in gates)
```

- [ ] **Step 2: Run to confirm failures**

```bash
uv run pytest tests/unit/test_court_orderbook_gates.py -v 2>&1 | head -25
```

- [ ] **Step 3: Add `_orderbook_gates()` and `assess_with_snapshots()` to `src/parallax/court/service.py`**

Add imports:
```python
from parallax.execution.schemas import ExecutionMode, OrderbookSnapshot
```

Add method `_orderbook_gates()` to `CourtService`:

```python
    def _orderbook_gates(self, simulation: SimulationResult) -> list[DecisionGate]:
        """Evaluate orderbook-specific gates. Only fire when execution_model != 'heuristic'."""
        gates: list[DecisionGate] = []
        mode = getattr(simulation, "execution_model", "heuristic")
        if mode == "heuristic":
            gates.append(DecisionGate(
                name="stale_quote", status="info",
                observed="heuristic_mode", threshold=None,
                detail="Orderbook gates inactive in heuristic mode",
            ))
            gates.append(DecisionGate(
                name="depth_unsupported", status="info",
                observed="heuristic_mode", threshold=None,
            ))
            gates.append(DecisionGate(
                name="partial_fill_inversion", status="info",
                observed="heuristic_mode", threshold=None,
            ))
            return gates

        # Gate 1: stale quote
        staleness = simulation.quote_staleness_seconds
        max_staleness = settings.court_max_quote_staleness_seconds
        if staleness is not None and staleness > max_staleness:
            gates.append(DecisionGate(
                name="stale_quote",
                status="watchlist",
                observed=f"{staleness:.1f}s",
                threshold=f"<= {max_staleness:.0f}s",
                detail="Quote is stale; executable price may have moved",
            ))
        else:
            gates.append(DecisionGate(
                name="stale_quote",
                status="pass",
                observed=f"{staleness:.1f}s" if staleness is not None else "n/a",
                threshold=f"<= {max_staleness:.0f}s",
            ))

        # Gate 2: depth unsupported
        depth_support = simulation.depth_support
        if depth_support is False:
            gates.append(DecisionGate(
                name="depth_unsupported",
                status="watchlist",
                observed="False",
                threshold="True",
                detail="Orderbook lacks sufficient depth for trade size",
            ))
        else:
            gates.append(DecisionGate(
                name="depth_unsupported",
                status="pass",
                observed=str(depth_support),
                threshold="True",
            ))

        # Gate 3: partial fill inversion
        pfr = getattr(simulation, "partial_fill_risk", 0.0)
        threshold_pfr = settings.court_partial_fill_inversion_threshold
        if pfr > threshold_pfr and simulation.simulated_pnl < settings.court_min_simulated_pnl:
            gates.append(DecisionGate(
                name="partial_fill_inversion",
                status="reject",
                observed=f"pfr={pfr:.2f}, pnl={simulation.simulated_pnl:.4f}",
                threshold=f"pfr<={threshold_pfr:.2f} or pnl>={settings.court_min_simulated_pnl:.4f}",
                detail="High partial fill risk combined with thin simulated PnL can invert the payoff",
            ))
        else:
            gates.append(DecisionGate(
                name="partial_fill_inversion",
                status="pass",
                observed=f"pfr={pfr:.2f}",
                threshold=f"pfr<={threshold_pfr:.2f}",
            ))

        return gates
```

Add method `assess_with_snapshots()`:

```python
    def assess_with_snapshots(
        self,
        candidate_id: str,
        snapshots: list[OrderbookSnapshot],
        mode: ExecutionMode,
    ) -> tuple[CourtAssessment, SimulationResult]:
        """Like assess_with_simulation() but uses snapshot-based execution."""
        simulation = self._simulator.simulate_snapshot(candidate_id, snapshots, mode)
        ob_gates = self._orderbook_gates(simulation)

        assessment, _ = self.assess_with_simulation(candidate_id)
        # Merge orderbook gates and upgrade decision if any gate is reject
        all_gates = list(assessment.gates) + [g for g in ob_gates if g.name not in {ag.name for ag in assessment.gates}]

        reject_gate = next((g for g in ob_gates if g.status == "reject"), None)
        watchlist_gate = next((g for g in ob_gates if g.status == "watchlist"), None)

        final_decision = assessment.decision
        reasons = list(assessment.reasons)

        if reject_gate and final_decision not in (CourtDecision.REJECTED,):
            final_decision = CourtDecision.REJECTED
            reasons.append(f"orderbook gate rejected: {reject_gate.name} — {reject_gate.detail or ''}")
        elif watchlist_gate and final_decision == CourtDecision.APPROVED:
            final_decision = CourtDecision.WATCHLIST
            reasons.append(f"orderbook gate watchlisted: {watchlist_gate.name}")

        return CourtAssessment(
            decision=final_decision,
            simulated_pnl=simulation.simulated_pnl,
            fill_probability=simulation.fill_probability,
            composite_risk=assessment.composite_risk,
            reasons=reasons,
            opportunity_type=assessment.opportunity_type,
            relation_type=assessment.relation_type,
            risk_flags=assessment.risk_flags + simulation.risk_flags,
            gates=all_gates,
        ), simulation
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_court_orderbook_gates.py -v
uv run pytest tests/unit/ -q
```

- [ ] **Step 5: Commit**

```bash
git add src/parallax/court/service.py tests/unit/test_court_orderbook_gates.py
git commit -m "feat(court): add _orderbook_gates() and assess_with_snapshots() — stale_quote, depth_unsupported, partial_fill_inversion gates"
```

---

### Task 15: PipelineRunner — wire OrderbookFetcher

**Files:**
- Modify: `src/parallax/pipeline/runner.py`
- Modify: `tests/unit/test_pipeline_runner.py`

The runner already calls `CourtService.assess()` indirectly via the divergence → candidates flow. The change is: when `settings.orderbook_enabled`, build an `OrderbookFetcher` and call `court.assess_with_snapshots()` instead of `assess()` for each candidate that reaches the court step.

- [ ] **Step 1: Add a failing test for the orderbook-enabled path**

Add to `tests/unit/test_pipeline_runner.py`:

```python
def test_pipeline_runner_accepts_orderbook_enabled_flag(monkeypatch):
    """When orderbook_enabled=True, PipelineRunner does not crash on construction."""
    import importlib
    import parallax.config as cfg_module
    monkeypatch.setattr(cfg_module.settings, "orderbook_enabled", True)

    from parallax.pipeline.runner import PipelineRunner
    session_factory = MagicMock()
    runner = PipelineRunner(session_factory)
    assert runner is not None
```

- [ ] **Step 2: Run to confirm existing behavior**

```bash
uv run pytest tests/unit/test_pipeline_runner.py -k "orderbook_enabled" -v
```

- [ ] **Step 3: Add imports to `src/parallax/pipeline/runner.py`**

```python
from parallax.execution.fetcher import OrderbookFetcher
from parallax.execution.polymarket_clob import PolymarketCLOBAdapter
from parallax.execution.kalshi_quotes import KalshiQuoteAdapter
```

- [ ] **Step 4: Update candidate court evaluation in the pipeline**

In the pipeline runner's candidate evaluation loop (the section where `CourtService.assess()` is called per candidate), wrap with the orderbook path:

```python
# Find the section in runner.py where court assessment happens.
# It will look something like:
#   assessment = court_svc.assess(candidate_id)
# Replace with:

if settings.orderbook_enabled:
    with self._session_factory() as ob_session:
        fetcher = OrderbookFetcher(
            ob_session,
            polymarket_clob=PolymarketCLOBAdapter(timeout=settings.orderbook_fetch_timeout_seconds),
            kalshi_quotes=KalshiQuoteAdapter(timeout=settings.orderbook_fetch_timeout_seconds),
            ttl_seconds=settings.orderbook_snapshot_ttl_seconds,
        )
        candidate_legs = PayoffMatrix.model_validate(candidate.payoff_matrix).legs
        snapshots, ob_mode = await fetcher.fetch_for_legs(candidate_legs)
        assessment, simulation = court_svc.assess_with_snapshots(
            str(candidate.id), snapshots, ob_mode
        )
else:
    assessment, simulation = court_svc.assess_with_simulation(str(candidate.id))
```

Note: the exact integration point depends on the runner's current structure. Find the `court` call by searching for `CourtService` or `assess` in `pipeline/runner.py` and wrap as above. The change must be backward-compatible: when `orderbook_enabled=False` (the default), behavior is identical to today.

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_pipeline_runner.py -v
uv run pytest tests/unit/ -q
```

- [ ] **Step 6: Commit**

```bash
git add src/parallax/pipeline/runner.py tests/unit/test_pipeline_runner.py
git commit -m "feat(pipeline): wire OrderbookFetcher when orderbook_enabled=True"
```

---

### Task 16: End-to-end smoke test and STATUS.md update

**Files:**
- Modify: `docs/STATUS.md`

- [ ] **Step 1: Run full unit suite**

```bash
uv run pytest tests/unit/ -v --tb=short
# Expected: all pass
```

- [ ] **Step 2: Run integration tests if postgres available**

```bash
make test-integration
# May skip cleanly if postgres_test is unavailable
```

- [ ] **Step 3: Apply migrations against dev DB**

```bash
make migrate
# Expected: upgrades 0010 and 0011
```

- [ ] **Step 4: Smoke test orderbook adapters directly against live APIs (optional, requires network)**

```bash
uv run python -c "
import asyncio
from parallax.execution.polymarket_clob import PolymarketCLOBAdapter

# Use a known Polymarket YES token (from any active market's raw_payload)
# This is a read-only call with no auth
async def main():
    adapter = PolymarketCLOBAdapter()
    # Replace token_id with a real one from your DB:
    # SELECT raw_payload->'tokens'->0->>'token_id' FROM raw_markets WHERE platform='polymarket' LIMIT 1;
    snap = await adapter.fetch_orderbook('PUT_REAL_TOKEN_ID_HERE', outcome='YES')
    print('mid_price:', snap.mid_price)
    print('bid depth:', snap.bids.total_depth)
    print('ask depth:', snap.asks.total_depth)
asyncio.run(main())
"
```

```bash
uv run python -c "
import asyncio
from parallax.execution.kalshi_quotes import KalshiQuoteAdapter

async def main():
    adapter = KalshiQuoteAdapter()
    # Replace with a real ticker from your DB:
    # SELECT market_id FROM raw_markets WHERE platform='kalshi' LIMIT 1;
    yes_snap, no_snap = await adapter.fetch_orderbook('PUT_REAL_TICKER_HERE')
    print('YES mid_price:', yes_snap.mid_price)
    print('NO mid_price:', no_snap.mid_price)
asyncio.run(main())
"
```

- [ ] **Step 5: Update `docs/STATUS.md`**

Under "Verified But Still Heuristic", change the execution simulation entry from:

> execution simulation models slippage and fill probability heuristically rather than from live orderbook replay

To:

> execution simulation: snapshot-based path implemented (`execution_model=snapshot_based`); activated when `ORDERBOOK_ENABLED=true`; live CLOB adapters for Polymarket and Kalshi; heuristic fallback remains active when disabled or when fetch fails

- [ ] **Step 6: Final commit**

```bash
git add docs/STATUS.md
git commit -m "docs(status): update execution simulation maturity — snapshot-based path implemented"
```

---

## Backward compatibility

| Component | Change type | Impact |
|-----------|------------|--------|
| `SimulatorService.simulate()` | No change | Zero |
| `SimulationResult` | New fields with defaults | Old snapshots deserialize correctly |
| `CourtService.assess()` | No change | Zero |
| `Settings` | New fields with defaults | Zero |
| `DB models` | Two new tables | additive only |
| `PipelineRunner` | Conditional branch | Off by default (`orderbook_enabled=False`) |

---

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Polymarket CLOB API rate limit | Medium | TTL cache in `OrderbookSnapshotStore`; 45s TTL means at most 1 req/45s per market |
| Kalshi orderbook returns empty book | Medium | `depth_support=False` → WATCHLIST, not crash |
| Token ID not found in raw_payload | Medium-high for older markets | `_fetch_polymarket()` returns `None` → degraded mode |
| Kalshi YES/NO price conversion bug | Low | `test_yes_prices_converted_from_cents` guards this |
| `assess_with_snapshots()` upgrades decision from APPROVED → WATCHLIST | By design | Court gates are intentionally conservative |
| Running `make migrate` fails if down_revision wrong | Low | Verify with `alembic history` before applying |

---

## Success criteria

After Fase 1 is complete, the system can say:

> "This candidate has `execution_model=snapshot_based`, `quote_staleness_seconds=12.3`, `depth_support=True`, `executable_edge=0.018`, `partial_fill_risk=0.06`, backed by orderbook snapshot IDs [`snap-a`, `snap-b`] captured 12 seconds ago."

Concrete checks:
- `uv run pytest tests/unit/ -q` → all pass
- `SimulationResult.execution_model` is `"snapshot_based"` when `orderbook_enabled=True` and live fetch succeeds
- `SimulationResult.execution_model` is `"heuristic"` when `orderbook_enabled=False`
- `SimulationResult.execution_model` is `"degraded"` when fetch fails
- CourtService rejects/watchlists a stale-quote candidate correctly
- Both migrations apply cleanly

## Failure criteria

- Any test regression in existing unit suite
- `simulate()` behavior changes for `execution_model="heuristic"` path
- `assess()` behavior changes when `orderbook_enabled=False`
- Migration fails on clean DB

---

## Build order

1. Task 1 — execution schemas (foundation)
2. Task 2 — SimulationResult extension
3. Task 3 — config
4. Task 4 — DB models
5. Tasks 5–6 — migrations (requires running DB)
6. Tasks 7–8 — token registry + snapshot store
7. Tasks 9–10 — CLOB adapters
8. Tasks 11–12 — depth estimator + fill simulator
9. Task 13 — fetcher facade
10. Task 14 — simulator snapshot path
11. Task 15 — court gates
12. Task 16 — pipeline wiring
13. Task 17 — smoke test + STATUS.md

Each task is independently committable. Tasks 5–6 require a running postgres; all others are unit-testable without DB.

---

## Next command after approval

```
/build
```
