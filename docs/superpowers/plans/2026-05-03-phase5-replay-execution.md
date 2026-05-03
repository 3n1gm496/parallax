# Fase 5 — Replay-Based Execution Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `execution_model="replay_based"` — calibrate execution estimates using historical settled paper-position data instead of pure heuristics, and wire it into the pipeline when orderbook snapshots are unavailable.

**Architecture:** `ReplayStatisticsService` queries settled (`status="CLOSED"`) paper positions for the same opportunity type, computes `win_rate` and `mean_edge_capture`, and returns `None` when history is insufficient (< 3 settled positions). `SimulatorService.simulate_replay()` starts with the heuristic result, applies those stats, and returns a `SimulationResult` with `execution_model="replay_based"`. `CourtService.evaluate_with_replay()` follows the same pattern as `evaluate_with_snapshots()`. `PipelineRunner` routes to replay when `orderbook_enabled=False` and history is available, falling back to heuristic otherwise. The original `opportunity_candidates.risk_scores` and the `simulate()` / `evaluate()` heuristic path are unchanged.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (sync ORM), Pydantic v2, pytest.

---

### File Map

**Create:**
- `src/parallax/execution/replay_stats.py` — `ReplayStats` dataclass + `ReplayStatisticsService`
- `tests/unit/test_execution_replay_stats.py` — unit tests for `ReplayStatisticsService`
- `tests/unit/test_simulator_replay.py` — unit tests for `simulate_replay()` and `evaluate_with_replay()`

**Modify:**
- `src/parallax/simulator/service.py` — add `simulate_replay()` method
- `src/parallax/court/service.py` — add `evaluate_with_replay()` method
- `src/parallax/pipeline/runner.py` — route to replay path when appropriate
- `docs/STATUS.md` — document Fase 5

---

### Task 1: `ReplayStats` + `ReplayStatisticsService`

- [ ] Step 1: Write failing tests
- [ ] Step 2: Create replay_stats.py
- [ ] Step 3: Run tests
- [ ] Step 4: Run full suite
- [ ] Step 5: Commit

### Task 2: `SimulatorService.simulate_replay()`

- [ ] Step 1: Write failing tests
- [ ] Step 2: Add simulate_replay()
- [ ] Step 3: Run tests
- [ ] Step 4: Run full suite
- [ ] Step 5: Commit

### Task 3: `CourtService.evaluate_with_replay()`

- [ ] Step 1: Write failing test
- [ ] Step 2: Add evaluate_with_replay()
- [ ] Step 3: Run test
- [ ] Step 4: Run full suite
- [ ] Step 5: Commit

### Task 4: Wire PipelineRunner

- [ ] Step 1: Check existing test structure
- [ ] Step 2: Add import to runner.py
- [ ] Step 3: Replace else branch
- [ ] Step 4: Write tests
- [ ] Step 5: Run full suite
- [ ] Step 6: Commit

### Task 5: Final validation + STATUS.md

- [ ] Step 1: Run full suite
- [ ] Step 2: Run replay-specific tests
- [ ] Step 3: Update STATUS.md
- [ ] Step 4: Commit
