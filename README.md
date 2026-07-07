# Harness Loadouts

Reusable configuration templates for AI coding harnesses. A loadout packages AGENTS.md, `.harness/` skills/scripts/config, and other repo-local files so you can apply a consistent setup across projects with one command.

## Quick Start

```powershell
# 1. Clone this repo
git clone <repo-url> && cd harness-loadouts

# 2. Create a loadout (see examples/ for reference)
mkdir loadouts/my-loadout
# Add AGENTS.md, .harness/skills, scripts, hooks, agents, commands, or other files

# 3. Apply it to a repo; -Harness is required
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness codex
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness opencode
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness claude
.\harness-init.ps1 -Loadout my-loadout -Target C:\path\to\repo -Harness omp

# Reapply a changed loadout to every repo recorded for it
.\update-loadout-repos.ps1 -Loadout my-loadout

# List available loadouts and supported harnesses
.\harness-init.ps1 -List
```

## Init Prompts

Reusable repo-initialization prompts live in `init-prompts/`. They are source templates, not loadout payloads, so loadout application does not copy them into target repos. Use them when a target repo needs discovery-driven setup before or after applying a loadout.

Run an init prompt headlessly with OMP:

```powershell
.\harness-init.ps1 -Target C:\path\to\repo -InitPrompt omp-repo-init -Headless
```

Headless init is hard-coded to OMP. It writes run artifacts under the target repo's `.omp/init/`, and the runtime prompt instructions require the follow-up report under `.omp/init/reports/`.

## Harness Conventions

Loadout templates are harness-agnostic:

| Template path       | Applied target path   |
| ------------------- | --------------------- |
| `AGENTS.md`         | `AGENTS.md`           |
| `.harness/skills/`  | `.<harness>/skills/`  |
| `.harness/scripts/` | `.<harness>/scripts/` |
| `.harness/...`      | `.<harness>/...`      |

The selected `-Harness` value controls the target config directory. For example, `-Harness codex` maps `.harness/` to `.codex/`; `-Harness opencode` maps it to `.opencode/`.

Anything else in a loadout is copied recursively at the matching path. This includes `.git/hooks/`, local docs, and other support files.

## How It Works

- `-Harness` is required so the script never guesses the target harness.
- `AGENTS.md` is appended to any existing target file with a dated separator, or copied fresh if none exists.
- Skills are copied recursively into the selected harness directory.
- Known harness hook/config files are merged by hook event where possible while preserving existing target settings.
- Existing files prompt before overwrite.
- Successful applies record `<target path, harness, last applied time>` by loadout in `applied-repos.json` at the harness repo root.
- The root registry is outside `loadouts/`, so loadout apply never copies it into targets.
- `update-loadout-repos.ps1` replays recorded repositories with `-Force`, warning and continuing for missing repos.

Earlier versions included a deprecated `claude-init.ps1` wrapper. Use `harness-init.ps1` directly.

## License

MIT
