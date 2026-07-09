# Implementation Summary

## Plan

- Plan path: `.omp/worktree-flow/20260709-104914-worktree-usage-stats-logging/plan.md`
- Worktree path: `/mnt/c/Users/joesa/code/harness-loadouts-worktree-usage-stats-logging`
- Branch: `feature/worktree-usage-stats-logging`
- Commit: `cc915c129733bab02016072ba96807863249ea1e`

## Changed Files

- `.omp/scripts/worktree-flow.py`
- `loadouts/worktrees/.harness/scripts/worktree-flow.py`
- `loadouts/worktrees/.opencode/scripts/worktree-flow.py`
- `loadouts/worktrees/.harness/docs/worktree-flow-explained.md`
- `tests/test_codex_worktree_flow.py`

## Behavior Changes

- Added numeric-only OMP usage telemetry to `HarnessWorktreeFlow.harness_exec`.
- Added live handoff artifacts under `.<harness>/handoff/`:
  - `usage-events.jsonl`
  - `usage-summary.json`
  - `usage-sources.json`
- Usage event collection now runs after every harness phase and before raising harness execution failures, so failed or timed-out phases still leave usage artifacts.
- Usage collection emits `status: "unavailable"` with `reason: "non_omp_harness"` for non-OMP harnesses and `reason: "no_matching_session_files"` when no changed OMP session file matches the phase worktree.
- Added OMP session root discovery mirroring `save-plan.py`: Linux home sessions plus the WSL Windows-home session root when the repo path is under `/mnt/<drive>/Users/<user>/`.
- Added pre-command OMP session snapshots and post-command changed-session selection capped at `SESSION_SCAN_MAX_FILES = 2000` newest `*.jsonl` files.
- Added phase-scoped extraction of numeric/config metadata only:
  - assistant message token and cost totals from `message.usage.*` and `message.usage.cost.*`
  - nested response token totals from `message.details.response.usage.*`
  - model/provider/api/stop-reason counts
  - context snapshot max/last prompt and non-message token counts
  - message duration and TTFT timing aggregates
  - tool start/result counts and safe numeric tool details such as wall time, file count, match count, exit code, timeout seconds, limit flags, and truncation counters
  - top-level `type` and `customType` event counts
- Added redacted source provenance in `usage-sources.json`: source id, session id, basename-only file name, 16-character SHA-256 path hash, records read, event counts, and up to 50 safe record ids.
- Explicitly avoids writing prompt text, assistant response text, tool display content, stdout/stderr, URL response bodies, raw tool argument values, prompt-file paths, session cwd values, or absolute session paths to usage artifacts.
- Updated all workflow harness phase callsites to pass explicit phase names:
  - `implementation`
  - `audit`
  - `conflict_resolution`
  - `post_conflict_audit`
- Kept `workflow.jsonl` initialization unchanged; usage artifacts are created lazily by the first harness phase.
- Kept archive behavior unchanged; existing `archive_handoff()` copies the new usage artifacts with the rest of handoff files.
- Synced the runnable `.omp` workflow script to both shipped loadout copies required by repository rules.
- Updated the worktrees loadout documentation to list the new usage files and state their privacy boundary.

## Tests and Checks Run

- `python3 -m py_compile .omp/scripts/worktree-flow.py`
  - Result: passed.
- Targeted telemetry smoke checks via Python import/eval:
  - Non-OMP `harness_exec` wrote an unavailable usage event and summary privacy booleans with no prompt leakage.
  - OMP collection aggregated assistant token/cost/context values and did not serialize prompt text or absolute session paths.
  - OMP tool collection counted a `read` tool start/result and did not serialize tool argument path or display text.
  - Result: passed.
- Tester-authored focused tests:
  - `python3 -m unittest tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_collects_omp_usage_stats_split_by_phase_without_text tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_harness_exec_writes_usage_artifacts_on_failure tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_non_omp_harness_records_unavailable_usage_event tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_archive_handoff_copies_usage_artifacts`
  - Result: passed, 4 tests.
  - `python3 -m unittest tests.test_codex_worktree_flow.SharedHarnessSelectionTests.test_omp_harness_exec_uses_print_mode_prompt_file_and_writes_stdout tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_harness_exec_adds_harness_and_common_git_dirs_as_writable_roots tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_harness_exec_uses_full_access_sandbox_on_windows tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_harness_exec_uses_workspace_write_sandbox_off_windows tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_harness_command_includes_model_and_output_file tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_harness_exec_logs_jsonl_to_main_repo_archive tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_failing_harness_exec_logs_failure_without_prompt_and_bounds_output tests.test_codex_worktree_flow.HarnessWorktreeFlowTests.test_timed_out_harness_exec_logs_timeout_failure`
  - Result: passed, 8 tests.
- Plan-required workflow/loadout tests:
  - `python3 -m unittest tests.test_codex_worktree_flow tests.test_worktrees_loadout_sync`
  - First run result: workflow tests passed; loadout sync failed because script copies had not yet been synced.
  - After syncing loadout copies, rerun result: passed, 74 tests.
- Plan-required updater tests:
  - `python3 -m unittest tests.test_harness_init`
  - Result: passed with `skipped=14`; all tests skipped because PowerShell (`pwsh`) is unavailable in this environment.
- Plan-required CLI smoke check:
  - `python3 .omp/scripts/worktree-flow.py --help`
  - Result: passed, printed parser help and exited 0.
- PowerShell availability check:
  - `command -v pwsh`
  - Result: exit code 1; no `pwsh` executable on PATH.

## Skipped Checks

- `python .omp/scripts/worktree-flow.py --help` was not run with `python` because `python` is not installed on PATH in this WSL environment (`python -m py_compile .omp/scripts/worktree-flow.py` failed with `command not found`). Equivalent `python3` checks passed.
- `pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees -WhatIf` was not run because `pwsh` is unavailable on PATH.
- `pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees` was not run because `pwsh` is unavailable on PATH. The target-repo rollout could not be performed locally.

## Implementation Decisions and Tradeoffs

- Used JSONL events plus rewritten summary/source JSON files so interrupted or failed harness phases preserve phase-level telemetry.
- Kept usage files under existing handoff/archive locations rather than adding a new archive path; this preserves existing handoff exclusion and archive behavior.
- Aggregated only fields explicitly allowed by the plan and ignored unknown OMP numeric fields to keep the privacy boundary stable.
- Stored model/provider/API/stop-reason values as aggregate counts only; no prompt, response, command output, raw tool args, URLs, or file contents are serialized.
- Used 16-character SHA-256 hashes for session paths and basename-only file names for source provenance.
- Capped session scanning and changed-file selection at the newest 2000 JSONL files to bound filesystem cost.
- For path matching, compared resolved paths when possible plus normalized POSIX/backslash strings and WSL drive equivalents.
- For dry-run usage writes, usage artifact write helpers print `+ write <path>` and do not mutate files, matching existing write-helper style.

## Assumptions

- OMP session JSONL records follow the plan-described schema for `message.usage`, `message.details.response.usage`, `message.contextSnapshot`, `customType == "tool_execution_start"`, and tool-result messages.
- Record ids are safe to include only when they match a conservative identifier regex; unsafe/arbitrary ids are omitted rather than hashed or copied.
- If `omp -p --no-session` produces no changed matching session file, the correct behavior is an unavailable usage event, not changing harness invocation flags.
- The unavailable non-OMP event is expected for codex/default harness runs and still produces summary/privacy artifacts.

## Known Risks and Follow-Up

- Rollout to recorded target repositories is not done in this worktree because PowerShell is unavailable. Re-run the plan-required `update-loadout-repos.ps1` WhatIf/apply commands in an environment with `pwsh` before considering target repositories updated.
- Usage collection depends on session file mtimes increasing after the pre-command snapshot. Files written without a newer `st_mtime_ns` may not be selected for that phase.
- Unknown future OMP schema fields are intentionally ignored unless they match the explicit allowlist from the approved plan.
- Summary/source JSON files are rewritten from valid event records; malformed lines in `usage-events.jsonl` are ignored.
