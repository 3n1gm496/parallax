# ADR-0001: Foundation Slice 1 Opportunity Priority

Status: Accepted
Date: 2026-04-29

## Context

PARALLAX targets two structurally distinct arbitrage types in prediction markets:

1. **Intra-platform logical consistency** (Market Rebalancing): The sum of mutually exclusive
   outcome prices on a single platform deviates from $1. Documented at ~$40M profit on Polymarket
   alone (April 2024–April 2025). Does not require cross-platform ingestion or semantic equivalence.

2. **Cross-platform semantic equivalence**: Two markets on different platforms encode the same
   event at divergent prices. Requires the full compiler + semantic graph + equivalence proof
   pipeline. Generated only $95K of $39.5M total documented arbitrage in the same period.

Foundation Slice 1 must establish a working, audited proof pipeline with real data. The choice of
opportunity type determines what the slice must build and what can be validated immediately.

## Decision

Prioritize **intra-platform logical consistency** in Foundation Slice 1.

Target the `mutually_exclusive_mispricing` and `exhaustive_set_mispricing` opportunity types on
Polymarket: find sets of mutually exclusive outcome markets whose prices sum to less than
(1 - realistic friction). Build the Payoff Prover, audit log, and paper trading tracker around
this simpler proof case first.

Cross-platform semantic equivalence detection becomes the primary validation target in Slice 2.

## Alternatives considered

### Option A: Intra-platform logical consistency first (chosen)

Pros:
- No cross-platform data or semantic equivalence matching required
- 99.76% of documented arbitrage by value is this type
- Proof logic is deterministic (sum < 1 threshold), not LLM-dependent
- Validates the Payoff Prover and audit pipeline with the simplest-to-prove cases
- Single API, single data schema in Foundation Slice 1
- Failure modes are straightforward to classify in autopsy

Cons:
- Does not test the compiler or semantic graph (the most novel components)
- A naive sum-check script could also find these — PARALLAX must show it does more than that

### Option B: Cross-platform semantic equivalence first

Pros:
- Tests the most novel and defensible components immediately
- Directly validates the core PARALLAX thesis

Cons:
- Requires two-platform ingestion, auth, and schema normalization from day one
- Requires a working compiler before any opportunity can be found
- LLM relation detection has documented ~88% false positive rate without formal validation layers
- Higher compound complexity makes debugging harder in a first slice

### Option C: Both in parallel

Pros:
- Faster path to full vision

Cons:
- Scope overload for Foundation Slice 1
- Two unproven pipelines compounding each other's failure modes

## Consequences

Positive:
- Foundation Slice 1 is scoped, buildable, and immediately testable against documented real opportunities
- Payoff Prover and audit log validated before tackling harder semantic cases

Negative:
- Compiler and semantic graph are deferred as primary validation targets to Slice 2

Neutral:
- Architecture is unchanged — all nine modules still exist in the final design
- The Event Contract Compiler is still built in Slice 1 and run against intra-platform markets;
  it is simply not the primary gating dependency for the first proof

## Risks

- Intra-platform opportunities may be fully arbitraged by faster bots, making them hard to
  observe in paper trading. Acceptable: PARALLAX is validating the proof pipeline, not racing
  for execution. The autopsy classification is valuable regardless.
- Simplicity of intra-platform logic may cause the Foundation Slice to appear less novel than
  it is. Mitigate with clear documentation of what the slice proves about the architecture.

## Rollback / revisit plan

If intra-platform opportunities are too thin to validate the pipeline, or if the compiler
delivers strong early results ahead of schedule, accelerate cross-platform equivalence detection
into Slice 1 without architectural changes. The pipeline is designed for both.

## References

- Saguillo et al. (2025): "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"
  https://arxiv.org/html/2508.03474v1
- Bawa (2024): "Combinatorial Arbitrage in Prediction Markets: Why 62% of LLM-Detected Dependencies Fail"
  https://medium.com/@navnoorbawa/combinatorial-arbitrage-in-prediction-markets-why-62-of-llm-detected-dependencies-fail-to-26f614804e8d
- PARALLAX /idea analysis (2026-04-28)
- PARALLAX /research findings (2026-04-29)
