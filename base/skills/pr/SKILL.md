---
name: pr
description: Create a pull request for the current work: branch, full verify, push, gh pr create with summary and test plan. Use only when the user types /pr or explicitly asks for a PR.
disable-model-invocation: true
argument-hint: "[optional title or base branch]"
---

# /pr: open a pull request

1. Run `git status -sb`, `git branch --show-current`, and find the default branch (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`). Uncommitted changes: stop and suggest `/commit` first.
2. If on the default branch, create a branch named after the change (`git switch -c <type>/<short-name>`) before anything else.
3. Run the full verify command from `CLAUDE.md` Commands (or `.claude/kit.json` `verify_command`). If it fails, stop and report; do not push.
4. Push with `git push -u origin <branch>` (never force-push).
5. Run `git log <default>..HEAD --oneline` and `git diff <default>...HEAD --stat`, then `gh pr create` with a title following the project's commit convention and a body with `## Summary` (what and why) and `## Test plan` (checklist of what was run or must be checked). Honor `$ARGUMENTS`.
6. Return the PR URL. **Never merge** the PR or enable auto-merge.
