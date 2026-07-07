# OMP Repo Init Prompt

Initialize this repository for effective OMP coding-agent work. Work directly in the current repository. Optimize for correctness, maintainability, and minimal durable configuration. Do not create mocks, stubs, placeholder skills, or speculative settings. Do not store secrets in committed files.

Do not create, update, rewrite, delete, or otherwise touch `AGENTS.md`. Treat it as user-owned instruction state.

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

## 3. Create new repo-specific OMP skills

Use `web_search` and official sources based on this repo's actual stack to choose high-leverage skills. Prefer official framework/database/cloud/security/testing docs and source-backed guidance over blog posts. New skills should cover the repo's real work, not generic categories.

Do not update, overwrite, delete, rename, or rewrite existing `.omp/skills/*/SKILL.md` files. Existing skills are user-owned state. If existing skills are stale, generic, overlapping, or incomplete, leave them unchanged and mention the issue in the final response. Add only new skill directories/files for missing repo-specific coverage.

For each new skill:

- create `.omp/skills/<skill-name>/SKILL.md` using one directory per skill;
- include frontmatter with exact `name` and a specific `description` that explains when to use it;
- write concise workflow guidance tailored to this repository;
- include commands, files, invariants, and verification checks only when they are confirmed for this repo;
- keep supporting references under the same skill directory when needed, so `skill://<skill-name>/...` works;
- avoid duplicate or overlapping new skills; merge overlaps into the sharper new skill.

Good default coverage to consider, only when the repo justifies a new skill: primary framework, language/runtime, database/storage, auth/security, test strategy, deployment/ops, UI/design system, performance, code review, release/publish readiness.

## 4. Leave repo instruction files untouched

Do not edit repo instruction files as part of initialization. In particular, never create, update, rewrite, delete, or otherwise touch `AGENTS.md`. If OMP-specific guidance is missing from existing instruction files, mention that in the final response instead of changing those files.

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
