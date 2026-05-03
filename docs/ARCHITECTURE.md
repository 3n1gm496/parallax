# Architecture

This file is the concise architecture map for the active Parallax implementation.

## Core Flow

```text
native venue adapters
  -> raw_markets
  -> compiler
       -> compiled_contracts
       -> compiled_propositions
  -> identity
       -> canonical_events
       -> market_event_links
       -> identity_match_reviews
  -> event_frames
       -> canonical_event_frames
  -> prover
       -> relation proposals
       -> logic proof
       -> semantic veto
       -> counterexample search
       -> logical_relations
       -> logical_relation_sets
       -> relation_reviews
       -> counterexample_records
  -> divergence
       -> opportunity_candidates
  -> court
       -> candidate_decision_snapshots
  -> tracker
       -> paper_positions
  -> autopsy
       -> autopsy_records
  -> evaluation / policy
       -> ops backtest
       -> ops policy
```

## Authority Order

1. Identity
2. Logical / semantic proof
3. Tradeability
4. Execution realism
5. Settlement / autopsy feedback

If two layers disagree, the upstream layer wins. In particular:

- semantic proof does not override ambiguous identity
- tradeability does not override rejected proof
- displayed edge does not override execution drag

## Storage Boundaries

- `logical_relations`: authoritative pairwise proof record
- `logical_relation_sets`: authoritative n-ary proof record
- `market_relations`: legacy compatibility write model only, disabled by default for new writes

## Identity Contract

Identity is not inferred ad hoc by downstream consumers.

Authoritative persisted identity state lives in:

- `market_event_links`
- `identity_match_reviews`

Downstream consumers use the explicit status:

- `verified`
- `ambiguous`
- `unresolved`
- `rejected`

Strict semantic opportunities must not become tradeable unless identity is `verified`.

## Operator Surfaces

- `/ready`: runtime readiness
- `/api/ops/runs`: persisted run proofs
- `/api/ops/metrics`: aggregate operations view
- `/api/ops/evaluation`: settled evaluation summary
- `/api/ops/backtest`: row-level replay ledger
- `/api/ops/policy`: threshold and calibration recommendations
- `/api/ops/identity-review`: ambiguity queue
- `/api/ops/relation-sets`: n-ary proof inspection

## UI Surfaces

- feed
- triage
- operations
- relation sets
- positions
- audit

The operations view is the operator workflow surface. The relation-sets view is the deep proof-inspection surface.
