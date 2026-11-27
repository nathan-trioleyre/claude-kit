# Stack Profiles

One folder per stack (`python/`, `csharp/`, `angular/`...), created by `/claude-kit`
the first time it encounters the stack, then reused on subsequent projects.

Each profile contains:
- `profile.json`: script-readable data (detection, commands, permissions,
  formatting rules, optional `paths` for `.claude/rules/<stack>.md`, optional
  `tooling` conflict detection, sources, last verified date).
- `practices.md`: summarized best practices (copied into `CLAUDE.md` or
  `.claude/rules/<stack>.md` when scoped paths are set).

Rules:
- A profile is only saved after validation (`apply.py validate`) and your approval.
- Every profile cites its sources (official docs preferred).
- A profile older than 90 days is considered stale: `/claude-kit-refresh <stack>`.
- Copy `_TEMPLATE/` to write one manually.

## `tooling` (optional): coexisting with what a project already has

Declares, per concern (`formatter`, `linter`, `package-manager`...), the tool the kit prefers
(`kit`) and known `alternatives`. When a project already uses an alternative, `apply.py` withholds
the kit's overlapping rules until the user decides (`keep_existing`, `adopt_kit`, `keep_both`).

- `kit`: `name`, `markers` (what reveals the kit's tool), `commands` (command keys it owns),
  `format_rules` (true if it owns the formatting rule), `permissions` (rules it owns),
  `practice_terms` (practice lines mentioning them are dropped when the existing tool is kept).
- `alternatives[]`: `name`, `markers` (`{"file": glob, "contains": text}`), `hooks` (words that reveal
  a hand-made hook), and optional replacements used when kept: `commands`, `permissions_allow`,
  `format_rule`. Only add replacements you are sure of.
