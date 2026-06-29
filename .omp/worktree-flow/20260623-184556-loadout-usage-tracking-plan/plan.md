# Loadout Usage Tracking Plan

## Context

Add per-loadout tracking so each loadout records every target repository it has been applied to, then add a bulk update script that reapplies an updated loadout to all recorded repositories. The registry lives under the loadout directory because the selected tracking scope is per loadout. Missing recorded repo paths warn and continue because the selected missing-repo policy is warn-and-continue.

Confirmed current behavior: `harness-init.ps1` is the loadout application script; it accepts `-Loadout`, `-Target`, required `-Harness`, and `-List`, resolves `$ScriptRoot`, `$LoadoutsDir`, `$LoadoutPath`, and `$Target`, then copies instructions, skills, hook config, and remaining loadout contents. Existing overwrite prompts are in `Copy-FileWithPrompt` and `Copy-Skills`, so a bulk updater needs a noninteractive overwrite path. Searches found no existing applied-repo registry or bulk-update script.

## Approach

1. Add an opt-in noninteractive overwrite path to `harness-init.ps1`.
   - Add `[switch]$Force` to the existing `param(...)` block after `[switch]$List`.
   - Change `Copy-FileWithPrompt` so when `$Force` is true and `$Dest` exists, it copies `$Source` to `$Dest` with `-Force`, writes `  [OVERWROTE] <relative path>`, and never calls `Read-Host`.
   - Change `Copy-Skills` so when `$Force` is true and a target skill directory exists, it calls `Copy-ItemWithoutGeneratedPythonCache -Source $skill.FullName -Dest $targetSkillPath`, counts it as copied, writes `           Overwritten.`, and never calls `Read-Host`.
   - Leave default behavior unchanged when `-Force` is absent: existing files and skills still prompt before overwrite.
   - Leave `Copy-InstructionFile` behavior unchanged: existing `AGENTS.md` content is skipped when the current loadout text is already present and appended with the existing dated separator when the current loadout text is not present. This preserves the current README contract instead of replacing target-authored instructions.

2. Add per-loadout usage registry helpers to `harness-init.ps1`.
   - Reserve metadata directory `loadouts/<loadout>/.harness-loadout/` and registry file `loadouts/<loadout>/.harness-loadout/applied-repos.json`.
   - Add `function Get-LoadoutUsagePath { param([string]$LoadoutPath) ... }` returning `Join-RepoPath $LoadoutPath ".harness-loadout/applied-repos.json"`.
   - Add `function Read-LoadoutUsage { param([string]$UsagePath, [string]$Loadout) ... }` returning this object when the file is missing:
     ```json
     { "version": 1, "loadout": "<loadout>", "repos": [] }
     ```
     If the file exists, parse it with `Get-Content -Raw | ConvertFrom-Json`; if `version` is absent, set it to `1`; if `loadout` is absent, set it to the current `$Loadout`; if `repos` is absent, set it to an empty array. Invalid JSON should throw and fail the apply so corrupt registry data is not silently overwritten.
   - Add `function Save-LoadoutUsage { param([string]$LoadoutPath, [string]$Loadout, [string]$Target, [string]$Harness) ... }` that creates `.harness-loadout`, reads the registry, removes any existing entry whose `path` equals `$Target` case-insensitively and whose `harness` equals `$Harness` case-insensitively, appends one entry, sorts by `path` then `harness`, and writes UTF-8 JSON with `ConvertTo-Json -Depth 10`.
   - The exact entry shape is:
     ```json
     {
       "path": "C:\\absolute\\repo",
       "harness": "codex",
       "lastAppliedAt": "2026-06-24T00:00:00.0000000Z"
     }
     ```
     Use the already resolved absolute `$Target` and `$profile.Name` so the `claude-code` alias records as `claude`.
   - Call `Save-LoadoutUsage -LoadoutPath $LoadoutPath -Loadout $Loadout -Target $Target -Harness $profile.Name` after the final loadout copy loop succeeds and before `Write-Host "`nDone!"`. Do not record on `-List`, validation failures, or partial copy failures.
   - Update the final top-level `foreach ($item in Get-ChildItem -Path $LoadoutPath -Force)` skip condition to skip `$item.Name -eq ".harness-loadout"`, so the registry is never copied into target repositories.

3. Add root script `update-loadout-repos.ps1`.
   - Create `update-loadout-repos.ps1` beside `harness-init.ps1`.
   - Use this script header and params:
     ```powershell
     <#
     .SYNOPSIS
         Reapply a loadout to every repository recorded for that loadout.
     #>
     [CmdletBinding(SupportsShouldProcess = $true)]
     param(
         [Parameter(Mandatory = $true)]
         [string]$Loadout
     )
     ```
   - Resolve `$ScriptRoot`, `$LoadoutsDir`, `$LoadoutPath`, `$UsagePath`, and `$HarnessInit` the same way as `harness-init.ps1`; use the same registry path literal `.harness-loadout/applied-repos.json`.
   - If `$LoadoutPath` does not exist, write `Error: Loadout '<name>' not found.` in red, list available loadouts the same way as `harness-init.ps1`, and `exit 1`.
   - If `$UsagePath` does not exist, write `No repositories recorded for loadout '<name>'.` and `exit 0`.
   - Parse the registry with `Get-Content -Raw | ConvertFrom-Json`. If JSON parsing fails, if `version` is not `1`, or if `repos` is absent, write a red error and `exit 1`.
   - Resolve PowerShell for child runs with `$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source`; run `harness-init.ps1` in a child process so any `exit` in that script cannot terminate the updater early.
   - For each `repo` in `@($data.repos)`:
     - If `repo.path` or `repo.harness` is missing/empty, `Write-Warning "Skipping malformed registry entry in <usage path>."`, increment skipped count, and continue.
     - If `repo.path` does not exist as a container, `Write-Warning "Skipping missing repo: <path>"`, increment skipped count, and continue; do not edit the registry.
     - If `$PSCmdlet.ShouldProcess($repo.path, "Apply loadout '<loadout>' for harness '<harness>'")` returns false because `-WhatIf` was used, increment planned count and do not run `harness-init.ps1`.
     - Otherwise run:
       ```powershell
       & $Pwsh -NoProfile -ExecutionPolicy Bypass -File $HarnessInit -Loadout $Loadout -Target $repo.path -Harness $repo.harness -Force
       ```
       If `$LASTEXITCODE` is nonzero, `Write-Warning "Failed to update repo: <path>"`, increment failed count, and continue to the next entry; otherwise increment updated count.
   - At the end, print `Updated: <n>; planned: <n>; skipped: <n>; failed: <n>.` Exit `1` if any repo update failed; otherwise exit `0`. Missing repos and malformed entries count as skipped, not failed.
   - Do not add a prune/delete option in this feature; stale paths remain in the registry until a future explicit cleanup command is requested.

4. Add focused tests in `tests/test_harness_init.py`, reusing the existing `HarnessInitTests` style.
   - Add `import json` at the top.
   - Add helper `copy_scripts_to_temp_root(root: Path) -> tuple[Path, Path]` that copies `harness-init.ps1` and `update-loadout-repos.ps1` into `root` and returns `(root / "harness-init.ps1", root / "update-loadout-repos.ps1")`. Keep the existing `run_init()` helper unchanged for current root-script tests.
   - Test `harness-init.ps1` records and upserts one repo per loadout: create `root/loadouts/custom/AGENTS.md`, create `root/target`, copy scripts with `copy_scripts_to_temp_root(root)`, run the temp `harness-init.ps1 -Loadout custom -Target <target> -Harness codex`, assert return code `0`, read `root/loadouts/custom/.harness-loadout/applied-repos.json`, and assert `version == 1`, `loadout == "custom"`, exactly one `repos` entry, `path == str(target.resolve())`, `harness == "codex"`, and `lastAppliedAt` is nonempty. Run the same apply command a second time and assert the registry still has exactly one entry for that path/harness.
   - Add a test that pre-creates `root/loadouts/custom/.harness-loadout/applied-repos.json`, runs apply, and asserts `target/.harness-loadout` does not exist. This verifies metadata is not copied into target repos.
   - Add a test for `-Force`: create `loadouts/custom/.harness/settings.txt` with `new`, create `target/.codex/settings.txt` with `old`, run `harness-init.ps1 -Loadout custom -Target <target> -Harness codex -Force`, assert return code `0`, and assert `target/.codex/settings.txt == "new"` without providing stdin.
   - Add a test for `update-loadout-repos.ps1`: create two target repos, create `loadouts/custom/.harness/settings.txt` with `v1`, copy scripts with `copy_scripts_to_temp_root(root)`, run temp `harness-init.ps1 -Loadout custom -Target <target1> -Harness codex -Force` and the same command for `<target2>` to create the initial target files, then overwrite the registry manually with `version: 1`, `loadout: "custom"`, and `repos` entries for both targets plus one missing path. Change `loadouts/custom/.harness/settings.txt` from `v1` to `v2`. Run `pwsh -NoProfile -ExecutionPolicy Bypass -File update-loadout-repos.ps1 -Loadout custom` with `cwd=root`. Assert return code `0`, both existing targets now contain `.codex/settings.txt` with `v2`, combined stdout/stderr contains `Skipping missing repo`, and the registry still contains the missing path.
   - Add a test for `-WhatIf`: create one target repo, create stale target content with an initial forced apply, manually write a registry containing that target, change the loadout content, run `update-loadout-repos.ps1 -Loadout custom -WhatIf`, assert return code `0`, and assert the target file remains unchanged.

5. Update `README.md` after the behavior tests pass.
   - In Quick Start, add the bulk-update command immediately after the apply examples:
     ```powershell
     # Reapply a changed loadout to every repo recorded for it
     .\update-loadout-repos.ps1 -Loadout my-loadout
     ```
   - In How It Works, add bullets stating that successful applies record `<target path, harness, last applied time>` in `loadouts/<loadout>/.harness-loadout/applied-repos.json`, the metadata directory is not copied into targets, and `update-loadout-repos.ps1` replays those entries with `-Force` while warning and continuing for missing repos.

## Critical files & anchors

- `harness-init.ps1` — `param` lines 14-19, overwrite prompts in `Copy-FileWithPrompt` and `Copy-Skills`, target/loadout validation around lines 350-374, final copy loop around lines 431-452.
- `tests/test_harness_init.py` — current PowerShell integration tests use `pwsh -NoProfile -ExecutionPolicy Bypass -File ...` with temp loadouts and targets; add registry and updater tests here.
- `README.md` — Quick Start lines 15-23 and How It Works lines 44-50 describe the user-facing script contract.

## Verification

Run from `C:/Users/joesa/Code/harness-loadouts` after implementation:

```powershell
python -m unittest tests.test_harness_init
```

Expected: all tests in `tests.test_harness_init` pass. The new behavior is covered by tests that create a temp loadout, record applied repos, verify no duplicate registry entries, verify `.harness-loadout` is not copied to targets, verify `-Force` overwrites without prompting, verify `update-loadout-repos.ps1` updates two recorded repos to changed loadout content, and verify missing repos warn without pruning.

Manual smoke check if desired after tests pass:

```powershell
.\harness-init.ps1 -Loadout worktrees -Target <existing-test-repo> -Harness codex
.\update-loadout-repos.ps1 -Loadout worktrees -WhatIf
```

Expected: the first command succeeds and records `<existing-test-repo>` under `loadouts/worktrees/.harness-loadout/applied-repos.json`; the second command prints the planned reapply without changing the target.

## Assumptions & contingencies

- Registry location is fixed at `loadouts/<loadout>/.harness-loadout/applied-repos.json`. If implementation finds an existing file or directory at `.harness-loadout` that is not a directory, fail with a clear error instead of choosing another path.
- The registry stores absolute target paths from `Resolve-Path`; do not store relative paths, because the bulk updater runs later from the harness-loadouts repo and must not depend on the original caller's working directory.
- Bulk update uses the harness recorded at apply time. If the same repo is applied with the same loadout for two harnesses, keep two entries and update both; uniqueness is `(path, harness)`, not path alone.
- Missing repos warn and remain in the registry. Only child `harness-init.ps1` failures make `update-loadout-repos.ps1` exit nonzero.
- `AGENTS.md` update semantics remain append/skip, matching existing behavior. `-Force` is only a noninteractive overwrite path for existing copied files and skills.
