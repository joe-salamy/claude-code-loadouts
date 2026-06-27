## Overview

Loadout management system for AI coding harness projects. A loadout is a reusable config package (AGENTS.md, CLAUDE.md, skills, hooks, other files) applied to target repos via `.\harness-init.ps1 -Loadout <name> -Target <repo>`. Loadout templates live in `loadouts/`. The script supports deduplication: hooks are merged per-event, skills prompt before overwriting, and instruction files skip duplicate appends.

## Rules

- Treat `docs/scratchpad.md` as private scratch space. Do not read, search, open, modify, diff, summarize, or quote it. If it appears in broad file listings or git status output, ignore it.
- When plan mode is active, use the `ask` tool every time before producing a plan. Ask any clarifying questions needed, or ask the user to confirm that no clarification is needed.
- Before performing any edit, briefly state in chat what files or behavior you intend to change and why. Do not wait for approval.

## Misc

- Keep canonical Oh My Pi tooling scripts in `.omp/scripts/`.
- When changing any script in `.omp/scripts/`, copy the same change to the exported opencode loadout copy in `loadouts/worktrees/.opencode/scripts/`.
