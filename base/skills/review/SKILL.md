---
name: review
description: Run an isolated pre-commit diff review (correctness, security, test coverage, CLAUDE.md invariants) using the code-reviewer agent. Use when the user types /review or before /commit.
disable-model-invocation: true
argument-hint: "[optional git diff range, e.g. main..HEAD]"
---

# /review: isolated diff review before committing

## Step 1: collect change scope

1. Run `git status -sb` and `git diff --stat HEAD` (or `git diff --stat $ARGUMENTS` when a range is given).
2. If there are no changes to review, say so and stop.

## Step 2: run isolated review

- Delegate the review to the `.claude/agents/code-reviewer.md` agent (or run its exact checklist in a fresh subagent if available; if subagents are unavailable, execute the checklist strictly against the diff).
- Pass `CLAUDE.md`, relevant `.claude/rules/*.md`, and the diff range (`$ARGUMENTS`, or working tree + staged changes when empty).

## Step 3: present findings

- Summarize **Critical** and **Important** findings first with `file:line` locations.
- If **Ready for `/commit`**, suggest running `/commit` (and verify `verify_command` passes).
- Do not modify files during `/review` unless the user asks you to fix findings.
