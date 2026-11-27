# org/ — optional company-wide layer

Everything here is applied to **every** project configured with the kit, between `base/` and the stack profiles.
It is additive: it can add rules, permissions and files, never remove what `base/` or the project already has.
Delete the files you do not need; an empty `org/` does nothing.

| File / folder | Effect in the project |
|---|---|
| `rules.md` | Appended to the "Mandatory Rules" section of `CLAUDE.md` (plain markdown bullet lines). |
| `settings.json` | Extra `permissions.allow` / `permissions.deny` and `hooks`, merged into `.claude/settings.json`. Same shape as `base/settings.base.json`. |
| `mcp.json` | `{"mcpServers": {...}}`, merged into the project's `.mcp.json`. Existing server names are never overwritten. Never put secrets here: use `${ENV_VAR}` references. |
| `agents/*.md` | Copied to `.claude/agents/` (sub-agents), without overwriting. |
| `commands/*.md` | Copied to `.claude/commands/` (slash commands), without overwriting. |

`base/agents/` and `base/commands/` work the same way for things that belong to every project, whoever the company is.

Apply to projects with `/claude-kit` (first time) or `/claude-kit sync` (afterwards). Skip the layer with `--no-org`.
