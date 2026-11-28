# Stack Profiles

One folder per stack (`python/`, `csharp-dotnet/`, `angular/`, …), created by `/claude-devkit` the first time it encounters a stack, then reused across subsequent projects.

Each profile contains:
- `profile.json`: machine-readable metadata (detection entries, commands, permissions, format rules, optional `paths` for `.claude/rules/<stack>.md`, optional `supersedes`, optional `tooling` conflict detection, sources, `last_verified` date).
- `practices.md`: summary of **timeless** stack best practices (max 15 lines; copied into `CLAUDE.md` or `.claude/rules/<stack>.md` when paths are defined).
- `versions/<ver>.md` *(optional)*: rules specific to a major version (max 8 lines, e.g., `versions/11.md`, `versions/21.md`), created on demand and injected automatically when `stack_versions` matches.

Rules:
- A profile is only saved after validation (`apply.py validate`) and your approval.
- Every profile cites its sources (official documentation preferred).
- A profile older than 90 days is flagged as stale: `/claude-devkit-refresh <stack>`.
- Copy `_TEMPLATE/` to author one by hand.

## `detect`: how a profile is matched

`detect` is a non-empty list; the profile matches when ANY entry hits. An entry is one of:
- `"pom.xml"` or `"*.vue"`: a glob (matched against the file name, or the relative path when it contains `/`).
- `{"file": "package.json", "contains": "\"react\":"}`: the file must also contain the text (case-insensitive, first 200 KB, undecodable bytes ignored). Same rules as tooling `markers`.
- `{"all": ["vite.config.*", {"file": "package.json", "contains": "\"react\":"}]}`: every part (a glob or a `{file, contains}`) must hit in the SAME directory, so one monorepo package is not mixed with another's files. `all` cannot be nested.

Prefer content-aware entries over bare globs when a file name is shared by many stacks (`pom.xml`, `package.json`), and use `supersedes` when a more specific profile should replace a generic one.

## `tooling` (optional): coexisting with existing project tools & presets

Declares, per concern (`formatter`, `linter`, `typechecker`, `package-manager`, …), the kit's preferred tool (`kit`) and known `alternatives`. When a project already uses an alternative, `apply.py` withholds overlapping kit rules until the user decides (`keep_existing`, `adopt_kit`, `keep_both`, or `skip`). When neither `kit` nor an alternative is detected and `kit` defines a preset, `audit` reports it in `missing_tooling`.

- `kit`: `name`, `markers` (what reveals the kit tool), `commands` (command keys it owns), `format_rules` (true if it owns the format rule), `permissions` (rules it owns), `practice_terms` (practice lines mentioning them are withheld when keeping/skipping), plus optional preset fields: `preset_files` (`{"src": "presets/<file>.template", "dest": "...", "mode": "create|snippet"}`), `install_packages` (list or per-package-manager map), `scripts` (`package.json` script map), `post_edit_check` (fast single-file lint rule for `PostToolUse`), and `only_when_installed` (true if active only once markers exist).
- `alternatives[]`: `name`, `markers` (`{"file": glob, "contains": text}`), `hooks` (keywords revealing a hand-made hook), and optional replacements used when keeping the tool: `commands`, `permissions_allow`, `format_rule`, `post_edit_check`. Optional (may be empty) when `kit` declares presets.
- Top-level `verify_steps` *(optional)*: ordered `[{"cmd": "...", "concern": "<concern>|null"}]` so `apply.py` can drop only a skipped concern's verify step. When a profile has `verify_steps`, the effective verify command is composed from them (a step with `command_key` uses the effective command of that key), so package-manager alternatives must not restate `commands.verify`; `commands.verify` stays the default and must equal the steps joined with ` && `.
- `runner` *(optional, on the `package-manager` concern's `kit` and on each of its `alternatives`)*: the prefix that runs a project-local tool with that package manager (uv: `uv run`, poetry: `poetry run`, pnpm: `pnpm exec`, yarn: `yarn`, bun: `bunx`, npm: `npx`). Any command, `verify_steps[].cmd`, alternative command, permission rule or `format_rule`/`post_edit_check` command list may contain `{run}` (e.g. `"{run} tsc --noEmit"`, `"Bash({run} flake8*)"`, or the token `"{run}"` in an argv list). It is substituted last, with the runner of the package manager in effect (the kit's, or the kept alternative's); a package manager without `runner` gets the bare tool (`{run} ` is dropped). `validate` checks each `{run}` permission once per declared runner.
