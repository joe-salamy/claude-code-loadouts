Implemented and committed.

## Commit

- `cc915c129733bab02016072ba96807863249ea1e`
- Branch: `feature/worktree-usage-stats-logging`
- Worktree: `/mnt/c/Users/joesa/code/harness-loadouts-worktree-usage-stats-logging`

## Changed files committed

- `.omp/scripts/worktree-flow.py`
- `loadouts/worktrees/.harness/scripts/worktree-flow.py`
- `loadouts/worktrees/.opencode/scripts/worktree-flow.py`
- `loadouts/worktrees/.harness/docs/worktree-flow-explained.md`
- `tests/test_codex_worktree_flow.py`

## Behavior added

- Adds numeric-only OMP usage telemetry artifacts:
  - `.<harness>/handoff/usage-events.jsonl`
  - `.<harness>/handoff/usage-summary.json`
  - `.<harness>/handoff/usage-sources.json`
- Writes usage artifacts during harness phase execution, including failed/timed-out phases before raising.
- Splits phase telemetry across:
  - `implementation`
  - `audit`
  - `conflict_resolution`
  - `post_conflict_audit`
- Aggregates allowed numeric/config metadata only:
  - token/cost totals
  - nested response usage
  - timing values
  - context token snapshots
  - model/provider/API/stop-reason counts
  - tool call/result counts
  - safe numeric tool details
  - event/custom event counts
- Redacts usage source provenance:
  - basename-only `file_name`
  - SHA-256 path hash prefix
  - no absolute session paths or cwd values
- Keeps usage files as handoff/worktree-flow artifacts, excluded from implementation/audit/integration commits by existing handoff handling.
- Synced `.omp`, `.harness`, and `.opencode` workflow script copies.
- Updated worktrees loadout docs to list usage files and state the privacy boundary.

## Verification

Passed:

- `python3 -m py_compile .omp/scripts/worktree-flow.py`
- Targeted telemetry smoke checks:
  - non-OMP unavailable event and privacy booleans
  - OMP assistant token/cost/context aggregation
  - OMP tool aggregation and tool argument/display redaction
- Tester-authored focused tests:
  - 4 telemetry artifact/privacy/archive/failure tests passed
  - 8 updated `harness_exec` callsite/behavior tests passed
- Plan-required focused suite:
  - `python3 -m unittest tests.test_codex_worktree_flow tests.test_worktrees_loadout_sync`
  - Result: `OK`, 74 tests
- Updater tests:
  - `python3 -m unittest tests.test_harness_init`
  - Result: `OK (skipped=14)`
- CLI smoke:
  - `python3 .omp/scripts/worktree-flow.py --help`
  - Result: exited 0 and printed parser help

## Skipped / blocked

- `python` is not installed on PATH in this WSL environment, so `python ...` commands were run with `python3`.
- `pwsh` is not installed on PATH:
  - `command -v pwsh` exited 1.
- Therefore these rollout commands could not be run locally:
  - `pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees -WhatIf`
  - `pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees`
- Target repositories were not updated because the approved updater requires PowerShell. Re-run the updater WhatIf/apply commands in an environment with `pwsh`.

## Handoff summary

Wrote required untracked artifact:

- `.omp/handoff/implementation-summary.md`

## Final status

Tracked changes are clean after commit.

Remaining untracked workflow artifacts only:

- `.omp/handoff/`
- `.omp/worktree-flow/20260709-104914-worktree-usage-stats-logging/`
