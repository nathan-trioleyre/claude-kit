# claude-kit

Personal kit that configures Claude Code in any project (`/claude-kit`). See [README.md](README.md).

## Commands
- Test: `python -m unittest discover -s tests -v`
- Validate profiles: `python skills/claude-kit/scripts/apply.py validate`

## Git conventions
- **Conventional Commits**: `type(scope): subject` in English, imperative, no trailing period.
  Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`. Scopes used here: `hooks`, `apply`, `install`, `profiles`, `skills`, `org`.
- One logical change per commit; keep tests green at the tip of each branch.
- Never commit directly to the default branch: work on a branch (`feat/...`, `fix/...`).

## Rules
- Changing `base/` → bump `VERSION`; changing a hook → bump its `claude-kit-hook-version` marker.
- Profiles: `practices.md` max 15 lines, sourced from official docs, `last_verified` only after a real check (`/claude-kit-refresh`).
- Write files containing backslashes with the Write tool, not shell heredocs (escapes get altered).
