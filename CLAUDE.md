## Overview

Loadout management system for Claude Code projects. A loadout is a reusable config package (CLAUDE.md, skills, hooks, other files) applied to target repos via `.\claude-init.ps1 -Loadout <name> -Target <repo>`. Loadout templates live in `loadouts/`. The script supports deduplication: hooks are merged per-event, skills prompt before overwriting, and CLAUDE.md skips duplicate appends.

## Git & Commits

- Read `.gitignore` before running any git commit to know what files to exclude.

## Off-Limits Files

- Never read from, write to, or git diff `scratchpad.md`.

## Plan Mode

- When asking clarifying questions in plan mode, be liberal; when in doubt, ask more rather than fewer.

## Documentation

- Keep READMEs concise.
