---
name: handoff
description: Save a concise inter-session state summary into ./MEMORY.md (Decisions, Active WIP, Known Issues) before /clear, /compact, or ending a session. Use when the user types /handoff or wants to pause and resume work cleanly later.
disable-model-invocation: true
argument-hint: "[optional focus or next step]"
---

# /handoff: persist inter-session state in ./MEMORY.md

## Step 1: inspect current state

1. Read `./MEMORY.md` if it exists (create it from the `## Decisions`, `## Active WIP`, `## Known Issues` structure if missing).
2. Run `git status -sb` and `git branch --show-current` to capture the exact working state.

## Step 2: update `./MEMORY.md` cleanly

- Use today's ISO date (`[YYYY-MM-DD]`) on every new or updated bullet.
- Keep each entry **under 150 characters** (concise pointer, not a narrative):
  - `## Decisions`: durable architectural or tooling choices made in this session.
  - `## Active WIP`: current branch/task, what is done, and the exact next step (incorporate `$ARGUMENTS` if provided).
  - `## Known Issues`: unresolved blockers, failing checks, or workarounds.
- **Prune stale WIP**: remove completed `Active WIP` items so `./MEMORY.md` stays **under 150 lines** (Claude Code truncates at 200 lines / 25 KB).
- If any existing entry is older than 30 days and still relevant as a permanent rule, suggest promoting it to `CLAUDE.md` via `/claude-kit-learn`.

## Step 3: wrap up

Show the updated `./MEMORY.md` diff and remind the user they can safely run `/clear` or start a new session.
