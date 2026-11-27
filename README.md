# claude-kit

A personal kit that prepares Claude Code for any project (Python, C#, Angular, and any future stack) with a single command: `/claude-kit`.

## The Idea in 30 Seconds

When you land on a project, `/claude-kit`:

1. **inspects** the project to understand its stack;
2. **checks** `profiles/` to see if this stack is already known;
   - yes → it reuses the profile without re-researching;
   - no → it checks official documentation, validates and shows you the proposed profile, and **saves it to this repository after your approval**;
3. **generates** a `CLAUDE.md` (plus optional path-scoped `.claude/rules/<stack>.md`), permissions, and hooks (safety + formatting) in the project without ever overwriting what already exists.

Afterwards, the kit keeps projects in line with it:

| Command | What it does |
|---|---|
| `/claude-kit` | first setup (or full re-run) of a project |
| `/claude-kit doctor` | reports drift: outdated hooks, missing permissions, stale profiles, new stacks, `CLAUDE.md` gaps |
| `/claude-kit sync` | refreshes only the kit-managed files (settings, hooks, agents/commands, `.mcp.json`); never touches `CLAUDE.md` |
| `/claude-kit-refresh [stack\|all]` | re-reads a profile's official sources and proposes updates |
| `/claude-kit-learn` | promotes durable lessons from a project's `CLAUDE.md` into the kit (profile, `org/`, or `base/`) |

## Layers

`base/` (every project) → `org/` (optional, your company) → `profiles/<stack>/` (per stack) → the project itself.
Each layer only **adds** to the previous one. See [org/README.md](org/README.md) for the company layer (shared rules, permissions, MCP servers, agents, commands).

## Who Does What

| The script (`apply.py`) | Claude (via skills) |
|---|---|
| Detects known stacks (up to depth 5, pruning `node_modules`/`.venv`/etc.) | Understands the project |
| Copies hooks; upgrades them only if the project's copy is unmodified (hashes in `.claude/kit.json`) | Creates/refreshes profiles from official docs |
| Merges `settings.json` without removing custom user rules | Writes project architecture, gotchas, and monorepo `rule_paths` |
| Generates `CLAUDE.md` & `.claude/rules/*.md` (without overwriting) | Shows diffs and asks for confirmation |
| `doctor` / `sync` / `validate` | Explains issues and proposes the fix |

Core rule: **what must be identical every time is code; what requires understanding is delegated to Claude.**

## Installation (once per machine)

```bash
git clone https://github.com/nathan-trioleyre/claude-kit.git
cd claude-kit
python install.py --link     # skills are linked: edits to this repo are live
```

`--link` uses a symlink (junction on Windows). Without it, skills are copied and `python install.py` must be re-run after editing a `SKILL.md`.
Then, in any project: open Claude Code and type `/claude-kit`.

## Repository Contents

```
claude-kit/
├── VERSION                     kit version (recorded in each project's kit.json)
├── install.py                  installs skills (copy or --link) + saves kit & Python paths
├── base/                       shared across ALL projects
│   ├── CLAUDE.md.template      skeleton for CLAUDE.md
│   ├── settings.base.json      hardened permissions + hook wiring
│   ├── hooks/                  run-hook.sh (launcher), guard.py (safety), format.py (formatters)
│   ├── agents/  commands/      optional: copied into every project
├── org/                        optional company layer (rules, permissions, MCP, agents, commands)
├── profiles/                   one folder per stack
│   ├── python/ csharp-dotnet/ angular/   starter profiles
│   └── _TEMPLATE/              template for writing a profile manually
├── skills/
│   ├── claude-kit/             /claude-kit (+ scripts/apply.py)
│   ├── claude-kit-refresh/     /claude-kit-refresh
│   └── claude-kit-learn/       /claude-kit-learn
└── tests/                      zero-dependency unittest suite
```

### Starter profiles are unverified on purpose

`python`, `csharp-dotnet` and `angular` were written from general knowledge, not checked against their sources yet.
Their `last_verified` is deliberately old, so the kit reports them as stale. Run `/claude-kit-refresh all` once: it re-reads the official sources, shows you the changes, and stamps the verification date after your approval.

## What the Script Never Does

- overwrite an existing `CLAUDE.md` or `.claude/rules/<stack>.md` (writes `.proposed` alongside it, and prints unified diffs on `--dry-run`). If you customized a file and the kit's output has not changed since the last run, it stays silent instead of re-proposing;
- remove a custom permission or hook (additive merge; only upgrades kit-managed hook commands/matchers);
- overwrite a hook you modified locally (only `sync --force-hooks` does, explicitly);
- write anything when `--dry-run` is passed.

## Safety Model

- `settings.json` `deny` rules block secret reads, `sudo`, `rm -rf`, force pushes and `reset --hard`.
- `guard.py` (PreToolUse hook) adds: nested shells (`bash -c "…"`, `pwsh -Command "…"`), reading/copying/redirecting into secret files via Bash, `find -delete`, `git branch -D`, remote branch deletion, discarding working-tree changes, `curl | sh`, DROP statements, and dangerous Windows deletions.
- `apply.py validate` rejects profile permissions that allow arbitrary code execution (`python *`, `bash *`, `npx *`, `find *`, `curl *`…) or start with a wildcard.
- `guard.py` is still a **safety net against accidents**, not a security boundary: strict isolation lives in `deny` rules and an isolated environment.

## Why Not a Claude Code Plugin?

Profiles are *written back* to this repository (and refreshed there). A plugin is installed into a cache that is replaced on update, so it cannot be the source of truth for data you edit. The kit keeps the repository as the source of truth and removes the drawbacks of copying with `--link`, hook hashes, `sync` and `doctor`. If you later want to distribute only the read-only part (hooks and skills) to teammates, wrapping it as a plugin remains possible.

## Evolving the Kit

- A rule useful across all your projects → `base/`; across your company → `org/`; specific to a stack → its profile.
- Validate profiles → `python skills/claude-kit/scripts/apply.py validate`.
- Run the test suite → `python -m unittest discover -s tests -v`.
- Bump `VERSION` when you change `base/` so `doctor` flags projects that need a `sync`; bump the `claude-kit-hook-version` marker in a hook when you change it.
- Commit changes in `profiles/` and `org/`: they are your stack and company memory.

## Things to Verify on First Run

1. **Skills appear**: in Claude Code, type `/` and look for `claude-kit`. Otherwise, check `~/.claude/skills/`.
2. **Hooks run across platforms**: hooks invoke `.claude/hooks/run-hook.sh`, which searches `PATH` for a working `python3`/`python` (skipping broken Windows Store stubs), falls back to the interpreter saved in `~/.claude/claude-kit.json`, and finally tries `py -3`. Type `/hooks` to verify registration, then ask Claude to run `git push --force`: it should be blocked.
3. **Hooks are loaded at startup**: after running `/claude-kit`, restart the session.
