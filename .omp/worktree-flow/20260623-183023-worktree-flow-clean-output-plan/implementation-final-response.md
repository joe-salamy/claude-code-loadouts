Implemented and committed.

- Commit: `750886c98e3fb481e43f97ad0715377d9a40b0fd`
- Branch: `feature/worktree-flow-clean-output-plan`
- Updated:
  - `.omp/scripts/worktree-flow.py`
  - `loadouts/worktrees/.harness/scripts/worktree-flow.py`
  - `.omp/skill-usage.json`

Behavior:

- Normal subprocess command echoing is quiet by default.
- `--verbose` restores `+ (<cwd>) <command>` traces.
- `--dry-run` still prints command traces.

Verification passed:

- Script sync diff: no output / exit 0.
- `py_compile` for both scripts.
- `--help` for both scripts includes `--verbose`.
- Missing-plan normal run emits no `+ (` trace.
- Missing-plan verbose run emits `+ (` trace.
- Dry-run emits `+ (` traces.

Handoff written:

- `.omp/handoff/implementation-summary.md`

Final status only has workflow artifacts untracked:

- `.omp/handoff/`
- `.omp/worktree-flow/worktree-flow-clean-output-plan/`
