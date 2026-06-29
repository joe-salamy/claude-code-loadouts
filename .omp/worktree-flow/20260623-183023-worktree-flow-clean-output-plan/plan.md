# Worktree Flow Clean Output Plan

## Context

The original request was to compare this repo’s `.omp/scripts/worktree-flow.py` with `C:/Users/joesa/Code/browser-agent-harness/.omp/scripts/worktree-flow.py`, then integrate the external version’s features into this repo’s canonical script and exported worktree loadout copy. Planning inspection found the three current files already match: `git diff --no-index -- .omp/scripts/worktree-flow.py C:/Users/joesa/Code/browser-agent-harness/.omp/scripts/worktree-flow.py` produced no output, and `git diff --no-index -- .omp/scripts/worktree-flow.py loadouts/worktrees/.harness/scripts/worktree-flow.py` produced no output. The remaining requested behavior is stricter than the external script: remove routine terminal command spam such as `+ (<cwd>) <command>` while keeping useful high-level results, warnings, failure details, and resumability.

## Approach

1. Reconfirm the baseline before editing.
   - From `C:/Users/joesa/Code/harness-loadouts`, run:
     - `git diff --no-index -- .omp/scripts/worktree-flow.py C:/Users/joesa/Code/browser-agent-harness/.omp/scripts/worktree-flow.py`
     - `git diff --no-index -- .omp/scripts/worktree-flow.py loadouts/worktrees/.harness/scripts/worktree-flow.py`
   - If the external diff is empty, treat the external-script feature parity work as already complete and apply only the clean-output edits below.
   - If the external diff is non-empty, first copy the external script behavior into `.omp/scripts/worktree-flow.py`, then apply steps 2–6 on top, then copy the final `.omp/scripts/worktree-flow.py` content to `loadouts/worktrees/.harness/scripts/worktree-flow.py`.

2. Make subprocess echoing quiet by default while retaining an explicit trace mode.
   - In `.omp/scripts/worktree-flow.py`, change `CommandRunner.__init__` to `def __init__(self, dry_run: bool = False, *, verbose: bool = False, command_timeout_seconds: float | None = None) -> None`.
   - Store `self.verbose = verbose` next to `self.dry_run` and `self.command_timeout_seconds`.
   - In `CommandRunner.run()`, keep `display = " ".join(args)` but replace the unconditional `print(f"+ ({cwd}) {display}")` with `if self.verbose or self.dry_run: print(f"+ ({cwd}) {display}")`.
   - This keeps dry-run useful because dry-run has no side effects and must show the commands it would run. Normal execution becomes quiet unless `--verbose` is supplied.
   - Do not change `CommandFailureError`, `format_command_failure()`, or `log_command_result()`: failures must still include command, cwd, stdout, and stderr; JSONL workflow logs must still record command details for debugging without printing every command to the terminal.

3. Reintroduce `--verbose` only as an opt-in command trace flag.
   - In `FlowConfig`, add `verbose: bool` after `keep_worktrees: bool` and before `command_timeout_seconds`.
   - In `build_parser()`, add:
     - `parser.add_argument("--verbose", action="store_true", help="Print each subprocess command before running it.")`
   - In `flow_config_from_args()`, pass `verbose=args.verbose` into `FlowConfig`.
   - In `main()`, construct the runner as `CommandRunner(args.dry_run, verbose=config.verbose, command_timeout_seconds=config.command_timeout_seconds)`.
   - There is only one current `CommandRunner(` callsite in each target file, at `main()`; update that callsite in both target files.

4. Keep the already-cleaned terminal phase banners removed.
   - Do not restore `announce_phase()` or `announce()`.
   - Do not reintroduce prints like `Running harness implementation...`, `Implementation complete.`, `Running harness audit...`, `Audit complete.`, `Integration commit complete.`, fast-forward status chatter, workflow artifact commit chatter, or cleanup chatter.
   - Leave remaining `Implementation` and `Audit` strings only where they are internal labels, prompts, invariant names, or error context, as currently seen around `require_commits_since_base(..., "Implementation")`, `require_clean_except_handoff(..., "Audit")`, and `audit_prompt()`.

5. Preserve the useful terminal output that is not command spam.
   - Keep these normal-run prints:
     - `Feature branch: {names.branch}`
     - `Feature worktree: {names.worktree}`
     - `Handoff archive: {archive_dir}`
     - stop-before-merge output: `Stopped before merge by request.`, `Plan: ...`, `Worktree: ...`, `Branch: ...`
   - Keep warnings printed to stderr for sandbox permission failures and tracked handoff artifacts.
   - Keep FlowError stderr output and resume command output exactly as currently implemented:
     - `print(str(exc), file=sys.stderr)`
     - blank line plus `Resume command:` to stderr
     - two spaces followed by the shell-quoted resume command to stderr

6. Synchronize both required target files.
   - Apply the same final source content to `.omp/scripts/worktree-flow.py` and `loadouts/worktrees/.harness/scripts/worktree-flow.py`.
   - The source text may remain identical even though defaults differ at runtime; `infer_default_harness_dir()` derives `.omp` or `.harness` from the script path.
   - Do not edit or create `loadouts/worktrees/.opencode/scripts/worktree-flow.py`; planning `find` found no such file. If it appears before implementation, update it with the same source content too because repo instructions require exported opencode copies for `.omp/scripts` changes.

## Critical files & anchors

- `.omp/scripts/worktree-flow.py` — `CommandRunner.__init__`, `CommandRunner.run`, `FlowConfig`, `build_parser()`, `flow_config_from_args()`, and `main()` implement the clean-output behavior.
- `loadouts/worktrees/.harness/scripts/worktree-flow.py` — exported worktree loadout copy that must receive the same source edits as `.omp/scripts/worktree-flow.py`.
- `C:/Users/joesa/Code/browser-agent-harness/.omp/scripts/worktree-flow.py` — external comparison source; current planning diff showed it already matches this repo, but it is no longer the final behavior for command echoing because the new requirement is quieter than that script.

## Verification

Run from `C:/Users/joesa/Code/harness-loadouts` after edits:

1. `git diff --no-index -- .omp/scripts/worktree-flow.py loadouts/worktrees/.harness/scripts/worktree-flow.py`
   - Expected: no output and exit code 0.
2. `python .omp/scripts/worktree-flow.py --help`
   - Expected: exits 0 and lists `--verbose` with help text `Print each subprocess command before running it.`
3. `python loadouts/worktrees/.harness/scripts/worktree-flow.py --help`
   - Expected: exits 0, lists `--verbose`, and shows the observed loadout defaults (`Defaults to omp` and `Defaults to .omp`).
4. Behavior check for quiet normal execution:
   - Run `python .omp/scripts/worktree-flow.py --plan C:/path/that/does/not/exist.md --repo .`
   - Expected: exits 1 with `Plan file does not exist: C:/path/that/does/not/exist.md` on stderr and no `+ (` command lines in stdout or stderr.
5. Behavior check for opt-in command tracing:
   - Run `python .omp/scripts/worktree-flow.py --verbose --plan C:/path/that/does/not/exist.md --repo .`
   - Expected: exits 1 and prints at least one `+ (` command line before the missing-plan error because `--verbose` re-enables subprocess tracing.
6. Behavior check for dry-run command tracing:
   - Create or use any existing readable Markdown file outside `docs/scratchpad.md` as the `--plan` argument; do not modify it.
   - Run `python .omp/scripts/worktree-flow.py --dry-run --plan <that-plan.md> --repo . --merge-mode stop`.
   - Expected: exits without making git changes; stdout includes `+ (` command lines because dry-run remains a command preview mode. If the dry-run reaches harness validation and the harness executable is unavailable, the command may exit 1; the expected clean-output assertion is still that dry-run prints `+ (` command lines.

## Assumptions & contingencies

- The prior plan did not satisfy the stricter clean-output requirement because it preserved unconditional subprocess prints. This revised plan makes normal execution quiet by default and keeps `--verbose`/`--dry-run` as explicit trace modes.
- The external script is no longer treated as the complete source of truth for terminal output. It remains the source for already-integrated features such as resume-command printing and removed phase banners, while this plan adds the missing quiet-by-default subprocess behavior.
- If approval-time inspection finds additional normal-run terminal spam besides `+ (<cwd>) <command>`, remove only routine progress/chatter prints. Do not remove warnings, final archive/worktree/branch lines, failure messages, or resume commands.
