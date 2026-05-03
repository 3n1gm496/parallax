# Architecture Decision Records

This directory contains accepted design decisions for Parallax.

Use these ADRs as the architectural target layer, not as a guarantee that every subsystem is already fully activated. For current implementation truth, check [docs/STATUS.md](/home/administrator/tools/parallax/docs/STATUS.md:1).

## Index

| ADR | Title | Status | Date | Summary |
|---|---|---|---|---|
| [0001](0001-foundation-slice-1-opportunity-priority.md) | Foundation Slice 1 Opportunity Priority | Accepted | 2026-04-29 | Intra-platform logical consistency comes before broader semantic coverage. |
| [0002](0002-llm-provider-event-contract-compiler.md) | LLM Provider for Event Contract Compiler | Accepted | 2026-04-29 | Anthropic Claude Sonnet 4.6 with structured output and provider abstraction. |
| [0003](0003-foundation-slice-1-ingestor-scope.md) | Foundation Slice 1 Ingestor Scope | Accepted | 2026-04-29 | Adapter-based ingestion architecture; runtime has since evolved beyond Polymarket-only. |
| [0004](0004-semantic-graph-storage-backend.md) | Semantic Graph Storage Backend | Accepted | 2026-04-29 | PostgreSQL adjacency storage behind a graph repository abstraction. |
| [0005](0005-relation-detection-approach.md) | Relation Detection Approach | Accepted | 2026-04-29 | Structural screening plus semantic confirmation. |
| [0006](0006-payoff-friction-convention.md) | PayoffMatrix Friction Convention | Accepted | 2026-04-30 | Friction is applied once upstream and read directly downstream. |

## How To Read These Correctly

- ADRs explain why the architecture should look a certain way
- `STATUS.md` says what is actually verified today
- `RUNTIME.md` says what the live contract is supposed to be
- if an ADR and the runtime diverge, fix the code or update the docs explicitly instead of silently assuming the ADR already won

## Known Historical Drift

- older ADRs and slice plans sometimes speak in terms of early Slice 1 or Slice 2 assumptions
- older ADR names are kept for traceability; do not read their phase labels as the current delivery plan
- the live runtime has since moved to:
  - native Kalshi ingestion instead of a provider-layer runtime path
  - richer relation evidence and court outputs
  - paper positions, settlement, autopsy, and ops views

When you need current truth, start from `STATUS.md`, then use the ADRs only for rationale and long-lived constraints.

## Status values

- Proposed
- Accepted
- Superseded
- Deprecated

## Reading order

1. Read the ADR index here.
2. Read [docs/STATUS.md](/home/administrator/tools/parallax/docs/STATUS.md:1) for live maturity.
3. Open the ADRs relevant to the subsystem you are changing.
