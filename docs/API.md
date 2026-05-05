# RUNTIME

This file describes the current runtime contract, not the aspirational roadmap.

## Pipeline

`IngestorService -> CompilerService -> IdentityService/IdentityV3Service -> RelationPipelineService -> DivergenceService -> CourtService -> CertificateService -> TrackerService -> SettlementScannerService -> AutopsyService -> CalibrationService`

## Authority Order

1. Identity
2. Relation proof
3. Solver proof object + scenario matrix
4. Execution realism
5. Court decision snapshot
6. Trade proof certificate
7. Paper position
8. Autopsy
9. Calibration / active policy

## Runtime Rules

- Identity v3 is now consulted first; legacy `group_id` and v2-style matching remain fallback.
- Strict semantic opportunities must not pass the solver path unless identity status is `verified` and identity version is `identity-v3*`.
- Candidate persistence requires `scenario_matrix_json` and `proof_object_json`.
- Certificate issuance requires:
  - candidate exists
  - verified identity in relation evidence
  - scenario matrix present
  - proof object present
  - decision snapshot present
  - simulation result present
  - snapshot ids if execution model is `snapshot_based`
  - proof status not `false_arbitrage`
- Paper position opening requires an issued certificate.
- Issued certificates are treated as immutable proof rows for re-issue purposes; status changes happen through invalidate / supersede instead of mutating the proof payload.

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
