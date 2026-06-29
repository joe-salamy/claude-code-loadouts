Implemented and committed the approved plan.

Commit: `26b4818 Implement plan`

What changed:

- Split `worktree-flow.py` into `worktree-flow-codex.py` and `worktree-flow-omp.py`.
- Codex defaults to `codex` / `.codex`; OMP defaults to `omp` / `.omp`.
- Mirrored the split under `loadouts/worktrees/.harness/scripts/`.
- Updated loadout docs and workflow tests.
- Wrote `.codex/handoff/implementation-summary.md` and left it untracked as required.

Verification passed:

- `python -m unittest tests.test_codex_worktree_flow` passed, 40 tests.
- `python .\.codex\scripts\worktree-flow-codex.py --help` passed.
- `python .\.codex\scripts\worktree-flow-omp.py --help` passed.
- `python -m py_compile ...` passed for all four script copies.

Final status is clean except for untracked `.codex/handoff/`.
