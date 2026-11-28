---
name: handoff
description: Write a short session handoff note to .claude/handoff.md before /clear, /compact, or ending a session. Use when the user types /handoff or wants to pause and resume work cleanly later.
disable-model-invocation: true
argument-hint: "[optional focus or next step]"
---

# /handoff: save session state to .claude/handoff.md

1. Run `git status -sb` and `git branch --show-current`.
2. **Overwrite** `.claude/handoff.md` (create `.claude/` if needed) with at most 40 lines:
   - `## Goal`: what this work is for (incorporate `$ARGUMENTS` if given).
   - `## Done`: completed items.
   - `## In progress`: current task and exact state.
   - `## Next steps`: ordered, concrete actions.
   - `## Gotchas`: blockers, failing checks, workarounds, decisions worth remembering.
   - `## Branch`: branch name and uncommitted state.
3. The file is gitignored by the kit (or in `.git/info/exclude` in local mode); never commit it. The SessionStart hook prints a pointer to it in the next session.
4. Show the note and tell the user they can safely `/clear`. Suggest `/claude-devkit-learn` if a gotcha is durable.
