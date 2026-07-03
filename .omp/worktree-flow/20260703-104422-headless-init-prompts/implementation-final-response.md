Implemented and committed the approved headless init-prompt plan.

Changed files:
- `harness-init.ps1`
  - Added `-InitPrompt`, `-Headless`, `-Model`.
  - Added headless OMP init mode before loadout validation.
  - Resolves prompt names from root `init-prompts/`.
  - Runtime-augments prompts with idempotent checklist and `.omp/init/reports/` report instructions.
  - Invokes OMP headlessly with captured stdout/stderr using `System.Diagnostics.Process`.
  - Writes artifacts under target `.omp/init/`.
  - Deletes the temporary headless prompt file on success.
  - Preserves stdout/stderr artifacts on failure.
- `README.md`
  - Documented the new command:
    ```powershell
    .\harness-init.ps1 -Target C:\path\to\repo -InitPrompt omp-repo-init -Headless
    ```
  - Documented `.omp/init/` artifacts and `.omp/init/reports/` follow-up reports.
- `tests/test_harness_init.py`
  - Added fake-OMP helper.
  - Added coverage for success, model option ordering, validation errors, path traversal rejection, artifact creation, prompt augmentation, target cwd, and no `-Loadout`/`-Harness` requirement.

Commit:
- `b10222ab4472d10e57f877e32b3d2e1e93f3a52c`
- Message: `Implement plan`

Verification:
- `python -m pytest tests/test_harness_init.py`
  - `13 passed in 13.10s`
- `python -m pytest tests/test_harness_init.py tests/test_init_prompts.py`
  - `14 passed in 13.08s`
- `python -m pytest tests/test_worktrees_loadout_sync.py tests/test_codex_worktree_flow.py::SharedHarnessSelectionTests::test_omp_harness_exec_uses_print_mode_prompt_file_and_writes_stdout`
  - `2 passed in 0.17s`

Handoff:
- Wrote `.omp/handoff/implementation-summary.md`.
- Left it untracked as required.

Final status:
- Implementation changes committed.
- Only workflow artifacts remain untracked:
  - `.omp/handoff/`
  - `.omp/worktree-flow/20260703-104422-headless-init-prompts/`

Blockers:
- None.
