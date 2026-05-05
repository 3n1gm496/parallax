# ADR-020: Stateful Hedging with Hedge Intents

## Status
Accepted

## Context
Partial fills during basket execution create directional risk. The original implementation used asynchronous "fire-and-forget" tasks to unwind these positions. This approach was vulnerable to process crashes, which would leave the system with unhedged (naked) risk.

## Decision
We will implement a persistent state machine for risk mitigation:
- **Intent Logging**: Every required hedge is recorded in the `hedge_intents` table *before* the execution client is called.
- **Atomic Updates**: The status of the hedge is updated (Completed/Failed) only after the venue confirms the order.
- **Recovery Worker**: A background process scans for `pending` or `failed` intents on startup and attempts to close the risk.

## Consequences
- **Positive**: High operational resilience. Guaranteed audit trail for every emergency exit.
- **Negative**: Slight increase in latency (one DB write before hedging), mitigated by using a fast SSD-backed Postgres.
