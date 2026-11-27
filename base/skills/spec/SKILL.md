---
name: spec
description: Plan a non-trivial change (architecture, edge cases, files to modify, and tests to write first) before editing code. Use when the user types /spec or before implementing a multi-file feature.
disable-model-invocation: true
argument-hint: "[feature or change description]"
---

# /spec: align on design and tests before editing

## Step 1: inspect context

1. Read `CLAUDE.md` and `.claude/codemap.md` (if present) to locate entrypoints and invariants.
2. Read only the files directly affected by `$ARGUMENTS`.

## Step 2: write a concise spec

Present a short plan (no code implementation yet):
- **Goal & Non-goals**: 1-2 lines on what changes and what stays untouched.
- **Files & Interfaces**: exact files to create/modify and function/API signatures.
- **Edge Cases**: failure modes, boundaries, validation, and backward compatibility.
- **Tests First (TDD)**: exact test names and assertions to write before implementation.

## Step 3: confirm and execute

- Wait for user confirmation if anything is ambiguous or risky; otherwise proceed directly to writing the failing test first (`RED -> GREEN`).
