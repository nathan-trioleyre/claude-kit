---
name: wrap-up
description: Summarizes what was completed, files changed, verification status, and exact next steps before ending a session or running /clear. Use when the user types /wrap-up or pauses a multi-step task.
---

# /wrap-up: clean session handoff

Produce a concise handoff summary (under 15 lines) so the next session or `/clear` starts cleanly:

1. **Done**: bullet list of completed changes with file paths.
2. **Verified**: exact command(s) run and their pass/fail status (or "not yet run").
3. **Remaining / Next**: concrete next step(s) or open questions, including the first command to run on resume.
4. **Gotcha** (only if discovered): 1 line worth adding to `CLAUDE.md` ("Lessons Learned").
