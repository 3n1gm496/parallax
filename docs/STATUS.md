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

## Orderbook Reality Layer (Fase 1 — 2026-05-03)

The execution layer now has a snapshot-based path alongside the heuristic path:

- `src/parallax/execution/` package: `OrderbookSnapshot`, `OrderbookSide`, `OrderbookLevel`, `DepthAnalysis`, `ExecutionMode`
- `SimulationResult` carries `execution_model` (heuristic / snapshot_based / replay_based / degraded), `quote_staleness_seconds`, `snapshot_ids`, `depth_support`, `partial_fill_risk`
- `PolymarketCLOBAdapter`: read-only CLOB orderbook fetch (`GET /book?token_id=…`)
- `KalshiQuoteAdapter`: read-only orderbook fetch, translates YES/NO cent prices to probability floats
- `VenueTokenRegistry`: persists (platform, market_id, outcome) → token_id mapping in `venue_tokens`
- `OrderbookSnapshotStore`: persists and retrieves `OrderbookSnapshot` objects from `orderbook_snapshots`
- `DepthAwareExecutablePriceEstimator`: VWAP-based executable price from book depth
- `DepthAwareFillSimulator`: fill probability and partial-fill risk from depth ratios
- `OrderbookFetcher`: unified fetcher; returns `None` when `orderbook_enabled=False`
- `SimulatorService.simulate_snapshot()`: snapshot path; `execution_model=degraded` when any leg is missing a snapshot
- `CourtService.assess_with_snapshots()` / `evaluate_with_snapshots()`: snapshot-based court path with three extra gates: quote_staleness, depth_support, partial_fill_inversion
- `PipelineRunner` wired: when `orderbook_enabled=True`, fetches snapshots per candidate leg and routes to `evaluate_with_snapshots()`; falls back to heuristic when disabled

Migration chain: `0010_venue_tokens` → `0011_orderbook_snapshots` applied.

## Token Discovery Layer (Fase 2 — 2026-05-03)

`venue_tokens` is now populated during ingestion so the snapshot-based court path is reachable on real Polymarket candidates:

- `RawMarketData` carries `token_ids: dict[str, str]` — populated by `PolymarketAdapter._extract_token_ids()`
- Shape A (`tokens[i].token_id + outcome`) and Shape B (`clobTokenIds[]` parallel to `outcomes[]`) both handled
- `TokenDiscoveryService` (`src/parallax/execution/token_discovery.py`): sync, upserts (platform, raw_market_id, outcome) → token_id rows during `IngestorService._ingest_one()`, after market upsert loop
- `PipelineRunner._persist_snapshot_sync()`: persists fetched snapshots to `orderbook_snapshots` inside `begin_nested()` before `evaluate_with_snapshots()`
- Kalshi orderbook path does not require token IDs (ticker = market_id directly)
- The `evaluate_with_snapshots` path is now end-to-end reachable when `orderbook_enabled=True` and Polymarket markets have been ingested

## Execution Observability Layer (Fase 3 — 2026-05-03)

The snapshot execution path is now visible across the ops surface, readiness report, and UI:

- `GET /api/ops/execution`: `ExecutionReport` with `venue_tokens` coverage by platform, `orderbook_snapshots` stats, execution_model distribution from last 500 decision snapshots, avg quote staleness, depth support rate
- `ReadinessReport` carries `orderbook_enabled` and `venue_token_count`
- `CandidateSummary` carries `execution_model` (batch-loaded from decision snapshots, no N+1)
- `CandidateDetail.tsx`: Execution section renders `execution_model`, `depth_support`, `quote_staleness_seconds`, `partial_fill_risk`
- `OperationsView.tsx`: Execution Coverage panel fetches `/api/ops/execution` and shows per-platform token/snapshot counts, staleness, and model distribution
- Frontend `SimulationResult` and `CandidateSummary` types updated to carry new fields

## Risk Score Snapshot Integration (Fase 4 — 2026-05-03)

Orderbook signals now feed back into `RiskScore` at court evaluation time:

- `RiskScore.adjust_from_simulation(base, simulation) -> RiskScore`: static method producing a snapshot-adjusted score
  - `depth_support=True` → lowers `execution_risk` by 0.08 (clamped at 0.0)
  - `depth_support=False` → raises `execution_risk` by 0.30 (clamped at 1.0)
  - `partial_fill_risk > 0` → `liquidity_risk = max(base, partial_fill_risk * 0.8)`
  - `composite` recomputed from adjusted components; `policy_version="risk-v2-snapshot"`
- `CourtService._compute_adjusted_risk()`: fetches candidate's stored risk and calls `adjust_from_simulation`
- `CourtService._run_assessment()`: accepts optional `risk_override` parameter; uses it in place of candidate's stored score when provided
- `CourtService.assess_with_snapshots()`: computes adjusted risk, injects into `_run_assessment`, returns 3-tuple `(assessment, simulation, adjusted_risk)`
- `CourtService._persist_evaluation()`: accepts `adjusted_risk` kwarg; persists it in decision snapshot when provided
- Original `opportunity_candidates.risk_scores` column is never mutated; adjustment is evaluation-time only

## Replay-Based Execution Path (Fase 5 — 2026-05-03)

Settled paper-position history now feeds back into the execution estimate when live orderbook snapshots are unavailable:

- `ReplayStatisticsService` (`src/parallax/execution/replay_stats.py`): queries the last 20 closed positions for the same opportunity type, computes `win_rate` and `mean_edge_capture` from `CandidateDecisionSnapshot.simulation_result` joined with `PaperPosition.actual_pnl`; returns `None` when fewer than 3 settled positions exist
- `SimulatorService.simulate_replay()`: calls heuristic first, then applies replay calibration — `fill_probability = win_rate`, `simulated_pnl = heuristic_pnl × effective_capture` (clamped [0, 1.5]); falls back to heuristic model when history is insufficient
- `CourtService.evaluate_with_replay()`: mirrors `evaluate()` but calls `simulate_replay()`; all existing court gates apply to the replay-adjusted simulation
- `PipelineRunner`: when `orderbook_enabled=False`, checks `ReplayStatisticsService.get_stats()` before deciding between replay and heuristic paths; snapshot path takes priority when enabled

The replay path only activates after sufficient settlement history accumulates (minimum 3 closed positions per opportunity type).

## Automated Settlement Layer (Fase 6 — 2026-05-03)

Open paper positions are now automatically settled when all underlying markets have closed with deterministic prices:

- `SettlementScannerService` (`src/parallax/settlement/scanner.py`): scans `OPEN` paper positions each pipeline run; skips positions where any market is still open or has an ambiguous final price (0.1 < YES price < 0.9)
- Resolution inference: `outcome_prices[0]` ≥ 0.9 → YES, ≤ 0.1 → NO, else ambiguous (manual settlement required)
- PnL computation: per-leg win/loss from stored `legs_json`; normalized by `PayoffMatrix.total_cost`; clamped to [-1.0, 1.0]
- Calls `TrackerService.close_position()` + `AutopsyService.record(resolution_type=CORRECT)` per settled position
- `PipelineRunner.run_once()` invokes scanner after the candidate loop; scanner failures are caught and logged without aborting the run
- `positions_settled` in `RunSummary` and `RunProofRecord` now reflects auto-settled positions

## Verified But Still Heuristic

- identity matching beyond native `group_id` is conservative multi-signal logic, not a trained entity-resolution system
- risk scoring is still a detection-time heuristic composite; when snapshot-based simulation is available, `execution_risk` and `liquidity_risk` are adjusted from `depth_support` and `partial_fill_risk` and the adjusted score is persisted in the decision snapshot (`policy_version="risk-v2-snapshot"`)
- court `composite_risk` gate uses snapshot-adjusted composite when `orderbook_enabled=True`, detection-time composite otherwise
- court gating is structured and opportunity-aware, but still threshold-based
- execution simulation defaults to heuristic when `orderbook_enabled=False`; snapshot path available when enabled
- settlement scanner only infers resolution from `outcome_prices[0]`; unusual oracle formats (multi-outcome, scaled) require manual settlement
- orderbook snapshot path is not yet tested against live CLOB APIs; adapters are implemented and unit-tested with mocks
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
