# claude-kit

A personal kit that prepares Claude Code for any project (Python, C#, Angular, and any future stack) with a single command: `/claude-kit`.

## The Idea in 30 Seconds

When you land on a project, `/claude-kit`:

1. **inspects** the project to understand its stack;
2. **checks** `profiles/` to see if this stack is already known;
   - yes → it reuses the profile without re-researching;
   - no → it checks official documentation, validates and shows you the proposed profile, and **saves it to this repository after your approval**;
3. **generates** a `CLAUDE.md` (plus optional path-scoped `.claude/rules/<stack>.md`), permissions, and hooks (safety + formatting) in the project without ever overwriting what already exists.

`/claude-kit-refresh` updates profiles when best practices evolve.

## Who Does What

| The script (`apply.py`) | Claude (via skills) |
|---|---|
| Detects known stacks (up to depth 5, pruning `node_modules`/`.venv`/etc.) | Understands the project |
| Copies hooks and upgrades kit-managed hook entries cleanly | Creates/refreshes profiles from official docs |
| Merges `settings.json` without removing custom user rules | Writes project architecture, gotchas, and monorepo `rule_paths` |
| Generates `CLAUDE.md` & `.claude/rules/*.md` (without overwriting) | Shows diffs and asks for confirmation |

Core rule: **what must be identical every time is code; what requires understanding is delegated to Claude.**

## Installation (once per machine)

```bash
git clone <your-repo> claude-kit
cd claude-kit
python install.py
```

Then, in any project: open Claude Code and type `/claude-kit`.

## Repository Contents

```
claude-kit/
├── install.py                  installs skills + saves kit & Python paths
├── base/                       shared across ALL projects
│   ├── CLAUDE.md.template      skeleton for CLAUDE.md
│   ├── settings.base.json      hardened permissions + hook wiring
│   └── hooks/
│       ├── run-hook.sh         cross-platform Python 3 hook launcher
│       ├── guard.py            blocks destructive commands & secret writes
│       └── format.py           runs all matching formatters after Write/Edit
├── profiles/                   one folder per stack, populated over time
│   └── _TEMPLATE/              template for writing a profile manually
├── skills/
│   ├── claude-kit/             /claude-kit (+ scripts/apply.py)
│   └── claude-kit-refresh/     /claude-kit-refresh
└── tests/                      zero-dependency unittest suite
```

`profiles/` starts empty by design. Each profile will be created and approved by you the first time you encounter that stack.

## What the Script Never Does

- overwrite an existing `CLAUDE.md` or `.claude/rules/<stack>.md` (writes `.proposed` alongside it and prints unified diffs on `--dry-run`);
- remove a custom permission or hook (additive merge; only upgrades kit-managed hook commands/matchers);
- overwrite an existing hook file that differs;
- write anything when `--dry-run` is passed.

## Things to Verify on First Run

1. **Skills appear**: in Claude Code, type `/` and look for `claude-kit`. Otherwise, check `~/.claude/skills/`.
2. **Hooks run across platforms**: hooks invoke `.claude/hooks/run-hook.sh`, which searches `PATH` for a working `python3`/`python` (skipping broken Windows Store stubs), falls back to the interpreter saved in `~/.claude/claude-kit.json`, and finally tries `py -3`. Type `/hooks` to verify registration, then test asking Claude to run `git push --force`: it should be blocked.
3. **`disable-model-invocation: true`** in skills: prevents Claude from invoking `/claude-kit` autonomously.
4. **Hooks are loaded at startup**: after running `/claude-kit`, restart the session.

## Known Limitations

- `guard.py` is a **safety net against accidents**, not a security boundary. Strict read/bash restrictions live in `settings.json` `deny` rules and an isolated environment.
- Generated profiles depend on the quality of the sources found. That is why every profile is validated with `apply.py validate`, cites its sources, and requires your approval before saving.
- No domain skills or `/ship` commands yet. Add them **when a real need repeats**, not before.

## Evolving the Kit

- A rule useful across all your projects → `base/`.
- A rule specific to a stack → its profile, via `/claude-kit-refresh <stack>`.
- Validate profiles → `python skills/claude-kit/scripts/apply.py validate`.
- Run the test suite → `python -m unittest discover -s tests -v`.
- Modifying a `SKILL.md` → re-run `python install.py`.
- Commit changes in `profiles/` to this repository: it is your stack memory.
