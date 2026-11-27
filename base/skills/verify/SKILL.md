---
name: verify
description: Runs the project's verification command, inspects git diff for unintended changes or secrets, and summarizes readiness before concluding a task. Use when the user types /verify or before wrapping up a feature/fix.
---

# /verify: final quality gate before concluding

1. Read `CLAUDE.md` to find the project's `Verify` command (or `Test` + `Lint` commands).
2. Run the verification command and inspect the actual output. Do not claim success if any check failed or was skipped.
3. Run `git status --short` and `git diff --stat` to verify:
   - no unintended files, debug leftovers, or secrets (`.env`, keys) were touched;
   - changes stay focused on the task.
4. For non-trivial changes, delegate a quick diff review to the `code-reviewer` subagent if available.
5. Report the exact command(s) run, their pass/fail status, and any remaining warnings.
