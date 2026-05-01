# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs).

## Index

| ADR | Title | Status | Date | Summary |
|---|---|---|---|---|
| [0001](0001-foundation-slice-1-opportunity-priority.md) | Foundation Slice 1 Opportunity Priority | Accepted | 2026-04-29 | Prioritize intra-platform logical consistency (mutually exclusive mispricing) before cross-platform semantic equivalence. 99.76% of documented arbitrage is this type. |
| [0002](0002-llm-provider-event-contract-compiler.md) | LLM Provider for Event Contract Compiler | Accepted | 2026-04-29 | Use Anthropic API (Claude Sonnet 4.6) with prompt caching and schema-validated structured output. `CompilerProvider` interface abstracts the backend for future migration. |
| [0003](0003-foundation-slice-1-ingestor-scope.md) | Foundation Slice 1 Ingestor Scope | Accepted | 2026-04-29 | Polymarket-only ingestion in Slice 1. `PlatformAdapter` interface designed for multi-platform extension. Kalshi added in Slice 2. |
| [0004](0004-semantic-graph-storage-backend.md) | Semantic Graph Storage Backend | Accepted | 2026-04-29 | PostgreSQL adjacency table in Slice 1 behind `GraphRepository` interface. Migrate to Neo4j when nodes exceed 10,000 or traversals exceed 3 hops. |
| [0005](0005-relation-detection-approach.md) | Relation Detection Approach | Accepted | 2026-04-29 | Hybrid two-stage: deterministic constraint rules (Stage 1) filter candidates; LLM semantic analysis with mandatory counterexample generation (Stage 2) classifies relations. |
| [0006](0006-payoff-friction-convention.md) | PayoffMatrix Friction Convention | Accepted | 2026-04-30 | `worst_case_payoff` is always stored post-friction. `DivergenceService` applies `_friction_cost()` exactly once; `SimulatorService` and `CourtService` read directly without re-applying. |

## Status values

- Proposed
- Accepted
- Superseded
- Deprecated

## Usage

Use Claude Code command: /decide

Examples:
- /decide Propose whether we should use SQLite or Postgres for this project.
- /decide Document the accepted decision to use FastAPI.
