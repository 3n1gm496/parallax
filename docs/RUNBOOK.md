# RUNBOOK

This is the current runbook for proving PARALLAX Omega honestly.

## 1. Clean DB / Migrations

Required proof:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run alembic upgrade head
```

Observed on `2026-05-04`:

- the command passed outside sandbox against the configured local DB
- clean test DB validation also passed with:

```bash
upgrade head
downgrade 0013
upgrade head
```

Important:

- `alembic/env.py` must respect an explicitly supplied `sqlalchemy.url`
- use `127.0.0.1:55432/55433` when the repo `.env` is configured that way

## 2. Backend Validation

Verified in this turn:

```bash
uv run pytest tests/unit
uv run pytest tests/integration
```

Observed results:

- `tests/unit`: `351 passed`
- `tests/integration`: `13 passed` outside sandbox against the local Postgres test DB

## 3. Frontend Validation

Verified in this turn:

```bash
cd ui
npm run typecheck
npm run build
```

Observed results:

- typecheck passed
- production build passed

Smoke:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/smoke
```

- `2 skipped`
- reason: opt-in smoke env not available in this turn

## 4. Real-Data Proof Path

Once DB and credentials are available:

```bash
docker compose up -d
UV_CACHE_DIR=/tmp/uv-cache uv run alembic upgrade head
uv run python -m parallax.pipeline.runner
uv run uvicorn parallax.api.app:app --port 8000
```

Then verify:

```bash
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/api/ops/runs
curl http://127.0.0.1:8000/api/ops/certificates
curl http://127.0.0.1:8000/api/ops/calibration
curl http://127.0.0.1:8000/api/ops/proof
curl http://127.0.0.1:8000/api/candidates
```

To save a proof bundle:

```bash
mkdir -p docs/proofs
curl http://127.0.0.1:8000/api/ops/proof > docs/proofs/proof-$(date -u +%Y%m%dT%H%M%SZ).json
```

## 5. What Must Be True Before Saying "No Proof, No Bet" Is Proven

- at least one candidate has:
  - scenario matrix
  - proof object
  - decision snapshot
  - issued certificate
- a paper position opens only with the issued certificate
- the certificate is inspectable through API/UI

## 6. What Must Be True Before Saying Calibration Is Closed-Loop

- at least one `calibration_run` persisted
- `status != insufficient_data` on that run
- an `active_policy_version` was activated from it
- court/simulator behavior is demonstrably reading that active policy
- solver policy construction is demonstrably reading active `solver_penalties`

## 7. What Not To Claim

- Do not claim real-data proof from unit tests.
- Do not claim clean migration proof from skipped or unreachable DB steps.
- Do not claim live execution support.
- Do not call a candidate arbitrage if the proof object marks `false_arbitrage`.
