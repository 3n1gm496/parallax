# Parallax System Architecture

Parallax is engineered as a **Hybrid Arbitrage Engine** that balances the non-deterministic nature of semantic reasoning with the hard requirements of HFT execution.

## 1. Vision: The "Omega" Reality Engine

PARALLAX is not merely an "opportunity feed"; it is a governed chain of truth designed to ensure that every trade is backed by a verifiable proof:

`event reality -> identity authority -> relation proof -> payoff proof -> execution realism -> trade court -> certificate -> paper position -> autopsy -> calibration`

### Non-Negotiable Principles
- **No proof, no bet**: Every candidate must have a valid `TradeProofCertificate`.
- **No execution realism, no edge**: Simulated PnL must survive conservative friction models.
- **Identity before proof**: Semantic mapping is only tradeable if identity status is `verified`.
- **Autopsy before learning**: Every position (even paper ones) must be closed with an autopsy for calibration.

## 2. The "Hot/Cold Path" Split

The system is split into two asynchronous loops to maintain ultra-low latency while performing complex reasoning.

### The Cold Path (Discovery & Reasoning)
- **Ingestion**: Polls and streams raw market data from Polymarket and Kalshi.
- **Normalization**: Uses LLMs (Anthropic Claude) to transform natural language into structured schemas.
- **Identity v3**: Maps disparate markets into unified `IdentityClusters` with strict authority.
- **Graph Reasoning**: Persists relationships (Equivalent, Inverse, Subset) into Neo4j.

### The Hot Path (Fast Execution)
- **L2 Orderbook**: A deterministic Rust engine (`parallax_core`) that maintains market depth.
- **Micro-Solver**: Scans for executable edges in sub-microsecond time.
- **HotCache**: A tiered memory system (L1 Dict / L2 Shared Memory) providing pre-compiled arbitrage sets.

## 3. Safety: The Proof Pipeline

We enforce a strict data provenance chain before any capital is at risk:

1.  **Identity v3**: Confirms two markets refer to the same event reality.
2.  **Logical Relation**: Defines the mathematical arbitrage thesis.
3.  **Trade Proof**: A JSON bundle containing embeddings, reasoning, and correlation evidence.
4.  **Certificate**: A signed database record authorizing the execution manager.

## 4. Risk Management & Stateful Hedging

- **Unwind Engine**: Automatically detects and manages partial fills to ensure delta-neutrality.
- **Hedge Intents**: Every emergency exit is recorded for stateful recovery across system restarts.
- **Complexity Breaker**: The MILP solver is capped at 5,000 states to prevent O(2^N) hangs.

## 5. Technical Stack

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0.
- **Core**: Rust (PyO3).
- **Data**: PostgreSQL (Audit), Neo4j (Graph), Aerospike (L3 Cache).
- **Frontend**: Vite, React (War Room Dashboard).

## 6. Implementation Status (Phase Map)

Parallax is currently in **Phase 5 (War Room Omega)**. While the architecture is materially hardened, full "Omega" acceptance requires real-data proof validation across all venues.

---
*Significant architectural decisions are documented in `docs/decisions/`.*
