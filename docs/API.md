# API & Runtime Contract

This file describes the current runtime contract, not the aspirational roadmap.

## Cold Path Pipeline (Semantic)

`IngestorService -> CompilerService -> IdentityService/IdentityV3Service -> RelationPipelineService -> DivergenceService -> CourtService -> CertificateService -> TrackerService -> SettlementScannerService -> AutopsyService -> CalibrationService`

## Hot Path Pipeline (Execution)

`MarketFeed -> L1HotCache -> OrderbookManager (Rust) -> BasketOptimizer (MILP) -> ExecutionManager -> UnwindEngine`

## Authority Order

1. Identity Authority
2. Relation Proof (Logical Thesis)
3. Trade Proof Certificate (Signed Authorization)
4. Hot Cache Freshness Check
5. Volatility-Aware Edge Verification
6. Atomic Fund Validation
7. Execution Manager (Concurrent Submission)
8. Unwind Engine (Emergency Recovery)
9. Autopsy & Performance Audit

- **Zero-Trust Execution**: No order is submitted without a valid `TradeProofCertificate` and verified `IdentityV3`.
- **Atomic Fund Checks**: Pre-trade balance verification is mandatory. Orders exceeding available liquidity are rejected pre-submission.
- **Volatility Premium**: Minimum edge requirements are dynamically increased by up to 50 bps during periods of high market update frequency (tracked via L1 Cache).
- **Toxic Flow Protection**: Unwind pricing must be derived from real-time L1 Cache best bid/ask, not stale execution prices.
- **Deterministic Solving**: MILP solver complexity is capped at 5,000 states to prevent sub-optimal latency spikes.

## Execution Paths

Primary runtime surfaces should prefer these execution-path labels:

- `primary_proof_based`
- `calibrated_model`
- `degraded_fallback`
- `offline_validation`

Legacy execution-model strings remain in historical rows and compatibility payloads:

- `heuristic`
- `snapshot_based`
- `replay_based`
- `degraded`

No live execution exists. No wallet, custody, or secrets-handling path exists.

## Active Policy

When calibration has enough settled data, `CourtService`, `SimulatorService`, and solver policy construction can read persisted active policy:

- court thresholds
- risk weights
- solver penalties
- execution calibration

If data is insufficient, calibration records `status=insufficient_data` and no behavior should be claimed as calibrated runtime proof.

## Read APIs

- `/ready`
- `/api/candidates`
- `/api/candidates/{candidate_id}`
- `/api/candidates/{candidate_id}/decision`
- `/api/candidates/{candidate_id}/decision-ledger`
- `/api/candidates/{candidate_id}/certificate`
- `/api/ops/metrics`
- `/api/ops/runs`
- `/api/ops/execution`
- `/api/ops/proof`
- `/api/ops/identity-review`
- `/api/ops/identity-clusters`
- `/api/ops/identity-clusters/{cluster_id}`
- `/api/ops/identity-metrics`
- `/api/ops/calibration`
- `/api/ops/policy`
- `/api/ops/policy/active`
- `/api/ops/scorecards`
- `/api/ops/strategy-kill-list`
- `/api/ops/certificates`

## Write APIs

- `/api/candidates/{candidate_id}/certificate/issue`
- `/api/ops/identity-clusters/{cluster_id}/review`
- `/api/ops/identity-clusters/{cluster_id}/split`
- `/api/ops/identity-clusters/merge`
- `/api/positions/{position_id}/settle`

## Proof Boundary

This repo now has stronger proof-chain enforcement in code, but real-data proof is still unproven until:

- Alembic upgrade succeeds on a clean DB
- pipeline run completes against real persisted data
- certificate issuance succeeds on a real candidate
- the same chain is inspectable through API/UI

Migration truth checked on `2026-05-04`:

- configured local DB `upgrade head` passed outside sandbox
- clean test DB `upgrade head -> downgrade 0013 -> upgrade head` passed
