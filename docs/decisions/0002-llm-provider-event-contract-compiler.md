# ADR-0002: LLM Provider for Event Contract Compiler

Status: Accepted
Date: 2026-04-29

## Context

The Event Contract Compiler is PARALLAX's most novel component. It parses natural language
prediction market descriptions into structured formal contracts:
`yes_conditions`, `no_conditions`, `exclusions`, `ambiguity_terms`, `counterexamples`,
`compiler_confidence`.

This requires a frontier-class LLM with reliable structured output. The provider choice affects:
output quality, latency, cost, privacy, vendor dependency, and future fine-tuning capability.

Research finding: LLM zero-shot relation detection has approximately 88% false positive rate on
real prediction market data. The compiler must produce schema-validated structured output that
feeds downstream formal validation — not free-form summaries. Counterexample generation is
mandatory for all equivalence and subset claims.

Market descriptions ingested by the compiler are publicly available data. No position data,
credentials, or private information is sent to the LLM provider.

## Decision

Use the **Anthropic API (Claude Sonnet 4.6)** with prompt caching and schema-validated
structured output (tool use / JSON mode) in Foundation Slice 1.

No fine-tuning in Slice 1. The compiler backend must be abstracted behind a `CompilerProvider`
interface so the LLM can be swapped without changing compiler business logic.

## Alternatives considered

### Option A: Anthropic API — Claude Sonnet 4.6 (chosen)

Pros:
- Best-in-class structured output reliability via tool use and JSON mode
- Prompt caching reduces cost significantly for repeated compilation of similar market formats
- Extended thinking mode available for complex ambiguity analysis cases
- Claude's instruction-following for schema-constrained output is excellent
- Privacy: market text is publicly available — external API is acceptable
- Consistency with the development environment (Claude Code)

Cons:
- External API dependency: latency, availability, per-token cost
- No fine-tuning capability (inference-only at standard tier)
- Data sent to Anthropic servers (acceptable for public market text)

### Option B: OpenAI API — GPT-4o or GPT-4.1

Pros:
- Strong structured output with JSON schema enforcement
- Large ecosystem, well-documented function calling

Cons:
- No prompt caching equivalent to Anthropic's — higher cost at scale
- No strong reason to prefer over Anthropic for this use case
- Additional vendor relationship

### Option C: Local LLM (Ollama + Llama 3.3 70B or similar)

Pros:
- No data leaves the system — maximum privacy
- No per-token cost after hardware
- No rate limits
- Can be fine-tuned on calibration data once available

Cons:
- Requires GPU hardware (12–24GB VRAM minimum for a capable model)
- 30–120 second latency per compilation on consumer hardware
- Structured output quality materially worse than frontier models for complex schema extraction
- Not viable for Foundation Slice 1 without dedicated GPU infrastructure

### Option D: Hybrid (Anthropic for initial compilation, local for bulk re-runs)

Pros:
- Quality for initial compilation; privacy and cost for bulk operations

Cons:
- Two LLM stacks, two prompting conventions
- Premature optimization for Foundation Slice 1

## Consequences

Positive:
- Best-quality structured output from day one
- No GPU infrastructure required in Foundation Slice 1
- Prompt caching reduces cost for repeated compilations
- Clean abstraction allows future migration

Negative:
- Per-token cost accumulates with scale
- Anthropic API availability is a pipeline dependency

Neutral:
- The `CompilerProvider` interface abstracts the LLM backend completely
- Migration to any provider is a new implementation class, not a rewrite

## Risks

- Anthropic API outage interrupts the compilation pipeline. Mitigate: cache all compiled
  contracts persistently; re-run only on new or updated markets.
- Schema validation violations occur intermittently. Mitigate: enforce schema validation with
  structured retry logic; log all violations for prompt improvement.
- Calibration shows systematic compiler errors that prompt engineering cannot fix.
  Revisit trigger: switch to fine-tunable provider (OpenAI fine-tuning or local model).

## Rollback / revisit plan

Revisit this decision when:
- Calibration error rate exceeds 20% after 200 labeled historical examples
- Monthly API cost exceeds $200
- A compelling local model with equivalent structured output quality becomes available

Migration path: implement `LocalCompilerProvider` or `OpenAICompilerProvider` behind the
same `CompilerProvider` interface. No business logic changes required.

## References

- Bawa (2024): "Combinatorial Arbitrage in Prediction Markets"
  https://medium.com/@navnoorbawa/combinatorial-arbitrage-in-prediction-markets-why-62-of-llm-detected-dependencies-fail-to-26f614804e8d
- Anthropic prompt caching documentation: https://docs.anthropic.com
- PARALLAX /idea analysis (2026-04-28)
- PARALLAX /research findings (2026-04-29)
