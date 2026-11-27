# claude-kit

A personal kit that prepares Claude Code for any project (Python, C#, Angular, TypeScript, Next.js, Docker, Rust, and any future stack) with a single command: `/claude-kit`.

## The 30-second overview

When you land on a project, `/claude-kit`:

1. **inspects** the project to understand its stack;
2. **checks** `profiles/` to see if the stack (and its detected major version in `versions/`) is already known;
   - yes → reuses the profile (and version rules) without re-researching;
   - no → reads official documentation, validates and shows the proposed profile (or `versions/<major>.md`), then **saves it into this repository after your approval**;
3. **generates** a `CLAUDE.md` (plus optional path-scoped `.claude/rules/<stack>.md`), permissions, and hooks (safety + formatting + fast post-edit linting) without ever overwriting existing files, and offers strict per-language linter/formatter presets (`.editorconfig`, ESLint, Ruff, Roslyn analyzers, etc.) when a project lacks them.

Afterwards, the kit keeps projects aligned:

| Command | What it does |
|---|---|
| `/claude-kit` | Initial setup (or full re-run) of a project |
| `/claude-kit local` | **Personal, invisible** setup for shared team repos (`CLAUDE.local.md`, `.claude/settings.local.json`, `.git/info/exclude` — never touches `.gitignore`, team `CLAUDE.md`, or team `settings.json`) |
| `/claude-kit doctor` | Reports drift: outdated hooks, missing permissions, stale profiles, new stacks, unfilled `CLAUDE.md` sections, unresolved tooling conflicts |
| `/claude-kit sync` | Refreshes only kit-managed files (settings, hooks, agents/commands/rules/skills, `.mcp.json`); never touches `CLAUDE.md` |
| `/claude-kit-refresh [stack\|all]` | Re-reads official sources for a profile and proposes updates |
| `/claude-kit-learn` | Promotes durable lessons from a project's `CLAUDE.md` back into the kit (profile, `org/`, or `base/`) |

## Projects with an existing setup

On a project that already has its own `CLAUDE.md`, hooks, formatter, linter, or package manager, `/claude-kit` never overrides anything silently:

1. `apply.py audit` inventories what exists and lists **conflicts** between the project's tools and the profile's preferred tools (e.g., `black` in `pyproject.toml` vs the kit's `ruff`, `pnpm-lock.yaml` vs `npm`, or a hand-made formatting hook).
2. For each conflict, you choose one by one: **keep existing** (the kit withholds overlapping commands, permissions, format rules, and practice lines, and uses the existing tool's equivalents), **adopt kit** (Claude proposes a migration plan: old config/hooks to remove, one-time reformat; nothing is touched before your approval), or **keep both**.
3. Your decision is saved in `.claude/kit.json` (`decisions`), so `sync` and `doctor` respect it. `doctor` flags undecided conflicts and half-finished migrations; `apply.py decide` lets you change a decision later.
4. Until you decide, the kit behaves as if you chose to keep the existing tool.
5. An existing `CLAUDE.md` is compared section by section (only in kit / only in yours / different) before any merge.

Conflict detection is driven by the optional `tooling` section in each profile (see [profiles/README.md](profiles/README.md)).

## Layers (5-layer model)

`base/` (all projects) → `org/` (optional, your company) → `profiles/<stack>/` (per stack) → the project itself.
Each layer only **adds** to the previous one. See [org/README.md](org/README.md) for the company layer (shared rules, permissions, MCP servers, agents, commands, modular rules, skills).

In each configured project, the kit aligns with the **5 Claude Code layers**:
1. **`CLAUDE.md` & `MEMORY.md`**: `CLAUDE.md` for invariants, commands, architecture, and gotchas (≤ 80 lines, 40–60 sweet spot; `@file` imports supported), plus `MEMORY.md` as a lightweight inter-session state index (≤ 150 lines).
2. **`.claude/rules/*.md`**: modular rules scoped by `paths` (monorepos, `base/rules/`, `org/rules/`).
3. **`.claude/skills/`** (and `commands/`): optional on-demand workflows from `base/` (`/commit`, `/handoff`, `/review`) or `org/`.
4. **`.claude/agents/`**: optional isolated subagents from `base/` (`code-reviewer`) or `org/`.
5. **Hooks (`.claude/settings.json`) & Observability**: deterministic guardrails (`SessionStart` with `session-check.py` including `~/.npmrc` supply-chain checks, `PreToolUse` with `guard.py`, `PostToolUse` with `format.py` running both `format_rules` and fast `lint_rules`, and `Stop` with `verify-stop.py` active by default whenever `verify_command` is set — opt-out via `"stop_verify": false` in `.claude/kit.json`). Hook blocks are logged to `.claude/logs/harness.log` and audited by `/claude-kit doctor` and `/claude-kit-learn`.

## Division of labor

| Script (`apply.py`) | Claude (via skills) |
|---|---|
| Detects known stacks (up to depth 5, skipping `node_modules`, `.venv`, etc.) | Understands the project |
| Copies hooks; upgrades them only if the project copy is unmodified (hashes in `.claude/kit.json`) | Creates and refreshes profiles from official docs |
| Merges `settings.json` without removing custom rules | Writes real architecture, gotchas, and monorepo `rule_paths` |
| Generates `CLAUDE.md` and `.claude/rules/*.md` (never overwrites) | Shows diffs and asks for confirmation |
| `audit` / `decide` / `doctor` / `sync` / `validate` | Explains issues, walks through conflicts, proposes and executes approved migrations |

Core rule: **what must stay identical every time is code; what requires understanding is delegated to Claude.**

## Installation (once per machine)

```bash
git clone https://github.com/nathan-trioleyre/claude-kit.git
cd claude-kit
python install.py --link     # links skills: edits in this repo take effect live
```

`--link` creates a symlink (a junction on Windows). Without it, skills are copied and you need to re-run `python install.py` after editing a `SKILL.md`.
Then, in any project: open Claude Code and type `/claude-kit`.

## Repository layout

```text
claude-kit/
├── VERSION                     kit version (recorded in each project's kit.json)
├── install.py                  installs skills (copy or --link) + records kit and Python paths
├── base/                       shared across ALL projects
│   ├── CLAUDE.md.template      CLAUDE.md skeleton
│   ├── MEMORY.md.template      MEMORY.md inter-session state skeleton
│   ├── settings.base.json      hardened permissions + hook wiring
│   ├── hooks/                  run-hook.sh, guard.py, format.py, session-check.py, verify-stop.py
│   └── agents/ commands/ rules/ skills/   optional: copied into each project if present
├── org/                        optional company layer (rules, permissions, MCP, agents, commands, skills)
├── profiles/                   one folder per stack
│   ├── python/ csharp-dotnet/ angular/ typescript/ nextjs/ docker/ rust/   built-in profiles
│   └── _TEMPLATE/              template for writing a profile by hand
├── skills/
│   ├── claude-kit/             /claude-kit (+ scripts/apply.py)
│   ├── claude-kit-refresh/     /claude-kit-refresh
│   └── claude-kit-learn/       /claude-kit-learn
└── tests/                      dependency-free unittest suite
```

### Profile freshness

Any profile whose `last_verified` is older than 90 days is flagged as `stale` by `doctor` and `apply`. Run `/claude-kit-refresh [stack|all]` to re-read official sources, review changes, and update the verification date after your approval.

## What the script never does

- overwrite an existing `CLAUDE.md` or `.claude/rules/<stack>.md` (writes a `.proposed` file alongside it and shows unified diffs with `--dry-run`). If you customized a file and the kit's output has not changed since the last run, it stays silent instead of re-proposing;
- remove a custom permission or hook (additive merge; only updates kit-managed hook commands and matchers);
- overwrite a locally modified hook (only `sync --force-hooks` does, explicitly);
- write anything when `--dry-run` is passed.

## Security model

- `deny` rules in `settings.json` block reading secrets, `sudo`, `rm -rf`, force pushes, and `reset --hard`.
- `guard.py` (`PreToolUse` hook) adds: nested shells (`bash -c "…"`, `pwsh -Command "…"`), reading, copying, or redirecting to secret files via Bash, `find -delete`, `git branch -D`, remote branch deletion, discarding working-tree changes, `curl | sh`, SQL `DROP` statements, and dangerous Windows deletions.
- `apply.py validate` rejects profile permissions that allow arbitrary code execution (`python *`, `bash *`, `npx *`, `find *`, `curl *`, …) or start with a wildcard.
- `guard.py` is a **safety net against accidents**, not a security boundary: strict isolation relies on `deny` rules and a sandboxed environment.

## Why not a Claude Code plugin?

Profiles are *rewritten* in this repository (and refreshed here). A plugin installs into a cache replaced on every update, so it cannot be the source of truth for data you modify. The kit keeps this repository as the single source of truth and avoids copy friction via `--link`, hook hashes, `sync`, and `doctor`. If you later want to share only the read-only parts (hooks and skills) with teammates, packaging them as a plugin remains possible.

## Evolving the kit

- A rule useful in all your projects → `base/`; across your company → `org/`; specific to one stack → its profile.
- Validate profiles → `python skills/claude-kit/scripts/apply.py validate`.
- Run tests → `python -m unittest discover -s tests -v`.
- Bump `VERSION` when modifying `base/` so `doctor` flags projects to resync; bump a hook's `claude-kit-hook-version` marker when modifying a hook.
- Commit changes in `profiles/` and `org/`: they are the memory of your stacks and company conventions.

## First-run checklist

1. **Skills appear**: in Claude Code, type `/` and look for `claude-kit`. Otherwise check `~/.claude/skills/`.
2. **Hooks work across platforms**: hooks invoke `.claude/hooks/run-hook.sh`, which searches `PATH` for a working `python3`/`python` (skipping broken Windows Store stubs), falls back to the interpreter saved in `~/.claude/claude-kit.json`, then tries `py -3`. Run `/hooks` to verify registration, then ask Claude to run `git push --force`: it must be blocked.
3. **Hooks load at startup**: after running `/claude-kit`, restart the session.
