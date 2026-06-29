Implemented and committed approved plan.

- Commit: `d94fe4748c3c528098cec961b1543f6fcc9bc126`
- Branch: `feature/init-prompts-plan`
- Handoff written: `.omp/handoff/implementation-summary.md` uncommitted as required.

Committed files:

- `README.md`
- `init-prompts/README.md`
- `init-prompts/omp-repo-init.md`
- `tests/test_init_prompts.py`

Verification passed:

- `python -m pytest tests/test_init_prompts.py` â†’ `2 passed`
- `python -m pytest tests/test_harness_init.py tests/test_worktrees_loadout_sync.py` â†’ `4 passed`

Final uncommitted workflow state:

- `.omp/skill-usage.json` modified by required skill-load recording.
- `.omp/handoff/` and `.omp/worktree-flow/init-prompts-plan/` remain untracked workflow artifacts.
