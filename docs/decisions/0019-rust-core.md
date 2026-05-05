# ADR-019: Deterministic Rust Core for Hot Path

## Status
Accepted

## Context
The Python-based orderbook and solver implementation introduced significant latency (GC pauses, GIL contention) during high-volatility events. To achieve sub-millisecond arbitrage detection, we need a deterministic execution path.

## Decision
We will implement the "Hot Path" (Orderbook depth maintenance and Arbitrage Solving) in Rust as a compiled Python extension module (`parallax_core`).

- **Orderbook**: Use `BTreeMap` for O(log N) price level access without heap allocations during updates.
- **Solver**: Pure mathematical functions with zero I/O.
- **Integration**: Use `PyO3` to expose the Rust objects to the Python `StreamScanner`.

## Consequences
- **Positive**: Sub-microsecond edge detection. Better concurrency (GIL released during heavy computation).
- **Negative**: Increased build complexity (requires `maturin` and a Rust toolchain).
- **Neutral**: Python remains the orchestrator for the "Cold Path" (Semantic Discovery).
