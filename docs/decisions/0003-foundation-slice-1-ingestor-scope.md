# ADR-0003: Foundation Slice 1 Ingestor Scope

Status: Accepted
Date: 2026-04-29

## Context

PARALLAX requires market data ingestion from prediction market platforms. Research confirmed
the following capabilities as of April 2026:

- **Polymarket:** Three public APIs (Gamma, CLOB, Data); no auth for market data reads;
  WebSocket for real-time streaming; historical prices publicly accessible; 9,000 req/10s (CLOB),
  4,000 req/10s (Gamma), 60 req/min (public endpoints); Python SDK available.
- **Kalshi:** Tiered API (Basic free tier, Advanced/Premier by application); auth required for
  trading; WebSocket read-only; historical data depth unclear without Advanced tier.
- **Manifold:** Free API, no auth for reads, 500 req/min, play money only.
- **Metaculus:** Research partner access; limited public API.

Foundation Slice 1 targets intra-platform logical consistency (ADR-0001), which does not require
cross-platform ingestion. However, the ingestor architecture must support multi-platform extension
in Slice 2 without redesign.

## Decision

**Polymarket-only ingestion in Foundation Slice 1**, implemented behind a `PlatformAdapter`
interface designed for multi-platform extension from day one.

Manifold is optional as a low-stakes testing environment for the compiler (no financial exposure,
high market volume). It is not a required Slice 1 deliverable.

The `PlatformAdapter` interface must be finalized before Kalshi integration begins in Slice 2,
reviewed against the Kalshi API schema even though Kalshi is not implemented.

## Alternatives considered

### Option A: Polymarket-only (chosen)

Pros:
- Single API, single data schema, no auth complexity for reads
- $40M in documented intra-platform arbitrage validates the target platform
- WebSocket available for real-time feeds
- Fastest path to a working ingestion + proof pipeline
- Polymarket is the highest-liquidity prediction market as of 2026

Cons:
- Delays cross-platform equivalence detection to Slice 2
- PlatformAdapter interface correctness not validated until Slice 2 adds Kalshi

### Option B: Polymarket + Kalshi from day one

Pros:
- Enables cross-platform detection immediately
- Validates the adapter abstraction with two real implementations

Cons:
- Kalshi API auth complexity in Slice 1
- Kalshi historical data depth unclear without Advanced tier (unknown cost)
- Two data schemas, two auth models, two rate-limit systems to manage
- Adds estimated 1–2 weeks of integration before semantic work can begin

### Option C: Manifold for prototyping + Polymarket for production

Pros:
- Manifold: no financial risk, generous rate limits, large market volume for compiler testing

Cons:
- Play-money only — execution simulation irrelevant
- Market description quality lower than Polymarket/Kalshi
- Adds a third data schema to the adapter

## Consequences

Positive:
- Focused scope; one API implementation delivers a working pipeline
- No auth complexity in Slice 1
- Clean interface design enables Kalshi addition in Slice 2 as an implementation-only change

Negative:
- No cross-platform comparison in Slice 1
- PlatformAdapter design may need adjustment when Kalshi is added

Neutral:
- Kalshi integration is well-scoped for Slice 2: implement the adapter, add auth, verify schema

## Risks

- Polymarket API schema changes or rate limiting interrupt the pipeline. Mitigate: cache market
  data locally; the pipeline must not depend on real-time API availability for historical analysis.
- PlatformAdapter interface designed for Polymarket doesn't generalize to Kalshi's schema.
  Mitigate: review Kalshi's market schema before finalizing the interface, even if Kalshi is
  not implemented in Slice 1.
- Polymarket reduces public API access or introduces auth requirements. No current indication
  of this, but monitor changelog.

## Rollback / revisit plan

Add Kalshi adapter in Slice 2 by implementing `KalshiPlatformAdapter` behind the
`PlatformAdapter` interface. Architecture does not change. If Kalshi Advanced tier is required
for useful historical data, evaluate cost against research value before subscribing.

Add Manifold adapter any time as a compiler testing harness — does not require Slice 2.

## References

- Polymarket API documentation: https://docs.polymarket.com
- Polymarket US API Guide 2026: https://agentbets.ai/guides/polymarket-us-api-guide/
- Kalshi API documentation: https://docs.kalshi.com
- Saguillo et al. (2025): https://arxiv.org/html/2508.03474v1
- PARALLAX /research findings (2026-04-29)
