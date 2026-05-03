# Runtime Contract

## Pipeline Shape

```
PolymarketAdapter + KalshiAdapter
  -> IngestorService
  -> MarketRepository
  -> CompilerService
  -> IdentityService
       -> identity_match_reviews
  -> RelationPipelineService
       -> RelationProposalGenerator
       -> EventFrameBuilder
       -> LogicEngine
       -> SemanticVeto
       -> CounterexampleEngine
       -> logical_relations
       -> logical_relation_sets
  -> DivergenceService
  -> candidates.CandidateRepository
  -> CourtService
  -> SimulatorService
  -> TrackerService
  -> AutopsyService via settlement route
```

## Venue And Provider Rules

- Polymarket uses the native adapter.
- Kalshi uses the native public trade API adapter.
- Persisted market platforms remain only `polymarket` and `kalshi`.

## Decision-Core Contract

The decision core is the combined behavior of:

- identity-qualified relation proposal generation
- logic proof
- semantic veto / counterexample confirmation
- Divergence candidate creation
- Court assessment
- Execution simulation

Current persisted and exposed evidence includes:

- identity status, confidence, scorer version, and blocking reason
- structural and semantic relation labels
- semantic confidence and semantic reasoning
- breaking scenarios
- explicit `is_confirmed` and `abstention_reason` state for negative or insufficient semantic outcomes
- relation signals
- evidence version
- alignment fields for oracle, deadline, and source
- ambiguity terms
- versioned risk score with oracle, deadline, semantic, execution, liquidity, cancellation, and source-trust components
- versioned court assessment
- simulation model version
- displayed edge versus executable edge breakdown

## Identity Contract

Identity resolution is conservative by design:

- use native `group_id` when available
- otherwise attempt a multi-signal event match
- if the match is ambiguous or unresolved, persist a scored review artifact and downgrade downstream tradeability

Persisted identity link evidence currently includes:

- `link_reason`
- `provenance`
- canonical event id through `market_event_links`
- explicit scored review state through `identity_match_reviews`

Identity states used downstream:

- `verified`
- `ambiguous`
- `unresolved`
- `rejected`

Tradeability rule:

- semantic or logical proof alone is insufficient
- `tradeable_relation=true` requires `identity_status=verified`

## API Contract

Health:

- `GET /health`
- `GET /ready`

Read routes:

- `GET /api/markets`
- `GET /api/markets/{market_id}`
- `GET /api/candidates`
- `GET /api/candidates/{candidate_id}`
- `GET /api/candidates/{candidate_id}/decision`
- `GET /api/candidates/{candidate_id}/autopsy`
- `GET /api/audit`
- `GET /api/audit/{entity_type}/{entity_id}`
- `GET /api/ops/metrics`
- `GET /api/ops/runs`
- `GET /api/ops/runs/{run_id}`
- `GET /api/ops/evaluation`
- `GET /api/ops/backtest`
- `GET /api/ops/policy`
- `GET /api/ops/identity-review`
- `GET /api/ops/relation-sets`
- `GET /api/ops/relation-sets/{set_key}`
- `GET /api/positions`
- `GET /api/positions/{position_id}`

Write route:

- `POST /api/positions/{position_id}/settle`

Access model:

- read routes use `require_read_access`
- write routes use `require_write_access`
- read auth is optional and controlled by `API_REQUIRE_AUTH_FOR_READS`
- write auth is optional and controlled by `API_AUTH_TOKEN`

## Ops Contract

`GET /api/ops/metrics` is the primary proof surface for recent runtime activity.

It currently exposes:

- market counts by platform
- candidate counts by decision
- open position count
- pipeline activity metrics
- recent run summaries with `run_id` and config fingerprint
- audit totals
- autopsy totals, resolution counts, and label counts
- calibration pressure derived from autopsy labels
- an offline evaluation pack derived from settled paper positions and autopsy rows
- verified relation-set counts by relation type

`GET /api/ops/backtest` is the detailed replay surface.

It exposes:

- row-level replay ledger from persisted decision snapshots
- `identity_invalidated` versus `oracle_invalidated` outcomes
- stored edge, realized pnl, and edge-capture ratio

`GET /api/ops/policy` is the calibration and threshold-governance surface.

It exposes:

- versioned policy recommendations
- component-specific risk pressure
- replay-derived invalidation counts
- recommended threshold deltas for operator review

`GET /api/ops/relation-sets` and `GET /api/ops/relation-sets/{set_key}` expose:

- persisted n-ary proof records
- member market ids
- set-level proof status and tradeability
- semantic pair reviews and raw evidence

`GET /api/ops/runs` and `GET /api/ops/runs/{run_id}` expose persisted run proofs with:

- run timestamps and status
- config fingerprint
- provider fingerprints
- run counts and errors
- readiness snapshot captured at run completion
- runtime control state captured at run completion

`GET /ready` is the lightweight readiness surface.

It currently reports:

- database reachability
- semantic analysis configuration status
- provider status for Polymarket and Kalshi
- latest observed market freshness by platform
- degraded reasons
- runtime controls including pause switches and live-execution disable state

This is still a repo-local readiness check, not an active external network probe.

## UI Contract

The UI in `ui/` is a lightweight operator console with six views:

- opportunity feed
- triage queues
- operations
- relation sets
- positions
- audit trail

Candidate detail surfaces:

- persisted payoff data
- persisted decision snapshot from evaluation time
- live simulation output
- displayed edge versus executable edge
- live court assessment
- relation evidence
- linked paper positions
- autopsy rows
- audit history

The triage view groups current repo-backed cases into:

- ambiguous semantic pairs
- high-edge / low-liquidity candidates
- identity conflicts
- autopsy failures requiring policy review

The operations view also surfaces:

- readiness state
- recent run summaries
- autopsy taxonomy
- calibration pressure
- policy recommendations
- operator workflow queue
- offline evaluation metrics:
  - realized win rate
  - false-positive rate on settled paper positions
  - average expected edge versus average realized pnl
  - average edge-capture ratio
  - opportunity-type breakdown

## Config Surface

Primary env vars:

- `DATABASE_URL`
- `TEST_DATABASE_URL`
- `ANTHROPIC_API_KEY`
- `FRICTION_BPS`
- `COMPILER_MIN_CONFIDENCE`
- `SEMANTIC_MIN_RELATION_CONFIDENCE`
- `COURT_MAX_COMPOSITE_RISK`
- `COURT_MIN_SIMULATED_PNL`
- `COURT_MIN_FILL_PROBABILITY`
- `POLYMARKET_MAX_EVENTS_PER_POLL`
- `KALSHI_MAX_EVENTS_PER_POLL`
- `PIPELINE_MAX_OPEN_MARKETS`
- `API_AUTH_TOKEN`
- `API_REQUIRE_AUTH_FOR_READS`
- `API_DOCS_ENABLED`
- `APP_ENV`
- `PROVIDER_FRESHNESS_THRESHOLD_MINUTES`
- `RUNTIME_GLOBAL_PAUSE`
- `RUNTIME_PAUSE_POLYMARKET`
- `RUNTIME_PAUSE_KALSHI`
- `RUNTIME_SEMANTIC_ANALYSIS_DISABLED`
- `RUNTIME_LIVE_EXECUTION_ENABLED`
- `RUNTIME_DEGRADED_READ_ONLY`
- `RUNTIME_MAX_EXPOSURE`
- `RUNTIME_MAX_DAILY_LOSS`
- `RUNTIME_MAX_CANDIDATE_CONCURRENCY`

## Invariants

- `worst_case_payoff` is already post-friction and must not be friction-adjusted a second time downstream
- candidate detail may compute live simulation and court output on demand, but approval-time decision evidence must be persisted when court evaluation runs
- semantic analysis persists both positive and negative semantic outcomes, including abstentions and below-floor confirmations
- paper positions are only opened for approved candidates that still look executable at evaluation time
- strict semantic opportunities must not pass court or divergence if identity is not verified
- `market_relations` is a disabled-by-default compatibility write model; authoritative decision logic must use `logical_relations` and `logical_relation_sets`
