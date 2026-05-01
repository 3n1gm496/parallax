---
adr: "0006"
title: PayoffMatrix Friction Convention
status: Accepted
date: 2026-04-30
---

# ADR 0006 — PayoffMatrix Friction Convention

## Status

Accepted

## Context

`DivergenceService` computes arbitrage payoff and stores it in `PayoffMatrix.worst_case_payoff`. Downstream services (`SimulatorService`, `CourtService`) read `worst_case_payoff` to evaluate or simulate the opportunity. A latent double-friction bug was discovered during Slice 1 review: `DivergenceService` applied `_friction_cost()` and stored the post-friction value, but `SimulatorService` re-applied friction a second time, understating returns.

A clear convention is required so any service that touches `PayoffMatrix` knows whether `worst_case_payoff` is pre- or post-friction, and therefore whether it must (or must not) apply friction itself.

## Decision

`worst_case_payoff` in `PayoffMatrix` is **always stored post-friction**. Friction is applied **exactly once**, in `DivergenceService._friction_cost(total_cost)`. No other service applies friction to a value read from `PayoffMatrix`.

### EQUIVALENT relation payoff

```
total_cost    = buy_price + (1.0 - sell_price)   # capital tied up in both legs
gross         = sell_price - buy_price            # direction-neutral spread
friction      = _friction_cost(total_cost)
net           = gross - friction
worst_case_payoff = net                           # stored; both YES/NO scenarios identical
```

### MUTUALLY_EXCLUSIVE relation payoff

```
total_cost    = (1 - p_a) + (1 - p_b)           # capital deployed: cost of both NO legs
gross         = p_a + p_b - 1.0                 # sum of YES prices minus collateral payout
friction      = _friction_cost(total_cost)
net           = gross - friction
worst_case_payoff = net                          # stored; both resolution scenarios identical
```

`total_cost` is the sum of NO-leg prices, consistent with EQUIVALENT where
`total_cost = buy_price + (1 - sell_price)`. Both strategies compute friction
on actual capital deployed rather than collateral.


### Downstream read contract

```python
# SimulatorService — correct
simulated_pnl = matrix.worst_case_payoff        # post-friction, no re-application

# Wrong — never do this
simulated_pnl = matrix.worst_case_payoff - self._friction_cost(...)
```

## Consequences

- **Positive**: single source of truth for net payoff; downstream services are read-only and cannot diverge.
- **Positive**: direction-neutrality is guaranteed at write time; readers need not reason about YES/NO scenarios.
- **Negative**: callers adding new relation types must apply `_friction_cost` before storing or they silently violate the convention — no type-level enforcement exists today.
- **Mitigation**: enforce via code review and a `_validate_payoff_matrix` helper in `DivergenceService` that asserts `worst_case_payoff < gross` before storing.

## Compliance trigger

If a new relation type is added (Slice 2+), the author must verify that `worst_case_payoff` is computed post-friction in `DivergenceService` before any other service reads it.
