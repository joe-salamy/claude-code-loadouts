# Headless Init Prompts

## Context

Add a repo initialization feature that runs an existing `init-prompts/<name>.md` prompt against a target repository without interactive intervention. The user selected extending `harness-init.ps1` instead of adding a new script, and selected `.omp/init/reports/` as the hard-coded follow-up report directory. Current repository state confirms there is no dedicated user-facing script for this; `harness-init.ps1` only applies loadouts, while `.omp/scripts/worktree-flow.py` already contains the OMP headless command shape to copy.

## Approach

1. Add a standalone headless init-prompt mode to `harness-init.ps1`.
   - Edit the param block at `harness-init.ps1` lines 14-23 to add exactly:
     - `[string]$InitPrompt,`
     - `[switch]$Headless,`
     - `[string]$Model`
   - Keep existing loadout parameters and behavior unchanged for calls that do not pass `-InitPrompt`.
   - New supported invocation: `./harness-init.ps1 -Target C:\path\to\repo -InitPrompt omp-repo-init -Headless`.
   - Optional model invocation: `./harness-init.ps1 -Target C:\path\to\repo -InitPrompt omp-repo-init -Headless -Model <model-name>`.
   - If `-InitPrompt` is passed without `-Headless`, print `Error: -Headless is required when -InitPrompt is used.` to stdout in red and `exit 1`.
   - If `-Headless` is passed without `-InitPrompt`, print `Error: -Headless requires -InitPrompt <name>.` to stdout in red and `exit 1`.
   - If `-InitPrompt` is present, do not require `-Loadout` or `-Harness`; the mode runs only the named prompt against `-Target` and exits after OMP finishes. This makes “pass repo and init prompt name” work without forcing a loadout apply.

2. Resolve prompt names from the existing source-template directory.
   - Add `$InitPromptsDir = Join-Path $ScriptRoot "init-prompts"` near the existing `$LoadoutsDir` assignment.
   - Add function `Resolve-InitPromptPath` before the main execution checks. Exact behavior:
     - Parameter: `[string]$Name`.
     - Reject blank/whitespace names with `throw "Init prompt name is required."`.
     - Reject names containing `/`, `\`, or `..` with `throw "Init prompt name must be a file name under init-prompts."`.
     - If `$Name` ends with `.md`, use it as the file name; otherwise append `.md`.
     - Resolve the candidate as `Join-Path $InitPromptsDir $fileName`.
     - If the file does not exist as a leaf, throw `Init prompt '<Name>' not found in '<InitPromptsDir>'.`.
     - Return the candidate path.
   - Existing prompt file read this session: `init-prompts/omp-repo-init.md` exists and is the expected default prompt name.

3. Build runtime-only OMP instructions into every headless prompt run.
   - Add function `New-HeadlessInitPrompt` before main execution. Exact signature: `function New-HeadlessInitPrompt { param([string]$PromptPath, [string]$Target) ... }`.
   - Read the prompt with `[System.IO.File]::ReadAllText($PromptPath)`.
   - Append two blank lines plus this exact markdown block to the prompt text:

     ```markdown
     ## Headless initialization execution rules

     The repository may already satisfy some or all items in this initialization prompt. Treat the prompt as an end-state checklist: inspect first, skip work that is already complete, and make only the changes needed to ensure every requested item is complete by the end of the run.

     Before your final response, create `.omp/init/reports/` in this repository if needed and write a timestamped Markdown report there named `yyyyMMdd-HHmmss-init-report.md`. The report must summarize what you changed, which verification commands ran, which checks could not run, and any follow-up needed. Keep the final chat response brief and mention the report path.
     ```

   - Do not edit `init-prompts/omp-repo-init.md` to bake in these runtime instructions; append them at runtime so all init prompts get the same idempotent-checklist and headless-report requirements.
   - No additional conflict policy is needed for the report file because the timestamped name prevents overwriting normal runs.

4. Invoke OMP headlessly from `harness-init.ps1`, copying the proven worktree command semantics.
   - Add function `Invoke-OmpHeadlessInitPrompt` before main execution. Exact signature: `function Invoke-OmpHeadlessInitPrompt { param([string]$Target, [string]$PromptPath, [string]$Model) ... }`.
   - Create `.omp/init/` in the target before invoking OMP.
   - Write the augmented prompt to `.omp/init/<prompt-stem>-headless-prompt.md` in the target repository using UTF-8 without BOM.
   - Build the command exactly as:
     - executable: `omp`
     - args: `-p`, `--no-session`, `--auto-approve`, `--approval-mode`, `yolo`, optionally `--model`, `$Model`, then `@<prompt-file>`.
   - Run the command with current directory set to the resolved target repository.
   - Capture stdout and stderr into variables using `System.Diagnostics.Process` rather than streaming only to console, so tests can fake/inspect the command output without relying on an interactive terminal.
   - Write stdout to `.omp/init/<prompt-stem>-headless-output.md` after the command exits.
   - If stderr is non-empty, write it to `.omp/init/<prompt-stem>-headless-stderr.txt`.
   - If OMP exits non-zero, print stdout and stderr to the console, print `Error: Headless init prompt '<prompt-name>' failed with exit code <code>.` in red, and `exit <code>`.
   - If OMP exits zero, delete the temporary prompt file, print stdout to the console, then print `Headless init prompt '<prompt-name>' completed. Output: .omp/init/<prompt-stem>-headless-output.md` in cyan.
   - Reuse the command literals from `.omp/scripts/worktree-flow.py` lines 993-1005 and the output-file behavior from lines 1023-1048, but do not import or call worktree-flow because `harness-init.ps1` must stay standalone.

5. Wire mode selection before existing loadout validation.
   - After handling `-List` and before the current `if (-not $Loadout)` check at `harness-init.ps1` line 740, insert the headless init validation and branch.
   - Move target resolution above the loadout/harness required checks so `-Target` is validated for both loadout mode and init-prompt mode. Use the existing error text for missing/invalid target: `Error: Target '<target>' is not a directory.`
   - Branch order:
     1. Handle `-List` exactly as today.
     2. Validate `-Headless`/`-InitPrompt` pairing:
        - `-InitPrompt` without `-Headless` prints `Error: -Headless is required when -InitPrompt is used.` and exits 1.
        - `-Headless` without `-InitPrompt` prints `Error: -Headless requires -InitPrompt <name>.` and exits 1.
        - `-PlanChanges` with `-InitPrompt` prints `Error: -PlanChanges cannot be used with -InitPrompt.` and exits 1.
     3. Resolve `$Target` and ensure it is a directory.
     4. If `-InitPrompt` is present, wrap `Resolve-InitPromptPath` and `Invoke-OmpHeadlessInitPrompt` in `try { ... } catch { Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red; exit 1 }`, then `exit 0` on success.
     5. Continue with existing `-Loadout` and `-Harness` validation and loadout application unchanged.
   - Preserve `-PlanChanges` behavior for loadout mode only. Headless OMP execution is autonomous and has no dry-run mode in this feature.

6. Document the new command in `README.md`.
   - Update the existing `## Init Prompts` section at `README.md` lines 28-30.
   - Replace it with a concise section that keeps the existing source-template explanation and adds this exact command example:

     ```powershell
     .\harness-init.ps1 -Target C:\path\to\repo -InitPrompt omp-repo-init -Headless
     ```

   - State that headless init is hard-coded to OMP and writes run artifacts under the target repo’s `.omp/init/`, while the prompt is instructed to write its follow-up report under `.omp/init/reports/`.

7. Add focused tests in `tests/test_harness_init.py`.
   - Add `import os` and `import sys` at the top of `tests/test_harness_init.py`; existing imports already include `json`, `shutil`, `subprocess`, `tempfile`, `unittest`, and `Path`.
   - Add a private test helper `make_fake_omp(self, bin_dir: Path, record_path: Path) -> None` inside `HarnessInitTests`:
     - Write `fake_omp.py` next to the fake executable. Its content imports `json`, `os`, `sys`, and `pathlib.Path`; finds the first arg beginning with `@`; reads that prompt file; records `{"argv": sys.argv[1:], "cwd": os.getcwd(), "prompt": <prompt text>}` to `record_path`; prints `completed init`; exits 0.
     - On Windows (`os.name == "nt"`), write `omp.cmd` with exactly two lines: `@echo off` and `"<sys.executable>" "%~dp0fake_omp.py" %*`, using the current test interpreter path from `sys.executable`.
     - On non-Windows, write executable `omp` with exactly `#!/bin/sh\nexec "<sys.executable>" "$(dirname "$0")/fake_omp.py" "$@"\n`, using the current test interpreter path from `sys.executable`.
   - Add `test_headless_init_prompt_invokes_omp_with_augmented_prompt`:
     - Create temp root with copied scripts, `init-prompts/demo.md` containing `# Demo Prompt\n\nOriginal body.`, target repo, fake-OMP bin dir, and record JSON path.
     - Invoke copied `harness-init.ps1` with `-Target <target> -InitPrompt demo -Headless`, `cwd=root`, and env `PATH=<fake-bin><os.pathsep><old PATH>`.
     - Assert exit code 0.
     - Assert recorded command args are exactly `["-p", "--no-session", "--auto-approve", "--approval-mode", "yolo", "@<target>/.omp/init/demo-headless-prompt.md"]`, normalizing only path separators in the final `@...` argument if needed for Windows.
     - Assert recorded cwd equals the resolved target path.
     - Assert `.omp/init/demo-headless-output.md` contains `completed init`.
     - Assert `.omp/init/demo-headless-prompt.md` is deleted after success.
     - Assert recorded prompt contains `Original body.`, `The repository may already satisfy some or all items`, `end-state checklist`, `.omp/init/reports/`, and `yyyyMMdd-HHmmss-init-report.md`.
     - Assert stdout contains `Headless init prompt 'demo' completed.`.
   - Add `test_headless_init_prompt_accepts_model_option`:
     - Use the same fake OMP helper.
     - Invoke `-Target <target> -InitPrompt demo -Headless -Model gpt-test`.
     - Assert recorded args contain `--model`, `gpt-test` immediately before the final `@<prompt-file>` argument.
   - Add `test_headless_init_prompt_requires_headless_switch`:
     - Invoke `-Target <target> -InitPrompt demo` without `-Headless`.
     - Assert non-zero exit and stdout contains `-Headless is required when -InitPrompt is used`.
   - Add `test_headless_switch_requires_init_prompt`:
     - Invoke `-Target <target> -Headless` without `-InitPrompt`.
     - Assert non-zero exit and stdout contains `-Headless requires -InitPrompt <name>`.
   - Add `test_headless_init_prompt_rejects_path_traversal`:
     - Invoke `-Target <target> -InitPrompt ../demo -Headless`.
     - Assert non-zero exit and stdout contains `Init prompt name must be a file name under init-prompts`.
   - Add `test_headless_init_prompt_does_not_require_loadout_or_harness` as either a separate test or an assertion inside the success test: the success command must omit `-Loadout` and `-Harness` and still return 0.

## Critical files & anchors

- `harness-init.ps1` lines 14-23 — parameter block to extend with `-InitPrompt`, `-Headless`, and `-Model`.
- `harness-init.ps1` lines 732-775 — current main validation order; headless init mode must branch before `-Loadout` and `-Harness` are required.
- `.omp/scripts/worktree-flow.py` lines 993-1005 and 1023-1048 — existing OMP headless command and output-file semantics to copy, not import.
- `README.md` lines 28-30 — existing `## Init Prompts` section to update with the new command.
- `tests/test_harness_init.py` lines 16-37 and 164-193 — temp script copy and subprocess patterns for PowerShell-script tests.

## Verification

Run focused tests from the repository root:

```powershell
python -m pytest tests/test_harness_init.py tests/test_init_prompts.py
```

Expected result: all tests pass; new headless-init tests prove `harness-init.ps1 -Target <repo> -InitPrompt demo -Headless` invokes fake OMP with the exact headless args, uses the target repo as cwd, augments the prompt with both the idempotent end-state-checklist instruction and the `.omp/init/reports/` report instruction, writes stdout to `.omp/init/demo-headless-output.md`, and omits any `-Loadout`/`-Harness` requirement.

Also run the script-sync regression because the plan references existing OMP command semantics but does not edit `.omp/scripts/`:

```powershell
python -m pytest tests/test_worktrees_loadout_sync.py tests/test_codex_worktree_flow.py::SharedHarnessSelectionTests::test_omp_harness_exec_uses_print_mode_prompt_file_and_writes_stdout
```

Expected result: both pass, confirming `.omp/scripts/worktree-flow.py` and exported loadout copies remain in sync and the existing OMP headless behavior still matches the command copied into `harness-init.ps1`.

Manual smoke command, only when a real `omp` executable is available and the target can be modified:

```powershell
.\harness-init.ps1 -Target C:\path\to\scratch-repo -InitPrompt omp-repo-init -Headless
```

Expected observable result: the target repo contains `.omp/init/omp-repo-init-headless-output.md`; OMP’s own run creates a timestamped report under `.omp/init/reports/`; console output ends with `Headless init prompt 'omp-repo-init' completed.`

## Assumptions & contingencies

- Headless init mode is OMP-only by design. Do not add `-Harness` selection for this feature; existing loadout mode still requires `-Harness`.
- The default prompt location is the existing root `init-prompts/` source-template directory. If future prompt storage moves, update `Resolve-InitPromptPath`; do not copy prompts into loadouts for this feature.
- If `System.Diagnostics.Process` command capture proves awkward in PowerShell, use `Start-Process -RedirectStandardOutput -RedirectStandardError -Wait -PassThru` with temp files instead; keep the same command args, cwd, output paths, and error behavior.
- If a real OMP run fails before writing its own follow-up report, `harness-init.ps1` must still preserve stdout/stderr artifacts under `.omp/init/` so the user can inspect the failure.
