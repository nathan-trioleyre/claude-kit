---
name: claude-kit
description: Configures Claude Code for the current project (CLAUDE.md, modular rules, permissions, security and formatting hooks) by detecting the stack, then reusing or creating a stack profile in claude-kit. Use when the user types /claude-kit, lands on a new or existing project, or asks to set up Claude for a project.
disable-model-invocation: true
---

# /claude-kit: prepare Claude Code for this project

You are configuring the current project from the user's **claude-kit** repository.

**Division of labor (important):**
- The `apply.py` script handles everything mechanical that must stay identical across projects: detecting known profiles, validating profiles, copying hooks, merging `settings.json`, and generating `CLAUDE.md` / `.claude/rules/*.md`.
- **You** handle what a script cannot do: understanding the project, creating or updating stack profiles from official documentation, and writing the real architecture, gotchas, and monorepo `rule_paths`.

Only write into the project through `apply.py` (except when merging a user-approved `.proposed` file, Step 5).

## Step 0: locate the kit

Use `Read` on `~/.claude/claude-kit.json` (or `~/.claude/claude-bootstrap.json` for older installs) to get `kit_path` and `python`.

If neither file exists: tell the user to run `python install.py` from the kit directory, and stop.

Hereafter:
- `KIT` = `kit_path`
- `PY` = `python` from the config (or a working `python3`/`python`/`py -3`)
- `APPLY` = `PY "KIT/skills/claude-kit/scripts/apply.py"`

## Step 1: understand the project (read-only)

1. List the root directory and read files that reveal the stack and real commands: `pyproject.toml`, `requirements*.txt`, `*.sln`, `*.csproj`, `package.json`, `angular.json`, `tsconfig.json`, `Makefile`, CI workflows (`.github/workflows`, `azure-pipelines.yml`...), `README`.
2. Check if a `CLAUDE.md` or `.claude/` directory already exists: they must be respected, never overwritten.
3. Run `APPLY detect --project .` to see which known profiles match (scans up to depth 5 while pruning `node_modules`/`.venv`/etc.).
4. List **all** stacks in the project (an Angular + C# monorepo has two), including those without a profile yet.
5. Note the project's **actual commands** (`package.json` scripts, `Makefile`, CI) and subproject directories for monorepos. Project commands take precedence over profile defaults.

## Step 2: one profile per stack

Run `APPLY list`, then for each stack in the project:

- **Existing and recent profile** (`stale: false`): use it as-is without re-researching.
- **Existing but stale profile** (`stale: true`, older than 90 days): tell the user and offer to refresh it now (`/claude-kit-refresh` procedure) or continue with the old one.
- **No profile**: create it.
  1. Search official documentation using `WebSearch` and `WebFetch` for **current** best practices (language, framework, tools). Tailor to what the project actually uses (e.g., `uv` or `poetry`, framework version read from the manifest).
  2. Write `profile.json` and `practices.md` following `KIT/profiles/_TEMPLATE/`. Constraints:
     - stack name in lowercase, no spaces (`python`, `csharp-dotnet`, `angular`);
     - `permissions_allow`: specific commands only (`Bash(pytest *)`), never `Bash(*)`, never deletions or remote script installation;
     - `practices.md`: 15 lines maximum, one practice per line, concrete and verifiable, no vague generalities;
     - `sources`: the URLs actually consulted; `last_verified`: today's date.
  3. Run `APPLY validate --profiles <stack>` and fix any schema errors.
  4. **Show the full profile to the user and wait for approval.** Only save it into `KIT/profiles/<stack>/` after approval. If they reject or edit it, apply their corrections and re-validate.

## Step 3: prepare the project context

Build the context JSON object:

```json
{
  "name": "project name",
  "description": "1 to 2 sentences on what the project does",
  "architecture": "5 to 10 markdown lines: entry point, main folders, data flow",
  "gotchas": "only real gotchas observed in the code or config",
  "commands_override": { "<stack>": { "test": "actual project command" } },
  "rule_paths": { "<stack>": ["apps/api/**"] }
}
```

- Only fill in what you actually read in the code. If you don't know, omit the key: the script inserts `_To be completed._`. Never guess or invent.
- Include `"rule_paths"` only for multi-stack monorepos when you want stack practices written into path-scoped `.claude/rules/<stack>.md` files instead of inline in `CLAUDE.md`.
- Pass the JSON via stdin using `--context -` (preferred, leaves no temp file) or a temp file outside the project.

## Step 4: dry run

Run `APPLY apply --project . --profiles <stacks...> --context - --dry-run` (omit `--profiles` if no stack profile applies yet).

Summarize the result in plain English (what will be created, merged, upgraded, or skipped, plus any unified diff shown for existing files) and ask the user for confirmation.

## Step 5: apply

Re-run the same command without `--dry-run`.

If any `.proposed` file was created (`CLAUDE.md.proposed` or `.claude/rules/<stack>.md.proposed`), an existing file was already present. Compare the two, explain useful differences, and offer to merge missing sections into the existing file **without deleting user content**. Only do so with the user's approval, then delete the `.proposed` file.

## Step 6: wrap up

Provide a brief summary:
- what was created or modified in the project (ready to commit);
- any new profile saved to the kit (ready to commit in the kit repo: `git -C KIT status`);
- any `CLAUDE.md` sections still marked `_To be completed._`;
- a reminder: restart the Claude Code session so hooks are loaded, and verify with `/hooks`.

## Rules

- Ask only one question at a time.
- Never modify files in `KIT/base/` (hooks, base settings): if you think a change is needed, propose it to the user.
- Never save an unapproved or unvalidated profile.
- No secrets in generated files.
- If no working Python 3 interpreter is available, tell the user: hooks and `apply.py` depend on it.
