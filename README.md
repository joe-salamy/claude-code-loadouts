# Claude Code Loadouts

Reusable configuration templates for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) projects. A loadout packages up a CLAUDE.md, skills, hooks, and other files so you can apply a consistent setup across repos with one command.

## Quick Start

```powershell
# 1. Clone this repo
git clone <repo-url> && cd _loadouts

# 2. Create a loadout (see examples/ for reference)
mkdir loadouts/my-loadout
# Add a CLAUDE.md, skills, hooks — whatever you need

# 3. Apply it to a repo
.\claude-init.ps1 -Loadout my-loadout -Target C:\path\to\repo

# List available loadouts
.\claude-init.ps1 -List
```

## What Goes in a Loadout

| What          | Where to put it                                                 |
| ------------- | --------------------------------------------------------------- |
| CLAUDE.md     | `loadouts/<name>/CLAUDE.md`                                     |
| Skills        | `loadouts/<name>/.claude/skills/<skill-name>/SKILL.md`          |
| Hooks         | `loadouts/<name>/.claude/settings.local.json` (or `hooks.json`) |
| Anything else | Drop it in `loadouts/<name>/` at the matching path              |

A loadout with just a `CLAUDE.md` is perfectly valid.

## How It Works

- **CLAUDE.md** is appended to any existing CLAUDE.md in the target (with a dated separator), or copied fresh if none exists.
- **Skills** are copied recursively into `.claude/skills/`.
- **Hooks** from `settings.local.json` are merged — only the `hooks` key is updated, existing `permissions` are preserved.
- **Everything else** (e.g., `.git/hooks/`) is copied as-is into the target.

## Hooks Format

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "bash .git/hooks/my-hook.sh" }
        ]
      }
    ]
  }
}
```

See [Claude Code hooks docs](https://docs.anthropic.com/en/docs/claude-code/hooks) for full syntax.

## License

MIT
