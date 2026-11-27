# Stack Profiles

One folder per stack (`python/`, `csharp-dotnet/`, `angular/`, …), created by `/claude-kit` the first time it encounters a stack, then reused across subsequent projects.

Each profile contains:
- `profile.json`: machine-readable metadata (detection globs, commands, permissions, format rules, optional `paths` for `.claude/rules/<stack>.md`, optional `supersedes`, optional `tooling` conflict detection, sources, `last_verified` date).
- `practices.md`: summary of **timeless** stack best practices (max 15 lines; copied into `CLAUDE.md` or `.claude/rules/<stack>.md` when paths are defined).
- `versions/<ver>.md` *(optional)*: rules specific to a major version (max 8 lines, e.g., `versions/11.md`, `versions/21.md`), created on demand and injected automatically when `stack_versions` matches.

Rules:
- A profile is only saved after validation (`apply.py validate`) and your approval.
- Every profile cites its sources (official documentation preferred).
- A profile older than 90 days is flagged as stale: `/claude-kit-refresh <stack>`.
- Copy `_TEMPLATE/` to author one by hand.

## `tooling` (optional): coexisting with existing project tools & presets

Declares, per concern (`formatter`, `linter`, `typechecker`, `package-manager`, …), the kit's preferred tool (`kit`) and known `alternatives`. When a project already uses an alternative, `apply.py` withholds overlapping kit rules until the user decides (`keep_existing`, `adopt_kit`, `keep_both`, or `skip`). When neither `kit` nor an alternative is detected and `kit` defines a preset, `audit` reports it in `missing_tooling`.

- `kit`: `name`, `markers` (what reveals the kit tool), `commands` (command keys it owns), `format_rules` (true if it owns the format rule), `permissions` (rules it owns), `practice_terms` (practice lines mentioning them are withheld when keeping/skipping), plus optional preset fields: `preset_files` (`{"src": "presets/...", "dest": "...", "mode": "create|snippet"}`), `install_packages` (list or per-package-manager map), `scripts` (`package.json` script map), `post_edit_check` (fast single-file lint rule for `PostToolUse`), and `only_when_installed` (true if active only once markers exist).
- `alternatives[]`: `name`, `markers` (`{"file": glob, "contains": text}`), `hooks` (keywords revealing a hand-made hook), and optional replacements used when keeping the tool: `commands`, `permissions_allow`, `format_rule`, `post_edit_check`. Optional (may be empty) when `kit` declares presets.
- Top-level `verify_steps` *(optional)*: ordered `[{"cmd": "...", "concern": "<concern>|null"}]` so `apply.py` can drop only a skipped concern's verify step.
