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
- **Check `git status`** for untracked files: stage new files that belong to the change, flag the rest.
- **One logical change per commit**: if the working tree mixes unrelated changes, split them into separate commits.
- **Targeted checks, not full verify**: run the tests for the changed files (the targeted/`test_related` command listed in `CLAUDE.md` Commands, if any) and the linter on the changed files only. Skip for pure doc/comment edits. Full verify is for before push/PR (`/pr`).

## Step 3: stage and commit

1. Propose the files to stage and the commit message (incorporating `$ARGUMENTS` if given).
2. Stage explicitly (`git add <paths>`) and run `git commit -m "<message>"`.
3. Never run `git push` unless the user explicitly asked for it.
4. Never amend or rewrite commits that were already pushed; make a new commit instead.
