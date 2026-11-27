# org/ — optional company layer

Everything here applies to **every** project configured with the kit, between `base/` and stack profiles.
This layer is additive: it can add rules, permissions, and files, never remove what `base/` or the project already have.
Delete the files you don't need; an empty `org/` does nothing.

| File / folder | Effect in the project |
|---|---|
| `rules.md` | Appended to the "Mandatory Rules" section of `CLAUDE.md` (plain markdown bullet lines). |
| `settings.json` | Extra `permissions.allow` / `permissions.deny` and `hooks`, merged into `.claude/settings.json`. Same schema as `base/settings.base.json`. |
| `mcp.json` | `{"mcpServers": {...}}`, merged into the project's `.mcp.json`. Existing server names are never overwritten. Never put secrets here: use `${ENV_VAR}` references. |
| `agents/*.md` | Copied into `.claude/agents/` (subagents), without overwriting. |
| `commands/*.md` | Copied into `.claude/commands/` (slash commands), without overwriting. |
| `rules/*.md` | Copied into `.claude/rules/` (path-scoped modular rules), without overwriting. |
| `skills/<name>/SKILL.md` | Copied into `.claude/skills/<name>/` (on-demand workflows), without overwriting. |

`base/agents/`, `base/commands/`, `base/rules/`, and `base/skills/` work the exact same way for items shared across all projects regardless of company.

Apply changes to projects with `/claude-kit` (initial setup) or `/claude-kit sync` (afterwards). Skip this layer with `--no-org`.
