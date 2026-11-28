---
name: review
description: Review the current diff with the code-reviewer subagent and summarize findings by severity. Use when the user types /review or wants a check before committing or opening a PR.
disable-model-invocation: true
argument-hint: "[optional focus]"
---

# /review: review the current diff

1. Run `git status -sb` and `git diff --stat` (plus `git diff --cached --stat`). If there is no change, say so and stop.
2. Dispatch the `code-reviewer` subagent on the current diff (staged and unstaged), passing `$ARGUMENTS` as extra focus if given.
3. Summarize its findings: counts per severity, then the Critical/High items with `file:line` and the proposed fix. Do not apply fixes unless the user asks.
4. Suggest next step: fix the findings, then `/commit`.
