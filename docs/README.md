# Documentation Map

This directory is the maintained documentation layer for the current repo state.

## Read In This Order

1. [STATUS.md](/home/administrator/tools/parallax/docs/STATUS.md:1)
2. [RUNTIME.md](/home/administrator/tools/parallax/docs/RUNTIME.md:1)
3. [ARCHITECTURE.md](/home/administrator/tools/parallax/docs/ARCHITECTURE.md:1)
4. [RUNBOOK.md](/home/administrator/tools/parallax/docs/RUNBOOK.md:1)
5. [VENDOR_HANDOFF.md](/home/administrator/tools/parallax/docs/VENDOR_HANDOFF.md:1)
6. [REPOSITORY.md](/home/administrator/tools/parallax/docs/REPOSITORY.md:1)
7. [decisions/README.md](/home/administrator/tools/parallax/docs/decisions/README.md:1)

## Contract Of Each File

- `STATUS.md`: what is verified now in this repo, including known blockers and non-proven claims
- `RUNTIME.md`: backend and UI contract for the active implementation
- `ARCHITECTURE.md`: concise authority map, storage boundaries, and subsystem flow
- `RUNBOOK.md`: how to prove lifecycle and real-data operation without hand-waving
- `VENDOR_HANDOFF.md`: the shortest third-party bootstrap and trial path
- `REPOSITORY.md`: source tree and ownership map
- `decisions/`: accepted architectural decisions and long-lived tradeoffs

## What Is Not The Current Contract

- `docs/superpowers/plans/` contains historical implementation plans and exploration notes
- `docs/superpowers/plans/README.md` explains how to read those historical files safely
- review workspaces and old plans are useful context, but they are not the truth source for the live repo
- if a document is not linked from here or from the top-level `README.md`, treat it as secondary context until verified otherwise

## Maintenance Rule

If runtime behavior, architecture boundaries, or operational proof criteria change, update `STATUS.md`, `RUNTIME.md`, `ARCHITECTURE.md`, and `RUNBOOK.md` in the same change rather than leaving them to drift.
