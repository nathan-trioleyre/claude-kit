---
name: debug
description: Systematic root-cause debugging (reproduce, trace cause, write failing test, minimal fix, verify). Use when the user types /debug or reports a bug or failing test.
disable-model-invocation: true
argument-hint: "[error message, failing test, or symptom]"
---

# /debug: root-cause debugging without guessing

## Step 1: reproduce and read the real failure

1. Run the exact failing command or targeted test (`Test (targeted)` from `CLAUDE.md`) and read the full error and stack trace.
2. Do not propose a fix before locating the exact failing line and condition.

## Step 2: isolate root cause

- Trace inputs from boundary to failure point; check recent changes (`git diff`, `git log -n 5`).
- Identify why the current behavior happens, not just the symptom.

## Step 3: TDD fix and verify

1. Write a minimal deterministic test that reproduces the bug and watch it fail (`RED`).
2. Apply the smallest fix addressing the root cause (`GREEN`).
3. Run the project's full `Verify` command before concluding.
