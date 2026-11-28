---
name: claude-kit
description: Configures Claude Code for the current project (CLAUDE.md, rules, permissions, hooks) by detecting its stack and reusing a claude-kit profile; also runs doctor, sync, and uninstall.
disable-model-invocation: true
argument-hint: "[local | doctor | sync | uninstall]"
---

# /claude-kit: prepare Claude Code for this project

You are configuring the current project from the user's **claude-kit** repository.

**Division of labor (important):**
- The `apply.py` script handles everything mechanical that must stay identical across projects: detecting known profiles, validating profiles, copying hooks, merging `settings.json`, and generating `CLAUDE.md` / `.claude/rules/*.md`.
- **You** handle what a script cannot do: understanding the project, creating or updating stack profiles from official documentation, and writing the real architecture, gotchas, and monorepo `rule_paths`.

Before modifying an existing `settings.json` / `settings.local.json`, the script writes a `<name>.bak` backup next to it. Memory: Claude Code's native auto-memory covers it; the kit generates no root `MEMORY.md` (`/handoff` writes `.claude/handoff.md` instead).

Only write into the project through `apply.py`, except when merging a user-approved `.proposed` file (Step 5), applying user-approved TOML manifest snippets or running approved package installs (Step 3c), or carrying out a user-approved migration plan (Step 3b).

**Existing setups are never overridden silently.** If the project already has its own CLAUDE.md, hooks, formatter, linter or package manager, Step 1b detects it and Step 3b has the user decide, one conflict at a time. Until a decision is recorded, the script withholds the kit's overlapping rules. If a project has **no** linter/formatter configured yet, Step 3c offers the profile's strict preset (plus optional `.editorconfig` and `.githooks/pre-commit`) before `apply.py apply`.

**Modes** (from `$ARGUMENTS`):
- empty: full setup, Steps 0 to 6 below.
- `local`: full setup in stealth/personal mode for shared team repositories (pass `--local` to `APPLY apply`). Writes `CLAUDE.local.md` and `.claude/settings.local.json`, records exclusions in `.git/info/exclude`, and never touches `.gitignore`, team `CLAUDE.md`, or team `.claude/settings.json`. Later `sync` and `doctor` remember this mode automatically.
- `doctor`: Step 0, then run `APPLY doctor --project .` and explain each `ISSUE` in plain English. Then propose the right fix: `sync` for outdated hooks/settings, a full `/claude-kit` for new stacks or refreshed profiles, Step 3b for a `tooling conflict`, and Step 3b (option "adopt the kit") to finish a migration reported as `finish the migration`. Write nothing yourself.
- `uninstall`: Step 0, then `APPLY uninstall --project . --dry-run`, summarize, ask for confirmation, re-run without `--dry-run`. It removes unmodified kit-managed files, kit hooks, kit-added permissions, kit ignore lines and `kit.json`; `CLAUDE.md`, `CLAUDE.local.md` and `.claude/rules/` are left for manual review (tell the user).
- `sync`: Step 0, then `APPLY sync --project . --dry-run`, summarize, ask for confirmation, re-run without `--dry-run`. This refreshes kit-managed files only (settings, hooks, agents/commands/rules/skills, `.mcp.json`, `kit.json`); `CLAUDE.md` is not touched. Recorded tooling decisions are respected; a new undecided conflict is reported (`! CONFLICT`): resolve it with Step 3b (`APPLY decide`, then `sync`). If a hook is reported `skipped ... modified locally`, show the diff against the kit's copy and ask before using `--force-hooks`.

## Step 0: locate the kit

Use `Read` on `~/.claude/claude-kit.json` to get `kit_path` and `python`. (The other kit skills reuse this step.)

If it does not exist: tell the user to run `python install.py` (or `python install.py --link`) from the kit directory, and stop.

Hereafter:
- `KIT` = `kit_path`
- `PY` = `python` from the config (or a working `python3`/`python`/`py -3`)
- `APPLY` = `PY "KIT/skills/claude-kit/scripts/apply.py"`

## Step 1: understand the project (read-only)

1. List the root directory and read files that reveal the stack and real commands: `pyproject.toml`, `requirements*.txt`, `*.sln`, `*.csproj`, `package.json`, `angular.json`, `tsconfig.json`, `Makefile`, CI workflows (`.github/workflows`, `azure-pipelines.yml`...), `README`.
2. Check if a `CLAUDE.md` or `.claude/` directory already exists: they must be respected, never overwritten.
3. Run `APPLY detect --project .` to see which known profiles match (scans up to depth 5 while pruning `node_modules`/`.venv`/etc.). It also returns `details` with the directories and suggested `rule_paths` globs for each matched stack.
4. List **all** stacks in the project (an Angular + C# monorepo has two), including those without a profile yet.
5. Note the project's **actual commands** (`package.json` scripts, `Makefile`, CI), subproject directories for monorepos, and **exact stack versions** (e.g., `@angular/core` or `next` in `package.json`, `<TargetFramework>` in `*.csproj`, `requires-python` in `pyproject.toml`). Project commands take precedence over profile defaults.

## Step 1b: audit what already exists (read-only)

Run `APPLY audit --project .` (JSON). It reports:
- `existing`: whether a `CLAUDE.md` exists and its section headings, files in `.claude/` the kit did not install, hooks and permissions in `settings.json` that are not the kit's;
- `tooling`: one entry per concern (formatter, linter, package manager...) where the project already uses a tool the kit's profile does not prefer, with the evidence (config files, hand-made hooks). `status` is `pending` (no decision yet), `resolved`, or `migration_pending` (kit adopted earlier, traces of the old tool remain);
- `missing_tooling`: concerns where neither the kit's markers nor any alternative were detected and the profile provides a strict preset;
- `pending_conflicts`: number of conflicts to settle.

If the project has nothing of its own (`existing` empty, no `tooling` entries), skip Step 3b (still run Step 3c in non-local mode for `missing_tooling`, `.editorconfig`, and `.githooks/pre-commit`).

## Step 1c: FAST PATH (first run, non-`sync`/`doctor`)

After Steps 1 and 1b, show **one** summary table: detected stacks (with/without profile), conflicts with the recommended choice each, missing tooling with the recommended preset, and the files that will be created or proposed. Then ask a single question: **Apply all recommendations / Review one by one / Cancel**.
- **Apply all**: take every recommendation (Step 3b recommended side, `adopt_kit` for accepted missing tooling), skip the per-item questions, and go to Step 4. Migration plans for `adopt_kit` on an existing tool still need explicit approval (Step 3b).
- **Review one by one**: continue with Steps 2 to 3c as written, one question at a time.
- **Cancel**: stop, write nothing.

## Step 2: one profile per stack

Run `APPLY list`, then for each stack in the project:

- **Existing and recent profile** (`stale: false`): use it as-is without re-researching. If the project uses a specific major version and `KIT/profiles/<stack>/versions/<major>.md` does not exist yet, check official docs for that version, write `versions/<major>.md` (8 lines max, version-specific rules only), validate with `APPLY validate --profiles <stack>`, and wait for user approval before saving.
- **Existing but stale profile** (`stale: true`, older than 90 days, which also covers starter profiles shipped unverified): tell the user and offer to refresh it now (`/claude-kit-refresh` procedure) or continue with the old one.
- **No profile**: do NOT research mid-setup. Generate `CLAUDE.md` without a profile (project commands and architecture only), then offer at the end to create the profile afterwards (same flow as `/claude-kit-refresh`: official docs, validate, show, save after approval). Only if the user asks for it right now, create it as follows:
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
  "stack_versions": { "<stack>": "11.2" },
  "rule_paths": { "<stack>": ["apps/api/**"] },
  "decisions": { "<stack>": { "<concern>": "keep_existing | adopt_kit | keep_both | skip" } }
}
```

- `decisions`: the answers from Step 3b, only for concerns the audit listed.
- Only fill in what you actually read in the code. If you don't know, omit the key: the script inserts `_To be completed._`. Never guess or invent.
- Include `"rule_paths"` only for multi-stack monorepos when you want stack practices written into path-scoped `.claude/rules/<stack>.md` files instead of inline in `CLAUDE.md` (you can use the globs suggested by `APPLY detect` in `details`).
- Optional `"stop_verify": false` disables the deterministic `Stop` hook (`verify-stop.py`) for documentation-only or slow repositories (it is enabled by default whenever `verify_command` is non-empty).
- The kit may also contain an optional `org/` layer (company-wide rules, permissions, MCP servers, agents, commands, modular rules, skills, see `org/README.md`). `apply.py` applies it automatically; do not duplicate its content in the context JSON.
- Pass the JSON via stdin using `--context -` (preferred, leaves no temp file) or a temp file outside the project.

## Step 3b: settle each conflict with the user

For every `tooling` entry with status `pending` (and `migration_pending` if the user wants to finish a migration), **one at a time**, show two columns: what the project has now (the tool and its evidence) versus what the kit would put (tool, command, permissions). Recommend one side with a reason (for example: keep the existing tool if it is configured deliberately and CI depends on it; adopt the kit when nothing enforces the old one), then ask. The choices:

- **Keep the existing tool** (`keep_existing`): none of the kit's overlapping rules is applied. The existing tool's known equivalents are used instead, and `CLAUDE.md` says so. Put the project's real commands in `commands_override` (`format`, `lint`, `verify`...) when the profile has no equivalent for them.
- **Adopt the kit's tool** (`adopt_kit`): the kit's tool is configured. Then propose a **migration plan** listing exactly what to remove or change (old config sections, hand-made hooks in `settings.json`, CI steps, dev dependencies) and the one-time reformat of the code base. Show it and wait for approval. This is the only case where you edit project files yourself, limited to the approved plan; recommend committing the reformat on its own so it stays reviewable. Afterwards `APPLY doctor` must no longer report `finish the migration`.
- **Keep both** (`keep_both`): only for tools that do not overlap. Both are applied, nothing is withheld.

Record every answer in the context JSON (Step 3): `"decisions": { "<stack>": { "<concern>": "keep_existing" } }`. They are stored in `.claude/kit.json`, so later `sync` and `doctor` runs do not ask again. To change a decision later: `APPLY decide --project . --profile <stack> --concern <concern> --choice <choice>`, then `APPLY sync --project .` (a migration is only needed when switching to `adopt_kit`).

## Step 3c: offer strict presets for missing tooling (non-local only)

Skip this step completely in `local` mode (`--local` must never modify repo-wide configs).

1. Present **one grouped question** for all `missing_tooling` entries: a table of concern, the kit's strict preset (tool, key AI-guardrail rules, files to create, packages/scripts to add) and a recommendation, then ask: **install all / choose per concern / skip all**. A "missing" concern is withheld by the engine until a decision `adopt_kit` is recorded.
   - **Accepted** (preset installed): record `"decisions": {"<stack>": {"<concern>": "adopt_kit"}}` in the Step 3 context JSON, run `APPLY scaffold-tooling --project . --profile <stack> --concern <concern>`, apply any printed `SNIPPET` to `pyproject.toml`/`Cargo.toml` with user approval, and install the listed `install_packages` using the project's package manager (respecting `guard.py` supply-chain rules).
   - **Declined**: record `"<concern>": "skip"` so its commands, hooks, and `verify` steps stay withheld.
2. If root `.editorconfig` is missing, offer `APPLY scaffold-tooling --project . --base-preset editorconfig`.
3. If no git hook setup (`.husky/`, `.pre-commit-config.yaml`, `lefthook.yml`, `.githooks/`) exists, offer `APPLY scaffold-tooling --project . --base-preset pre-commit` and, if approved, activate it locally with `git config core.hooksPath .githooks`.
4. If the project has no CI (neither a workflow in `.github/workflows/` nor `.gitlab-ci.yml`), offer a CI file for the host of the `origin` remote, generated from the active profiles: `APPLY scaffold-tooling --project . --base-preset ci --ci-provider github|gitlab` (`.github/workflows/ci.yml` or `.gitlab-ci.yml`). Without `--ci-provider` the script detects GitLab only when the remote URL contains `gitlab`, so pass it explicitly for a self-hosted GitLab. For any other host (Bitbucket, Azure DevOps...), skip this offer.

Complete Step 3c **before** Step 4 so `apply.py apply` detects the newly scaffolded markers in one pass.

## Step 4: dry run

Run `APPLY apply --project . --profiles <stacks...> --context - --dry-run` (omit `--profiles` if no stack profile applies yet).

If the dry run shows nothing existing being overwritten or merged (no `.proposed` file, no merge into existing settings) and there are no conflicts, skip the confirmation: go straight to Step 5 and report. Otherwise summarize in plain English (created, merged, upgraded, skipped, plus unified diffs) and ask for confirmation.

## Step 5: apply

Re-run the same command without `--dry-run`.

If any `.proposed` file was created (`CLAUDE.md.proposed` or `.claude/rules/<stack>.md.proposed`), an existing file was already present. The report already lists, section by section, what exists only in the kit's version, only in the user's file, or in both with different content. Go through the differing sections: where the user's file contradicts the kit (a convention, a command), ask which wins, one at a time, consistently with the decisions of Step 3b. Merge missing sections into the existing file **without deleting user content** unless the user chose to replace it. Only do so with the user's approval, then delete the `.proposed` file.

## Step 6: wrap up

Provide a brief summary:
- what was created or modified in the project (ready to commit) and any new profile saved to the kit (`git -C KIT status`); for a stack without profile, offer to create it now;
- any `CLAUDE.md` sections still marked `_To be completed._`;
- restart the Claude Code session so hooks load (verify with `/hooks`); mention `/commit`, `/handoff`, `/review`, and `/claude-kit-learn` if "Lessons Learned" is filled.

## Rules

- Ask one question at a time, except the fast-path question (Step 1c) and the grouped presets question (Step 3c).
- Never modify files in `KIT/base/` (hooks, base settings): if you think a change is needed, propose it to the user.
- Never save an unapproved or unvalidated profile.
- Never remove or replace a tool the project already uses without an explicit `adopt_kit` decision and an approved plan.
- No secrets in generated files.
- Re-running on an already configured project is safe: a customized `CLAUDE.md` is left alone unless the kit's own output changed (then a `.proposed` file is written).
- If no working Python 3 interpreter is available, tell the user: hooks and `apply.py` depend on it.
