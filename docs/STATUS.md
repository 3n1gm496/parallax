# Status

This file is the source of truth for the verified state of the repo as checked on `2026-05-03`.

## Current Verified Runtime

Parallax currently has a coherent backend and UI slice with:

- native Polymarket ingestion
- native Kalshi ingestion
- persisted markets with canonical platforms limited to `polymarket` and `kalshi`
- contract compilation and persistence
- identity-qualified relation proof
- Anthropic-backed semantic veto / confirmation for selected relation types
- divergence candidate creation
- heuristic risk scoring
- court assessment using relation evidence plus execution simulation
- paper-position opening, settlement, and autopsy persistence
- FastAPI routes for markets, candidates, audit, operations, and positions
- a React lifecycle console for feed, triage, operations, relation sets, positions, and audit

## Verified In This Checkout

- backend unit test suite passes in the local `.venv` (`97 passed` on the current targeted verification slice)
- frontend typecheck passes when UI dependencies are installed
- frontend production build passes when UI dependencies are installed
- candidate detail exposes live `simulation_result`, `court_assessment`, and relation evidence
- court evaluation now persists a decision snapshot with relation evidence, simulation output, and court assessment at evaluation time
- relation evidence includes structural and semantic fields, breaking scenarios, relation signals, and evidence versioning
- identity links now carry `link_reason` and structured provenance
- identity review is now persisted explicitly in `identity_match_reviews`
- relation evidence now carries `identity_status`, `identity_confidence`, `identity_version`, and `identity_blocking_reason`
- strict semantic tradeability now requires `identity_status=verified`
- `/api/ops/metrics` exposes pipeline activity, recent pipeline runs, and autopsy label counts
- persisted `run_proofs` exist as a first-class model and are exposed through `/api/ops/runs` and `/api/ops/runs/{run_id}`
- `/api/ops/metrics` now also exposes first-pass calibration pressure derived from autopsy labels
- `/api/ops/metrics` now also exposes an offline evaluation pack from settled positions plus autopsy history
- `/api/ops/evaluation` exposes the same evaluation pack as a dedicated report contract
- `/api/ops/backtest` exposes row-level replay from persisted decision snapshots
- `/api/ops/policy` exposes a versioned policy/calibration report with threshold recommendations
- `/api/ops/identity-review` exposes a server-side queue for ambiguous or mismatch-prone identity cases
- `/api/ops/relation-sets` and `/api/ops/relation-sets/{set_key}` expose persisted n-ary proof records
- settlement supports autopsy labels such as `execution_miss` and `oracle_mismatch`
- UI now includes a triage surface for ambiguity, execution drag, identity conflict, and autopsy-failure queues
- operations UI now includes evaluation metrics for realized win rate, edge capture, and opportunity-type breakdown
- operations UI now includes a task-oriented operator workflow section driven by policy pressure, identity queue, and invalidated replays
- `/ready` now exposes degraded reasons plus runtime control switches for pause, semantic-analysis disable, and live-execution disable
- `market_relations` is now legacy compatibility persistence only and is disabled by default for new writes

## Verified But Still Heuristic

- identity matching beyond native `group_id` is conservative multi-signal logic, not a trained entity-resolution system
- risk scoring is still a heuristic composite, even though it is now versioned and decomposed into a richer vector
- court gating is structured and opportunity-aware, but still threshold-based
- execution simulation models slippage and fill probability heuristically rather than from live orderbook replay
- quote provenance is still heuristic metadata, not a captured live orderbook snapshot
- identity review queue ordering is rule-based rather than learned from a historical calibration model
- policy recommendations are versioned and evidence-backed, but still heuristic rather than learned

## Not Yet Proven Here

- a recent end-to-end real-data run with:
  - Polymarket ingestion
  - Kalshi ingestion
  - Anthropic compilation
  - live semantic relation confirmation
  - candidate generation from the same run
  - opened and settled positions tied to that same run

## Current Operational Blockers

- real-data proof remains blocked unless `.env` contains working Anthropic credentials and a reachable runtime database

## What To Trust

- trust this file for verified maturity
- trust `RUNTIME.md` for the intended active contract
- trust `RUNBOOK.md` for what counts as proof
- do not trust historical plan documents as proof that something is live
