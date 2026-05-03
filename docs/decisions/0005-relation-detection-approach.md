# ADR-0005: Relation Detection Approach

Status: Accepted
Date: 2026-04-29

## Context

The Semantic Market Graph requires detecting and classifying typed relations between markets
(equivalent, duplicate, subset, mutually_exclusive, etc.). Research documented a critical failure:

- LLM-only relation detection has approximately 88% false positive rate on real prediction market
  data (Bawa 2024: 1,576 LLM-flagged candidates, 13 confirmed logically dependent pairs).
- Combinatorial arbitrage generated only $95K of $39.5M total documented arbitrage — the failure
  was primarily execution feasibility after false detection, not execution speed.
- The Semantic Non-Fungibility paper (Gebele & Matthes 2025) demonstrates that semantic
  alignment requires joint analysis of natural-language descriptions, resolution semantics,
  and temporal scope — not embedding similarity alone.

The relation detector must produce evidence trails that the Trade Court can verify against
compiled contracts. Free-form LLM assertions about market equivalence are not verifiable.

## Decision

Use a **hybrid relation-analysis approach**:

**Structural screening** (fast, zero LLM cost, high precision):
- Sum check: does a candidate set of mutually exclusive markets sum to < 0.97?
  → candidates for `mutually_exclusive_mispricing` or `exhaustive_set_mispricing`
- Price inversion: does Market A YES price + Market B YES price < 0.97 where markets share
  a domain and temporal proximity? → candidates for `equivalent` or `subset`
- Same-platform grouping: markets in the same Polymarket group or condition set
  → candidates for `exhaustive` sets
- Cross-platform temporal proximity: same event domain, overlapping deadline windows
  → candidates for semantic relation analysis

**Semantic analysis** (for candidates that pass structural screening only):
- Compile both markets into structured contracts (via Event Contract Compiler)
- Compare `yes_conditions`, `no_conditions`, `exclusions`, `deadline`, `oracle`
- Classify relation type from the 13-type taxonomy
- Generate at least 2 independent counterexample scenarios (scenarios where markets resolve
  differently) — **mandatory for all `equivalent` and `subset` claims**
- Assign confidence score (calibrated against historical labeled pairs as data accumulates)

A relation claim is only emitted if structural screening passes AND semantic analysis produces a structured contract
comparison AND (for equivalence claims) counterexample generation fails to find a breaking
scenario after 2 attempts.

## Alternatives considered

### Option A: LLM-only detection

Pros:
- Simpler to implement
- Handles edge cases without explicit rule engineering
- Flexible to novel market formats

Cons:
- 88% documented false positive rate on real data
- LLMs hallucinate confidence; no structured evidence for the relation claim
- Trade Court cannot verify LLM reasoning against compiled contracts

### Option B: Deterministic constraint rules only

Pros:
- Fully auditable; zero hallucination risk; fast execution

Cons:
- Cannot detect semantic relations requiring natural language understanding
  (e.g., "Will X win?" vs "Will the Democratic nominee win?" are semantically related
  but structurally dissimilar)
- Limited to structural/numeric patterns
- Cannot detect `same_event_different_oracle` without NLU

### Option C: Hybrid — rules first, LLM second (chosen)

Pros:
- Dramatically reduces LLM candidate set (thousands -> dozens)
- LLM operates on pre-filtered, higher-quality candidates only
- Every relation claim has a structural plus semantic evidence trail
- Counterexample generation is mandatory — guards against the Semantic Equivalence Illusion
- Structural criteria are explicit and auditable

Cons:
- Structural rule set requires maintenance as market formats evolve
- Two-step pipeline adds latency vs single-pass LLM
- Structural screening may miss novel semantic relations not covered by rules

## Consequences

Positive:
- Lower false positive rate before candidates reach the Payoff Prover
- Every relation claim has structured contract evidence, not just a model assertion
- Trade Court can verify reasoning against contracts and counterexample records
- Mandatory counterexample generation prevents the Semantic Equivalence Illusion

Negative:
- Structural rules require maintenance
- Higher latency than single-pass LLM

Neutral:
- Detection approach is internal to `RelationDetector` module
- Downstream pipeline (Payoff Prover, Trade Court) does not change

## Risks

- Structural rules filter out valid candidates that LLM-only would catch.
  Monitor: autopsy `identity_error` rate. If >15% of autopsied false negatives trace to structural
  filtering, loosen structural criteria.
- LLM counterexample generation fails to surface real breaking scenarios.
  Mitigate: require 2 independent attempts; flag as `low_confidence_equivalence` if both fail
  to find a breaking scenario, rather than silently promoting to `equivalent`.
- Structural rules become stale as prediction market platforms evolve their naming and grouping
  conventions. Mitigate: rules are data-driven where possible (using platform-provided category
  and grouping fields); add monitoring for structural pass rate over time.

## Rollback / revisit plan

If autopsy data shows structural screening is filtering too aggressively: loosen numeric thresholds or add
rules to capture the missed patterns. If semantic LLM quality is insufficient: switch provider
per ADR-0002 or add calibrated prompting layers. If fine-tuning data accumulates: build a
calibrated classifier for semantic relation typing.

## References

- Bawa (2024): "Combinatorial Arbitrage in Prediction Markets: Why 62% of LLM-Detected
  Dependencies Fail" — https://medium.com/@navnoorbawa/combinatorial-arbitrage-in-prediction-markets-why-62-of-llm-detected-dependencies-fail-to-26f614804e8d
- Gebele & Matthes (2025): "Semantic Non-Fungibility and Violations of the Law of One Price
  in Prediction Markets" — https://arxiv.org/html/2601.01706v1
- Saguillo et al. (2025): "Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets"
  — https://arxiv.org/html/2508.03474v1
- PARALLAX /idea analysis (2026-04-28)
- PARALLAX /research findings (2026-04-29)
