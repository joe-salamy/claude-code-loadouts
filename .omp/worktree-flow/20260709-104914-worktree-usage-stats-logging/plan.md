# Worktree Usage Stats Logging

## Context

Add numeric-only usage telemetry to the worktree workflow script used in this repository and shipped by the `worktrees` loadout. The workflow already writes `workflow.jsonl` under `.<harness>/handoff/` during a run and archives handoff files to `.<harness>/worktree-flow/<run-id>/`; the new telemetry must live beside those artifacts, split implementation and audit usage, and avoid prompt/response logging. After implementation, commit the source changes in this repository, then use the repository's existing loadout updater to apply the updated `worktrees` loadout to every recorded target repository.

## Approach

### Add numeric telemetry artifacts to the workflow

1. In `.omp/scripts/worktree-flow.py`, keep `workflow.jsonl` behavior intact and add a separate stats artifact set under the same handoff/archive path:
   - During a live run: `.<harness>/handoff/usage-events.jsonl`, `.<harness>/handoff/usage-summary.json`, and `.<harness>/handoff/usage-sources.json` inside the feature or integration worktree currently executing the phase.
   - Durable archive after stop/success/cleanup: existing `archive_handoff()` already copies every handoff file into `.<harness>/worktree-flow/<run-id>/`, so the same three files must appear beside `plan.md`, `workflow.jsonl`, and `workflow-state.json` without adding a second archive mechanism.
   - Do not add these files to commits from implementation/audit/integration; they remain handoff/worktree-flow artifacts covered by existing `path_is_handoff()` and `stage_integration_changes()` behavior.

2. Add constants near existing workflow constants:
   - `USAGE_EVENTS_FILENAME = "usage-events.jsonl"`
   - `USAGE_SUMMARY_FILENAME = "usage-summary.json"`
   - `USAGE_SOURCES_FILENAME = "usage-sources.json"`
   - `SESSION_SCAN_MAX_FILES = 2000`
   These names are load-bearing: tests and docs must use exactly these filenames.

3. Add typed helpers and dataclasses in `.omp/scripts/worktree-flow.py`; keep them stdlib-only and Python 3.11-compatible:
   - `@dataclass(frozen=True) class SessionSnapshot: files: dict[str, int]` where keys are resolved source paths and values are `st_mtime_ns`.
   - `@dataclass(frozen=True) class UsageSource: source_id: str; session_id: str | None; file_name: str; path_hash: str; records_read: int; event_counts: dict[str, int]; record_ids: list[str]`.
   - `@dataclass(frozen=True) class UsageTotals: input_tokens: int = 0; output_tokens: int = 0; cache_read_tokens: int = 0; cache_write_tokens: int = 0; reasoning_tokens: int = 0; total_tokens: int = 0; cost_input: float = 0.0; cost_output: float = 0.0; cost_cache_read: float = 0.0; cost_cache_write: float = 0.0; cost_total: float = 0.0`.
   - Use `asdict()` for JSON serialization; do not introduce a dependency, Pydantic model, or package config.

4. Add path/session discovery helpers to `HarnessWorktreeFlow`:
   - `usage_events_file(self, worktree: Path) -> Path`, `usage_summary_file(self, worktree: Path) -> Path`, and `usage_sources_file(self, worktree: Path) -> Path` returning paths under `worktree / self.handoff_dir`.
   - `omp_sessions_roots(self, repo: Path) -> list[Path]` mirroring `save-plan.py`'s `candidate_sessions_roots(repo)`: `Path.home() / ".omp" / "agent" / "sessions"`, plus `wsl_windows_home_from_repo(repo.resolve()) / ".omp" / "agent" / "sessions"` for WSL checkouts matching `^/mnt/([A-Za-z])/Users/([^/]+)(?:/|$)`. If a root does not exist, skip it.
   - `snapshot_omp_sessions(self, repo: Path) -> SessionSnapshot` scanning `*.jsonl` recursively under those roots, capped at `SESSION_SCAN_MAX_FILES` newest files by `st_mtime_ns`; store resolved path and `st_mtime_ns` only.
   - `changed_session_files(self, repo: Path, snapshot: SessionSnapshot) -> list[Path]` returning files absent from the snapshot or whose current `st_mtime_ns` is greater than the snapshot value, newest first, capped at `SESSION_SCAN_MAX_FILES`.
   - `session_cwd(self, session_file: Path) -> str | None` reading only `type == "session"` or `type == "session_init"` records and returning the `cwd` scalar when present.
   - `path_matches_worktree(self, raw_cwd: str, worktree: Path) -> bool` comparing normalized resolved paths when possible; also compare raw POSIX strings with backslashes converted to `/` so WSL/Windows separators do not block matches.

5. Add OMP stats extraction helpers that never copy prompt, assistant response, tool result display text, file contents, command stdout/stderr, URL response bodies, or arbitrary `data.args` values into usage artifacts:
   - `collect_phase_usage(self, repo: Path, worktree: Path, phase: str, snapshot: SessionSnapshot, command_result: CommandResult) -> dict[str, object]`.
   - It selects changed OMP session files whose safe session `cwd` matches the phase worktree. For non-OMP harnesses or no matching files, emit a phase event with `status: "unavailable"` and a reason: `"non_omp_harness"` or `"no_matching_session_files"`.
   - It parses each selected JSONL record and aggregates only scalar numeric/config metadata from the confirmed OMP schema:
     - model/config: top-level `model_change.model`, `thinking_level_change.thinkingLevel`, `service_tier_change.serviceTier`, and assistant message `message.api`, `message.provider`, `message.model`, `message.stopReason`.
     - token/cost totals: assistant message `message.usage.input`, `output`, `cacheRead`, `cacheWrite`, `reasoningTokens`, `totalTokens`, and `message.usage.cost.input`, `output`, `cacheRead`, `cacheWrite`, `total`.
     - nested tool response usage: `message.details.response.usage.inputTokens`, `outputTokens`, `totalTokens` under a separate `nested_response_usage` total so it is not double-counted with assistant model usage.
     - timings: `message.duration`, `message.ttft`, `CommandResult.started_at`, `finished_at`, `duration_ms`, `returncode`, and `timed_out`.
     - context size snapshots: `message.contextSnapshot.promptTokens` and `nonMessageTokens`; store `max_prompt_tokens`, `last_prompt_tokens`, `max_non_message_tokens`, and `last_non_message_tokens`, not a sum.
     - tool calls: count `customType == "tool_execution_start"` grouped by `data.toolName`; count tool-result messages where `message.role == "toolResult"` grouped by `message.toolName`; count `message.isError == true`; aggregate safe numeric details such as `message.details.wallTimeMs`, `exitCode`, `timeoutSeconds`, `fileCount`, `matchCount`, `fileLimitReached`, `resultLimitReached`, and truncation byte/line counters.
     - event counts: count top-level `type` values and `customType` values.
   - It must not store `message.content`, `message.details.displayContent`, `message.details.response.answer`, `message.details.files`, `message.details.url`, `data.args.path`, raw commands, stdout, stderr, or any prompt-file path in `usage-events.jsonl`, `usage-summary.json`, or `usage-sources.json`.

6. Implement redacted source provenance in `usage-sources.json`:
   - For each parsed session file assign source ids `session-1`, `session-2`, ... within that phase collection.
   - Store only `source_id`, `session_id`, `file_name` (basename only), `path_hash` as `sha256(str(path.resolve())).hexdigest()[:16]`, `records_read`, `event_counts`, and up to 50 record ids from records that contributed numeric/config/tool metadata.
   - Do not store absolute session paths, cwd values, prompts, response text, or tool argument values.

7. Add phase event appending and summary rewriting:
   - `append_usage_event(self, worktree: Path, event: dict[str, object]) -> None` appends JSON to `usage-events.jsonl`; no-op on dry-run except printing `+ write <path>` consistent with existing write helpers.
   - `rewrite_usage_summary(self, worktree: Path) -> None` reads all valid `usage-events.jsonl` records and writes `usage-summary.json` with this exact top-level shape:
     ```json
     {
       "schema_version": 1,
       "generated_at": "<iso timestamp>",
       "run_id": "<workflow run id>",
       "harness": "omp",
       "harness_dir": ".omp",
       "phases": {
         "implementation": { "runs": 1, "status_counts": { "collected": 1 }, "totals": { } },
         "audit": { "runs": 1, "status_counts": { "collected": 1 }, "totals": { } },
         "conflict_resolution": { },
         "post_conflict_audit": { }
       },
       "totals": { },
       "models": { },
       "tools": { },
       "sources": { "count": 0, "path_hashes": [] },
       "privacy": {
         "prompt_text_logged": false,
         "response_text_logged": false,
         "tool_argument_values_logged": false,
         "session_paths_logged": false
       }
     }
     ```
     `totals`, `models`, and `tools` must contain aggregate numeric counts from all phase events. Empty phase keys are allowed when that phase did not run, but implementation and audit must be present after a normal run.
   - `rewrite_usage_sources(self, worktree: Path) -> None` writes `usage-sources.json` from the redacted sources embedded in usage events.

8. Wire telemetry to phase boundaries by changing `harness_exec` and its callers:
   - Change signature from `harness_exec(self, cwd: Path, prompt: str, output_file: Path) -> None` to `harness_exec(self, cwd: Path, prompt: str, output_file: Path, *, phase: str) -> None`.
   - Update all direct callers:
     - `run_implementation(...)` passes `phase="implementation"`.
     - `run_audit(..., post_conflict=False)` passes `phase="audit"`.
     - `run_audit(..., post_conflict=True)` passes `phase="post_conflict_audit"`.
     - `run_conflict_resolution(...)` passes `phase="conflict_resolution"`.
     - Existing tests/direct calls in `tests/test_codex_worktree_flow.py` pass an explicit phase, usually `phase="implementation"` unless the test is audit-specific.
   - In `harness_exec`, call `snapshot_omp_sessions(cwd)` immediately before `self.runner.run(...)`. After `log_command_result("harness_exec_finish", ...)`, call `collect_phase_usage(...)`, `append_usage_event(...)`, `rewrite_usage_summary(...)`, and `rewrite_usage_sources(...)` before raising failures. This preserves stats for failed/timed-out harness phases.
   - The new usage event must include `phase`, `run_id` when known from `self._last_state` or parsed from existing workflow log, `status`, `command_returncode`, `command_timed_out`, `command_duration_ms`, and the aggregated stats. It must not include the harness command array because OMP prompt-file paths can identify prompt artifacts.

9. Keep resume and archive behavior deterministic:
   - `start_log()` and `continue_log()` should initialize only `workflow.jsonl`; the first harness phase creates usage files lazily.
   - `archive_handoff()` already copies all handoff files; no special case is needed except tests verifying stats files are copied.
   - `cleanup_successful_worktrees()` sets `self.log_file` to the archive workflow log after cleanup; add analogous archive-aware handling only if usage events are appended during cleanup. Since no harness phase runs during cleanup, no extra usage write is required after worktree removal.

### Sync the shipped loadout copies

1. After `.omp/scripts/worktree-flow.py` is correct, copy its exact contents to:
   - `loadouts/worktrees/.harness/scripts/worktree-flow.py`
   - `loadouts/worktrees/.opencode/scripts/worktree-flow.py`
2. Do not edit `save-plan.py`; the current task only changes the workflow runner. Existing `tests/test_worktrees_loadout_sync.py` covers both script directories and will fail if the copies drift.
3. Update `loadouts/worktrees/.harness/docs/worktree-flow-explained.md` in the final cleanup phase after tests first prove the telemetry works. Add the new files under `## Files Produced` and state that usage files contain numeric usage/tool/timing metadata only, not prompt or response text.

### Add focused tests

1. Extend `tests/test_codex_worktree_flow.py` with fake OMP session JSONL fixtures created under a temporary fake sessions root. Avoid real home/session files in tests by monkeypatching `subject.omp_sessions_roots = lambda _repo: [fake_root]`.
2. Add `test_collects_omp_usage_stats_split_by_phase_without_text`:
   - Create a fake worktree path and two fake session JSONL files whose `session.cwd` matches that path.
   - Implementation fixture includes one assistant message with `message.model = "gpt-5.5"`, `message.provider = "openai-codex"`, `message.usage.input = 10`, `output = 4`, `cacheRead = 3`, `cacheWrite = 2`, `reasoningTokens = 1`, `totalTokens = 20`, `message.usage.cost.total = 0.12`, `message.duration = 1.5`, `message.ttft = 0.2`, `message.contextSnapshot.promptTokens = 100`, `nonMessageTokens = 25`; include a prompt-like string in `message.content` that must not appear in artifacts.
   - Audit fixture includes a different token set and a tool call start/result pair for `read` with safe numeric `wallTimeMs = 12` and `fileCount = 2`; include fake `data.args.path` and `message.details.displayContent.text` strings that must not appear in artifacts.
   - Call `collect_phase_usage(..., phase="implementation", ...)`, append/rewrite, then repeat for `phase="audit"`.
   - Assert `usage-summary.json` has separate `phases.implementation.totals.total_tokens == 20`, `phases.audit.tools.read.calls == 1`, aggregate totals equal both phases, and the full JSON text does not contain the prompt-like string, display text, raw path, or absolute session path.
3. Add `test_harness_exec_writes_usage_artifacts_on_failure`:
   - Use `FailingHarnessExecRunner` and a fake OMP session modified after the snapshot.
   - Assert `usage-events.jsonl`, `usage-summary.json`, and `usage-sources.json` exist even though `harness_exec(..., phase="implementation")` raises `FlowError`.
   - Assert the event records `command_returncode == 42`, `status == "collected"`, and no prompt text appears.
4. Add `test_non_omp_harness_records_unavailable_usage_event`:
   - Use default codex config and `harness_exec(..., phase="implementation")`.
   - Assert the usage event has `status == "unavailable"`, `reason == "non_omp_harness"`, and `usage-summary.json` still has `schema_version == 1` with privacy booleans all `false`.
5. Add `test_archive_handoff_copies_usage_artifacts`:
   - Create `usage-events.jsonl`, `usage-summary.json`, and `usage-sources.json` under a worktree handoff dir.
   - Call `archive_handoff(repo, worktree, "plan-run")`.
   - Assert all three files exist under `repo / .<harness> / worktree-flow / plan-run`.
6. Update existing `harness_exec` tests in `tests/test_codex_worktree_flow.py` to pass the new `phase=` keyword and adjust expected usage files only where the new behavior writes them.

### Verify locally, commit this repository, then roll out the loadout

1. Run focused tests from the repository root:
   ```powershell
   python -m unittest tests.test_codex_worktree_flow tests.test_worktrees_loadout_sync
   ```
   Expected: all tests pass. This exercises new usage aggregation, privacy exclusions, archive copying, and script-copy sync.
2. Run updater tests because rollout uses `update-loadout-repos.ps1` and `harness-init.ps1`:
   ```powershell
   python -m unittest tests.test_harness_init
   ```
   Expected: all tests pass or skip only when `pwsh` is not installed; a skip is acceptable only if the final report says rollout could not be tested locally because `pwsh` was unavailable.
3. Smoke-test the CLI without creating worktrees:
   ```powershell
   python .\.omp\scripts\worktree-flow.py --help
   ```
   Expected: exits 0 and prints the parser help.
4. Commit only this repository's source/test/doc changes:
   ```powershell
   git status --short
   git add .omp/scripts/worktree-flow.py loadouts/worktrees/.harness/scripts/worktree-flow.py loadouts/worktrees/.opencode/scripts/worktree-flow.py loadouts/worktrees/.harness/docs/worktree-flow-explained.md tests/test_codex_worktree_flow.py
   git commit -m "Add worktree usage stats logging"
   git status --short
   ```
   Do not stage `docs/scratchpad.md`, `applied-repos.json`, generated `.<harness>/handoff/`, generated `.<harness>/worktree-flow/`, or target-repo changes.
5. Plan the loadout rollout with the dedicated updater:
   ```powershell
   pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees -WhatIf
   ```
   Expected: output lists planned updates or says no repositories are recorded; failed count must be 0. Because the updater has `SupportsShouldProcess`, `-WhatIf` routes through `harness-init.ps1 -PlanChanges` for each recorded repo.
6. If the rollout plan has `failed: 0`, apply the loadout to all recorded repos:
   ```powershell
   pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees
   ```
   Expected: exits 0 and prints `Updated: <n>; planned: 0; skipped: <m>; failed: 0.` Missing repos may be skipped by the existing updater; report skipped count and paths only from the command output. Do not manually copy files into target repos and do not commit target repos unless separately requested.

## Critical files & anchors

- `.omp/scripts/worktree-flow.py` — `HarnessWorktreeFlow.harness_exec`, `run_implementation`, `run_audit`, `run_conflict_resolution`, `archive_handoff`, and existing log helpers around `workflow_log_file`, `log_event`, and `log_command_result`; this is the runnable script for this repo.
- `loadouts/worktrees/.harness/scripts/worktree-flow.py` — actual loadout template copied into target harness directories by `harness-init.ps1`; must match `.omp/scripts/worktree-flow.py` exactly.
- `loadouts/worktrees/.opencode/scripts/worktree-flow.py` — exported opencode copy required by repo rules; must match `.omp/scripts/worktree-flow.py` exactly.
- `tests/test_codex_worktree_flow.py` — existing workflow/log tests and `FakeRunner`/`FailingHarnessExecRunner`; extend here for stats aggregation and privacy checks.
- `update-loadout-repos.ps1` — existing dedicated rollout script; it reads `applied-repos.json`, supports `-WhatIf`, calls `harness-init.ps1 -Force`, and is the only rollout mechanism to use.

## Verification

- `python -m unittest tests.test_codex_worktree_flow tests.test_worktrees_loadout_sync` from the repository root proves the new telemetry behavior, no prompt/text leakage in usage artifacts, archive copying, and exact script sync across `.omp`, `.harness`, and `.opencode` copies.
- `python -m unittest tests.test_harness_init` from the repository root proves the dedicated loadout updater path used for rollout still works. If `pwsh` is unavailable, the existing tests skip; record that exact skip and still run the updater commands only if `pwsh` is available.
- `python .\.omp\scripts\worktree-flow.py --help` from the repository root proves the script still imports and the CLI parser still works after adding dataclasses/helpers.
- `pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees -WhatIf` proves the target set and planned changes without mutating target repos.
- `pwsh -NoProfile -ExecutionPolicy Bypass -File .\update-loadout-repos.ps1 -Loadout worktrees` performs the requested rollout through the existing updater; success is exit 0 with `failed: 0` in the summary.

## Assumptions & contingencies

- The telemetry artifact choice is JSONL events plus a final summary JSON, with a redacted provenance sidecar. This is intentionally more robust than one final JSON because interrupted or failing harness phases still leave phase events behind.
- OMP session JSONL is the source of model/token/tool statistics. Confirmed numeric fields include `message.usage.*`, `message.usage.cost.*`, `message.duration`, `message.ttft`, `message.contextSnapshot.*`, nested `message.details.response.usage.*`, tool call/result metadata, and top-level `model_change`, `thinking_level_change`, and `service_tier_change` records.
- If `omp -p --no-session` produces no matching session file for a phase, do not remove `--no-session` or change harness behavior. Record an `unavailable` usage event with `reason: "no_matching_session_files"`, keep command duration/returncode in the usage event, and leave token/model/tool totals at zero for that phase.
- If multiple changed OMP session files match the same worktree during one phase, aggregate all of them and list each in `usage-sources.json` with a separate redacted `source_id`; do not ask the implementer to choose one.
- If the OMP session schema adds new numeric fields, ignore unknown fields for this change unless they are under the explicit paths listed in the Approach. This keeps the schema stable and prevents accidental capture of content-bearing fields.
- Rollout uses `update-loadout-repos.ps1 -Loadout worktrees`; do not direct-sync target repositories. If the registry has no repositories, the updater's `No repositories recorded for loadout 'worktrees'.` output satisfies the rollout step because there are no recorded targets to update.
