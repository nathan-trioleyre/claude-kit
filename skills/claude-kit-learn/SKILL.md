---
name: claude-kit-learn
description: Promotes durable lessons from the current project's CLAUDE.md "Lessons Learned" section into the claude-kit (a stack profile's practices.md, the org layer, or base rules), after your approval. Use when the user types /claude-kit-learn or wants lessons from a project to benefit all projects.
disable-model-invocation: true
---

# /claude-kit-learn: make the kit smarter from real projects

## Step 0: locate the kit

Do Step 0 of `/claude-kit` (`Read` `~/.claude/claude-kit.json` for `kit_path` = `KIT` and `python` = `PY`; `APPLY` = `PY "KIT/skills/claude-kit/scripts/apply.py"`).

## Step 1: collect candidates

1. Read the project's `CLAUDE.md` ("Lessons Learned" and "Known Gotchas") and `.claude/rules/*.md`.
2. Read `.claude/kit.json` to know which profiles the project uses.
3. Keep only lessons that are **general to a stack or to all projects** (a framework pitfall, a tooling flag, a safety rule). Discard anything specific to this codebase (names, paths, business rules).

## Step 2: route each candidate

| Scope | Destination |
|---|---|
| One stack | `KIT/profiles/<stack>/practices.md` (15 non-empty lines max: propose which line to drop if full) |
| Every project of the user's company | `KIT/org/rules.md` |
| Every project, safety or workflow | `KIT/base/CLAUDE.md.template` (propose the exact edit, never apply silently) |

## Step 3: propose, validate, save

1. Show the user a table: lesson, destination, exact line to add (and line to remove if needed).
2. Wait for approval of each item. Apply only the approved ones.
3. Run `APPLY validate` after editing a profile; fix errors.
4. Remind the user to commit in the kit repository and to run `/claude-kit sync` in other projects (or re-run `/claude-kit` for `CLAUDE.md` changes).

## Rules

- Never add an unverified claim: if a lesson is a guess, say so and skip it.
- Never touch `KIT/base/hooks/` or `settings.base.json` from this skill.
- Ask one question at a time.
