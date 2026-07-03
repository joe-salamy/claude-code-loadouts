# Headless Init Prompts Implementation Summary

## Plan path

`.omp/worktree-flow/20260703-104422-headless-init-prompts/plan.md`

## Worktree path

`C:/Users/joesa/Code/harness-loadouts-headless-init-prompts`

## Branch name

`feature/headless-init-prompts`

## Commit

`b10222ab4472d10e57f877e32b3d2e1e93f3a52c`

## Changed files

- `harness-init.ps1`
- `README.md`
- `tests/test_harness_init.py`

## Behavior changes

- Added `-InitPrompt`, `-Headless`, and `-Model` parameters to `harness-init.ps1`.
- Added standalone headless init-prompt mode before loadout validation:
  - `-InitPrompt` without `-Headless` exits 1 with `Error: -Headless is required when -InitPrompt is used.`
  - `-Headless` without `-InitPrompt` exits 1 with `Error: -Headless requires -InitPrompt <name>.`
  - `-PlanChanges` with `-InitPrompt` exits 1 with `Error: -PlanChanges cannot be used with -InitPrompt.`
  - `-InitPrompt` mode validates and resolves `-Target`, then exits after the headless OMP run; it does not require `-Loadout` or `-Harness`.
- Added init prompt resolution from the repository root `init-prompts/` directory:
  - Blank names throw `Init prompt name is required.`
  - Names containing `/`, `\`, or `..` throw `Init prompt name must be a file name under init-prompts.`
  - Names may be passed with or without `.md`.
  - Missing files throw `Init prompt '<name>' not found in '<init-prompts path>'.`
- Added runtime prompt augmentation without editing source prompt templates:
  - Appends the headless initialization execution rules.
  - Instructs the agent to treat the prompt as an end-state checklist.
  - Instructs the agent to write a timestamped follow-up report under `.omp/init/reports/` named `yyyyMMdd-HHmmss-init-report.md`.
- Added headless OMP invocation in `harness-init.ps1`:
  - Creates target `.omp/init/` before invoking OMP.
  - Writes the augmented temporary prompt to `.omp/init/<prompt-stem>-headless-prompt.md` using UTF-8 without BOM.
  - Resolves `omp` through PowerShell command lookup and runs it through `System.Diagnostics.Process` with captured stdout/stderr.
  - Uses OMP args `-p --no-session --auto-approve --approval-mode yolo`, optionally `--model <model>`, then `@<prompt-file>`.
  - Sets the process working directory to the resolved target repository.
  - Writes stdout to `.omp/init/<prompt-stem>-headless-output.md`.
  - Writes stderr to `.omp/init/<prompt-stem>-headless-stderr.txt` when stderr is non-empty.
  - On non-zero exit, prints captured stdout/stderr and exits with OMP's exit code after printing `Error: Headless init prompt '<prompt-stem>' failed with exit code <code>.`
  - On success, deletes the temporary prompt file, prints stdout, and prints `Headless init prompt '<prompt-stem>' completed. Output: .omp/init/<prompt-stem>-headless-output.md`.
- Updated `README.md` `## Init Prompts` section with the headless OMP command example and artifact/report paths.
- Added focused fake-OMP tests in `tests/test_harness_init.py` for:
  - Successful headless invocation without `-Loadout` or `-Harness`.
  - Exact OMP argument shape and target cwd.
  - Runtime prompt augmentation content.
  - Stdout artifact creation and temporary prompt deletion.
  - Optional `-Model` placement immediately before the `@<prompt-file>` arg.
  - Required `-Headless`/`-InitPrompt` pairing errors.
  - Path traversal rejection for init prompt names.

## Tests/checks run

- `python -m pytest tests/test_harness_init.py`
  - Result: `13 passed in 13.10s` after fixing Windows command resolution for the fake `omp.cmd`.
- `python -m pytest tests/test_harness_init.py tests/test_init_prompts.py`
  - Result: `14 passed in 13.08s`.
- `python -m pytest tests/test_worktrees_loadout_sync.py tests/test_codex_worktree_flow.py::SharedHarnessSelectionTests::test_omp_harness_exec_uses_print_mode_prompt_file_and_writes_stdout`
  - Result: `2 passed in 0.17s`.

## Skipped checks

- Manual real-OMP smoke command was not run. The plan marks it conditional on a real `omp` executable and a target that can be modified; focused fake-OMP tests cover command shape, cwd, prompt augmentation, output artifacts, and success cleanup without mutating an external repository.
- No project-wide test suite beyond the plan's focused commands was run.

## Implementation decisions and tradeoffs

- `harness-init.ps1` resolves `omp` with `Get-Command -Name "omp" -CommandType Application` before starting `System.Diagnostics.Process`. This preserves the requested command semantics while making Windows PATH/PATHEXT resolution testable with `omp.cmd`; direct `ProcessStartInfo.FileName = "omp"` reached the real `omp.exe` instead of the fake command during tests.
- The headless mode validates `-Target` before resolving or invoking the prompt, so invalid targets keep the existing user-facing target error shape.
- The temporary prompt file is deleted only on successful OMP exit. On failure it is preserved alongside stdout/stderr artifacts to aid debugging.
- No `.omp/scripts/` files were changed, so no exported opencode loadout script copy was needed.

## Assumptions, blockers, residual risks, follow-up work

- Assumption: OMP supports the copied `-p --no-session --auto-approve --approval-mode yolo [--model <model>] @<prompt-file>` invocation in normal user environments.
- Assumption: Prompt names are intended to be plain file names under root `init-prompts/`, not nested paths.
- Residual risk: The fake-OMP tests validate process invocation and artifacts, but they do not validate a real OMP model run or the downstream agent-created timestamped report.
- Blockers: none.
- Follow-up work: none required by the approved plan.
