# Stack Profiles

One folder per stack (`python/`, `csharp/`, `angular/`...), created by `/claude-kit`
the first time it encounters the stack, then reused on subsequent projects.

Each profile contains:
- `profile.json`: script-readable data (detection, commands, permissions,
  formatting rules, optional `paths` for `.claude/rules/<stack>.md`, sources,
  last verified date).
- `practices.md`: summarized best practices (copied into `CLAUDE.md` or
  `.claude/rules/<stack>.md` when scoped paths are set).

Rules:
- A profile is only saved after validation (`apply.py validate`) and your approval.
- Every profile cites its sources (official docs preferred).
- A profile older than 90 days is considered stale: `/claude-kit-refresh <stack>`.
- Copy `_TEMPLATE/` to write one manually.
