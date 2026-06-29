Implemented and committed the approved plan.

Commit: `cb2f747 Implement plan`

What changed:

- Added shared `.codex/scripts/worktree-flow.py`.
- Replaced Codex/OMP flow files with compatibility wrappers.
- Added workflow invariant checks for implementation, audit, and pre-integration.
- Synced loadout `.harness` script copies.
- Added drift-protection test.
- Updated worktree-flow docs.
- Wrote `.codex/handoff/implementation-summary.md` and left it untracked as required.

Verification passed:

- `python -m unittest tests.test_codex_worktree_flow`
- `python -m unittest tests.test_worktrees_loadout_sync`
- `git diff --check -- . ':!scratchpad.md' ':!.codex/handoff/**'`
- Combined focused unittest rerun: 54 tests passed

Final status is clean except for untracked `.codex/handoff/`.
