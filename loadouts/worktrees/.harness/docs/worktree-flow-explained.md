# <harness> Worktree Flow

`worktree-flow.py` is installed under the target repo's active harness directory. `save-plan.py` is the OMP helper that copies the latest approved OMP plan to `.omp/worktree-flow/<slug>/plan.md` and prints the `worktree-flow.py` command.

1. Creates a feature branch and Git worktree from `main`.
2. Runs <harness> implementation in that worktree.
3. Requires an implementation commit and handoff summary.
4. Runs a fresh <harness> audit pass.
5. Requires an audit summary.
6. Verifies no non-handoff changes are left pending.
7. Finishes through a temporary integration worktree.
8. Squash-merges by default and cleans up only after a successful merge.

## Quick Start

For OMP plan mode, first save the approved plan:

```powershell
python .\.omp\scripts\save-plan.py
```

It prints both `python` and `python3` commands; run the one appropriate for your shell.

Codex:

```powershell
python .\.codex\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex
```

Oh My Pi:

```powershell
python .\.omp\scripts\worktree-flow.py --plan .omp\worktree-flow\my-plan\plan.md --harness omp --harness-dir .omp
```

Common options:

```powershell
# Show Git/<harness> commands without running them
python .\.codex\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --dry-run

# Implement and audit, but stop before merging
python .\.codex\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --merge-mode stop

# Keep feature/integration worktrees after completion
python .\.codex\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --keep-worktrees

# Use a non-main base branch
python .\.codex\scripts\worktree-flow.py --plan docs\plans\my-plan.md --harness codex --harness-dir .codex --base develop
```

### Resume

Resume requires `--resume --worktree <feature-worktree>`. Optional resume-only arguments are `--branch`, `--run-id`, `--integration-worktree`, and `--integration-branch`.

## Required Skills

The script expects these skills to be installed in the target repo for the active harness:

- `implement-worktree`: implements the approved plan inside the script-created worktree.
- `audit-worktree`: audits the implementation in a fresh <harness> run and fixes confirmed issues.
- `merge-conflict-resolver`: resolves merge conflicts in the temporary integration worktree.

For this loadout, the source templates live under:

```text
loadouts/worktrees/.harness/skills/
```

When applying this loadout, `harness-init.ps1 -Harness <harness>` copies skills into:

```text
.<harness>/skills/
```

## Files Produced

Feature worktree:

```text
.<harness>/handoff/implementation-summary.md
.<harness>/handoff/implementation-final-response.md
.<harness>/handoff/audit-summary.md
.<harness>/handoff/audit-final-response.md
.<harness>/handoff/workflow-state.json
```

Conflict path only, inside the integration worktree:

```text
.<harness>/handoff/merge-conflict-context.md
.<harness>/handoff/conflict-resolution-summary.md
.<harness>/handoff/conflict-resolution-final-response.md
.<harness>/handoff/post-conflict-audit-summary.md
.<harness>/handoff/post-conflict-audit-final-response.md
```

The workflow plan is copied into the feature worktree at:

```text
.<harness>/worktree-flow/<slug>/plan.md
```

Before cleanup, the script archives handoff files and workflow state back into the primary checkout:

```text
.<harness>/worktree-flow/<run-id>/
```

This archive directory contains the copied handoff files and `workflow-state.json`; it is the durable record after the feature and integration worktrees are removed.

## Safety Notes

- The script does not push branches or open PRs.
- `--merge-mode stop` leaves the audited feature worktree ready for manual review.
- Default merge mode is `squash`, so implementation/audit commits are treated as execution detail.
- The primary checkout is updated only after a merge succeeds in a temporary integration worktree.
- Worktrees and branches are deleted only after successful integration unless `--keep-worktrees` is set.
- The implementation phase must create at least one commit and produce a diff from the base branch.
- The audit phase may be a no-op with no new commit when the worktree is clean outside `.<harness>/handoff/`.
- Tracked handoff artifacts produce a warning instead of a hard failure; non-handoff pending changes still fail integration checks.
