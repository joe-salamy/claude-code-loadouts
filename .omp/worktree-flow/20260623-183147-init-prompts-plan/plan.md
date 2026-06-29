# Init Prompts Plan

## Context

Create a repo-owned place for reusable repository initialization prompts and add one direct-execution OMP bootstrap prompt. The user chose root-level `init-prompts/` because these prompts are not necessarily tied to a loadout, and chose direct execution rather than plan-first behavior. The intended end state is: root prompt storage is documented, `harness-init.ps1` loadout-copy behavior remains unchanged, and `init-prompts/omp-repo-init.md` gives an agent exact instructions to make a target repo OMP-ready: concise README, curated skills, LSP setup, repo instructions, and verification.

## Approach

1. Add root prompt storage as source-only repository content.
   - Create `init-prompts/README.md` with this exact content:

     ```markdown
     # Init Prompts

     Reusable prompts for initializing target repositories. These are source templates, not loadout payloads: `harness-init.ps1` only applies files under `loadouts/<name>/`.

     Use root prompts when the prompt can inspect a target repo and decide what README, skills, LSP, or OMP setup it needs independently of any one loadout. Put a prompt inside a loadout only when it must ship with files from that loadout.

     - `omp-repo-init.md` — direct-execution prompt for preparing a repository for OMP coding-agent work.
     ```

   - Update `README.md` after the Quick Start block, before `## Harness Conventions`, with this concise section:

     ```markdown
     ## Init Prompts

     Reusable repo-initialization prompts live in `init-prompts/`. They are source templates, not loadout payloads, so `harness-init.ps1` does not copy them into target repos. Use them when a target repo needs discovery-driven setup before or after applying a loadout.
     ```

   - Do not modify `harness-init.ps1`: current behavior reads `$LoadoutsDir = Join-Path $ScriptRoot "loadouts"` and copies only children of `loadouts/<Loadout>`; root `init-prompts/` should remain independent of loadout application. If an implementer finds an existing `init-prompts/` folder, keep it at repo root, update its README to the text above, and replace/add only `omp-repo-init.md` from step 2.

2. Add the direct-execution OMP bootstrap prompt.
   - Create `init-prompts/omp-repo-init.md` with this exact content:

     ```markdown
     # OMP Repo Init Prompt

     Initialize this repository for effective OMP coding-agent work. Work directly in the current repository. Optimize for correctness, maintainability, and minimal durable configuration. Do not create mocks, stubs, placeholder skills, or speculative settings. Do not store secrets in committed files.

     ## 1. Discover before editing

     - Read existing repo instructions, README files, package manifests, build/test config, harness config, and the main source tree before changing files.
     - Preserve existing conventions. Do not introduce a second convention beside an existing one.
     - Identify the primary languages, frameworks, package managers, test commands, lint/typecheck commands, deployment/runtime shape, and any existing `.omp/`, `.harness/`, `.codex/`, `.claude/`, `.opencode/`, or `.agents/` assets.
     - If a fact is not discoverable from files or official docs, do not invent it; leave it out or state the exact missing prerequisite in the final response.

     ## 2. Make the README concise and useful

     Create or update `README.md` so a new contributor can run the project without reading the whole repo. Keep it short. Include only confirmed facts:

     - what the project does;
     - prerequisites;
     - setup/install commands;
     - run/develop commands;
     - test, lint, typecheck, and format commands;
     - required environment variables by name only, with no secret values;
     - any OMP-specific notes needed to work in this repo.

     Remove stale or duplicated README content. Do not add marketing copy.

     ## 3. Curate 5-10 repo-specific OMP skills

     Use `web_search` and official sources based on this repo's actual stack to choose 5-10 high-leverage skills. Prefer official framework/database/cloud/security/testing docs and source-backed guidance over blog posts. The final skill set should cover the repo's real work, not generic categories.

     For each selected skill:

     - create `.omp/skills/<skill-name>/SKILL.md` using one directory per skill;
     - include frontmatter with exact `name` and a specific `description` that explains when to use it;
     - write concise workflow guidance tailored to this repository;
     - include commands, files, invariants, and verification checks only when they are confirmed for this repo;
     - keep supporting references under the same skill directory when needed, so `skill://<skill-name>/...` works;
     - avoid duplicate or overlapping skills; merge overlaps into the sharper skill.

     Good default coverage to consider, only when the repo justifies it: primary framework, language/runtime, database/storage, auth/security, test strategy, deployment/ops, UI/design system, performance, code review, release/publish readiness.

     ## 4. Add repo instructions for OMP skill usage

     Ensure the repo instruction file (`AGENTS.md` when present, otherwise create it) contains concise OMP guidance:

     - when loading any skill, record the load with `python ./.omp/scripts/skill-usage-manager.py record <skill-name> --scope repo --path ./.omp/skills --repo .` if `.omp/scripts/skill-usage-manager.py` exists;
     - read `skill://<skill-name>` before following a skill;
     - prefer repo-local commands from the README or package manifests;
     - never commit secrets or generated cache artifacts.

     If a different instruction file already owns this policy, update that file instead of duplicating it.

     ## 5. Set up OMP LSP support

     OMP auto-detects language servers when matching root markers exist and the server binary is available. Project-specific LSP overrides belong in `<repo>/.omp/lsp.json`; project settings belong in `<repo>/.omp/config.yml` only when overriding defaults.

     - Detect the repo's primary language servers from manifests and source files.
     - Prefer OMP built-ins when applicable: `typescript-language-server`, `denols`, `eslint`, `biome`, `pyright`, `basedpyright`, `pylsp`, `ruff`, `rust-analyzer`, `gopls`, `clangd`, `vscode-json-language-server`, `yamlls`, and the other built-ins documented by OMP.
     - If a matching built-in server will auto-detect because the root marker and binary already exist, do not create `.omp/lsp.json` just to restate defaults.
     - If the server binary is missing and the ecosystem supports repo-local dev tools, add the minimal repo-local dev dependency using the repo's package manager; do not install global tools.
     - If the repo needs an override, create `.omp/lsp.json` with a `servers` object. New custom server entries must include `command`, `fileTypes`, and `rootMarkers`; never set `resolvedCommand`.
     - Keep `lsp.enabled`, `lsp.lazy`, and `lsp.diagnosticsOnWrite` at their defaults unless the repo has a proven reason to override them.

     ## 6. Set up only useful OMP project config

     - Ensure `.omp/` exists when adding OMP assets.
     - Create `.omp/config.yml` only for repo-specific overrides that are actually needed. Do not restate OMP defaults.
     - Keep credentials out of `.omp/config.yml`; document required env vars in `README.md` instead.
     - If the repo needs MCP servers, hooks, or custom commands, add the smallest repo-local config that is required for the observed workflow and document how to verify it.

     ## 7. Verify end to end

     Run the focused checks that prove the setup works:

     - README commands that are safe in the current environment;
     - package manager install/update check if dependencies changed;
     - relevant test/lint/typecheck commands discovered from the repo;
     - OMP LSP diagnostics or an equivalent language-server smoke check for the primary language;
     - a final file review confirming the skill count is 5-10, each skill has frontmatter, `.omp/lsp.json` is absent unless needed, and no secrets were written.

     In the final response, report files changed, skills created, LSP decision, commands run, and any missing prerequisite that prevented a check.
     ```

   - The prompt intentionally tells the target agent to create `AGENTS.md` only when no existing instruction file owns the policy; this avoids duplicate instruction conventions while still ensuring OMP skill recording is present when `.omp/scripts/skill-usage-manager.py` exists.
   - The prompt intentionally says not to create `.omp/lsp.json` when OMP auto-detection will work. OMP docs state auto-detection needs a matching root marker and available binary, and project-specific overrides belong in `<project>/.omp/lsp.json`.

3. Add a focused regression test for prompt storage and required prompt content.
   - Create `tests/test_init_prompts.py` with this exact content:

     ```python
     from __future__ import annotations

     from pathlib import Path


     ROOT = Path(__file__).resolve().parents[1]
     INIT_PROMPTS = ROOT / "init-prompts"


     def test_init_prompts_are_source_templates() -> None:
         readme = (INIT_PROMPTS / "README.md").read_text(encoding="utf-8")

         assert "source templates, not loadout payloads" in readme
         assert "harness-init.ps1" in readme
         assert "omp-repo-init.md" in readme


     def test_omp_repo_init_prompt_contains_required_bootstrap_steps() -> None:
         prompt = (INIT_PROMPTS / "omp-repo-init.md").read_text(encoding="utf-8")

         required_phrases = (
             "Create or update `README.md`",
             "Use `web_search`",
             "5-10 high-leverage skills",
             ".omp/skills/<skill-name>/SKILL.md",
             "python ./.omp/scripts/skill-usage-manager.py record <skill-name> --scope repo --path ./.omp/skills --repo .",
             "<repo>/.omp/lsp.json",
             "do not create `.omp/lsp.json` just to restate defaults",
             "Do not store secrets in committed files",
         )
         for phrase in required_phrases:
             assert phrase in prompt
     ```

   - This test verifies the new repository behavior: reusable init prompts exist as source templates, and the OMP prompt preserves the README, web-search skill curation, skill layout, skill usage recording, LSP, and no-secrets requirements.

4. Do not change loadout-copy behavior or OMP worktree scripts.
   - Do not edit `harness-init.ps1`, `.omp/scripts/worktree-flow.py`, `.omp/scripts/save-plan.py`, `.omp/scripts/skill-usage-manager.py`, or their exported copies under `loadouts/worktrees/.harness/scripts/` for this task.
   - If execution unexpectedly requires a script change, mirror the same script change into `loadouts/worktrees/.harness/scripts/` and run `tests/test_worktrees_loadout_sync.py`; otherwise, leave scripts untouched.

## Critical files & anchors

- `README.md` lines 5-25 — insert the concise `## Init Prompts` section after Quick Start and before Harness Conventions.
- `harness-init.ps1` lines 23-24 and 431-452 — confirms loadout application is rooted at `loadouts/` and copies only loadout children; root `init-prompts/` should not be added to this flow.
- `omp://lsp-config.md` — OMP LSP facts used by the prompt: auto-detection requirements, `<project>/.omp/lsp.json`, `servers` object, required server fields, and built-in server names.
- `omp://skills.md` — OMP skill layout facts used by the prompt: one-level `<skills-root>/<skill-name>/SKILL.md`, explicit name/description frontmatter, and `skill://<name>/...` references.
- `tests/test_harness_init.py` and `tests/test_worktrees_loadout_sync.py` — existing verification anchors if implementation touches loadout behavior or worktree scripts; normal implementation should only add `tests/test_init_prompts.py`.

## Verification

Run from repository root after implementation:

```powershell
python -m pytest tests/test_init_prompts.py
```

Expected result: both new tests pass, proving `init-prompts/README.md` documents source-template behavior and `init-prompts/omp-repo-init.md` contains all required bootstrap instructions.

Also run:

```powershell
python -m pytest tests/test_harness_init.py tests/test_worktrees_loadout_sync.py
```

Expected result: existing loadout initialization and active/exported worktree script sync still pass. This matters because the plan intentionally keeps `init-prompts/` outside `harness-init.ps1` and does not change `.omp/scripts/`.

Manual review checklist:

- `README.md` has a short `## Init Prompts` section and remains concise.
- `init-prompts/README.md` says prompts are source templates, not loadout payloads.
- `init-prompts/omp-repo-init.md` is direct-execution phrasing, not plan-first phrasing.
- The prompt instructs: concise README, web-search-backed 5-10 skills, `.omp/skills/<skill-name>/SKILL.md`, skill usage record command, OMP LSP setup via auto-detect first and `.omp/lsp.json` only when needed, no secrets, and concrete verification.

## Assumptions & contingencies

- Root `init-prompts/` is the chosen storage model. If a future prompt is truly coupled to copied files from one loadout, put that future prompt under that loadout; do not move this generic OMP prompt.
- This task is content and tests only. If an implementer discovers an existing script behavior that already copies root `init-prompts/`, stop and update the plan before changing behavior; current inspected `harness-init.ps1` does not do that.
- OMP LSP setup in the prompt follows OMP docs read during planning: defaults auto-detect common servers; project overrides use `<project>/.omp/lsp.json`; project settings use `<project>/.omp/config.yml` only for real overrides.
