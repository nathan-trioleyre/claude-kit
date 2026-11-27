---
name: commit
description: Stage, verify, and create a clean commit following the project's git conventions (or Conventional Commits by default). Use when the user types /commit or asks to commit changes.
disable-model-invocation: true
argument-hint: "[optional hint or message]"
---

# /commit: clean, verified, convention-compliant commits

## Step 1: inspect state and conventions

1. Run `git status -sb`, `git diff --stat`, and `git log -n 10 --oneline`.
2. Read `CLAUDE.md` (and `CLAUDE.local.md` if present) for project-specific git rules (commit format, language, allowed types/scopes, branch policy).
3. If the project defines no convention, follow **Conventional Commits v1.0.0** (`https://www.conventionalcommits.org/en/v1.0.0/`):
   - Header: `<type>[optional scope][optional !]: <description>` (imperative mood, ≤ 72 chars, no trailing period).
   - Types: `feat` (new feature), `fix` (bug fix), `build`, `chore`, `ci`, `docs`, `perf`, `refactor`, `revert`, `style`, `test`.
   - Breaking changes: append `!` before `:` (e.g. `feat(api)!: drop v1 endpoint`) and/or add a `BREAKING CHANGE: <explanation>` footer.
   - Optional body after a blank line (explain *why*, not *what*); optional git-trailer footers (`Refs: #123`, `Co-authored-by: ...`).

## Step 2: safety & scope check

- **Never stage secrets or local artifacts**: `.env*` (except `.env.example`/`.template`/`.sample`), `*.pem`, `*.key`, `credentials*`, `*.proposed`, `.claude/logs/`.
- **One logical change per commit**: if the working tree mixes unrelated changes (e.g. a feature and an unrelated fix), propose splitting into separate commits.
- **Verify first**: if `.claude/kit.json` defines `verify_command` and code files changed, ensure it passes before committing (skip only for pure doc/comment edits or if it already passed on the exact current state).

## Step 3: stage and commit

1. Propose the files to stage and the commit message (incorporating `$ARGUMENTS` if given).
2. Stage explicitly (`git add <paths>`) and run `git commit -m "<message>"`.
3. Never run `git push` unless the user explicitly asked for it.
