## Rules

- Treat `docs/scratchpad.md` as private scratch space. Do not read, search, open, modify, diff, summarize, or quote it. If it appears in broad file listings or git status output, ignore it.
- When plan mode is active, use the `ask` tool every time before producing a plan. Ask any clarifying questions needed, or ask the user to confirm that no clarification is needed.
- Before performing any edit, briefly state in chat what files or behavior you intend to change and why. Do not wait for approval.
- Every Markdown plan file must start with a single descriptive H1 (`# ...`) before any `##` sections. Use the H1 as a stable, filesystem-safe worktree-flow title, not a generic label like `Plan`; `worktree-flow.py` derives branch, worktree, staging, and archive names from that header.
