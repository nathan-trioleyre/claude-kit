# Design: Full Harness Workflow — Per-Language Linter/Formatter Presets & Agentic Workflow

Date: 2026-11-27
Status: Ready for approval

## Intent & Why

Today, `claude-devkit` provides deterministic execution hooks (`format.py` on `PostToolUse`, `verify-stop.py` on `Stop`, `guard.py` on `PreToolUse`) and detects competing tools on already-configured projects (`tooling` in `profile.json`). However:
1. Profiles do not ship strict, opinionated linter/formatter/static-analysis configurations (`eslint.config.mjs`, `ruff.toml`, `.globalconfig`, `[lints.clippy]`, etc.).
2. When `/claude-devkit` lands on a project with **no** linter configured, it writes default commands (`npm run lint`, `uv run ruff check .`) without checking whether a real linter config exists or offering to install one.
3. `PostToolUse` only runs formatting (`format_rules`), leaving lint issues to be caught only at turn end (`verify-stop.py`), and `base/` does not yet provide reusable agentic workflow pieces (`review` agent/skill, universal `.editorconfig`, optional git pre-commit hook).

The goal is to make `/claude-devkit` deliver a complete baseline workflow (**AI + deterministic tooling**) so that style, types, dead code, complexity, and common bugs are caught deterministically at 0 LLM tokens, while keeping Claude focused on architecture, tests, and domain logic.

## Goals

- Equip every built-in stack profile (`python`, `typescript`, `nextjs`, `angular`, `csharp-dotnet`, `rust`, `docker`) with strict, officially-sourced linter/formatter/static-analysis presets tailored as AI-code guardrails.
- Extend `apply.py audit`, `apply`, and `doctor` to detect **missing** tooling (not only conflicting tooling) and let `/claude-devkit` propose installing the kit's preset + dev dependencies + scripts with explicit user approval.
- Speed up the inner AI feedback loop by supporting optional fast, auto-fixable per-file lint checks in `base/hooks/format.py` (`PostToolUse`) alongside formatting.
- Add lightweight reusable workflow assets in `base/` (isolated `/review` skill + agent, universal `.editorconfig` preset, optional `.githooks/pre-commit`) using existing kit conventions without bloating `CLAUDE.md`.

## Non-Goals

- **No silent modification of existing projects**: projects that already configure their own linter/formatter continue through the existing `audit` / `decide` (`keep_existing` | `adopt_kit` | `keep_both`) workflow without forced migration.
- **No forced syncing of project-owned linter configs**: once scaffolded into a project, linter/formatter config files belong to the project and are never overwritten by `/claude-devkit sync`.
- **No bloat in `CLAUDE.md` or `practices.md`**: linter rules live in linter config files, not in prompt text (`practices.md` stays <= 15 lines; `CLAUDE.md` stays <= 80 lines).
- **No repo pollution in `--local` mode**: `/claude-devkit local` must never create or edit project-wide linter configs, `package.json`, `pyproject.toml`, `.editorconfig`, or `.githooks/`.

## Anti-Goals

- **Slow or noisy `PostToolUse` hooks**: per-file lint checks after `Edit`/`Write` must only run fast tools (sub-second to a few seconds) on the single edited file; full-project typechecks and test suites stay in `verify_command` (`Stop`).
- **Auto-fixing rules by disabling checks**: presets must not silence strict checks just to make builds pass; rules should catch real AI failure modes (unused code, implicit `any`, untyped boundaries, empty catches, excessive complexity) without drowning existing code in unactionable nitpicks.
- **Unsafe permissions or blind package installs**: profile validation must continue rejecting unsafe `Bash(*)` / `npx *` permissions, and package installation remains an explicit user-approved step executed with existing supply-chain guards (`uv`, `~/.npmrc` `ignore-scripts=true` awareness).

## Constraints

- `skills/claude-devkit/scripts/apply.py` and `base/hooks/*.py` must remain dependency-free Python 3.9+ (stdlib only) and cross-platform (Windows + Linux/macOS).
- Existing `apply.py` invariants hold: `--dry-run` writes nothing; existing files (`CLAUDE.md`, `.claude/rules/*.md`, and any scaffolded config files) are never silently overwritten; `apply.py validate` enforces schema and permission safety.
- Modifying `base/` requires bumping `VERSION`; modifying `base/hooks/format.py` requires bumping its `claude-devkit-hook-version` marker.
- `tests/` unittest suite must remain dependency-free and pass (`python -m unittest discover -s tests -v`), plus `python skills/claude-devkit/scripts/apply.py validate`.

## Approaches Considered

1. **Approach 1 — Per-profile presets (init scaffolding only)**: add config presets to profiles, detect missing tooling in `audit`, and scaffold configs with user approval. Simple and safe, but leaves the inner `PostToolUse` loop and reusable AI workflow assets (`base/skills/`, `base/agents/`, git hooks) untouched.
2. **Approach 2 — Full Harness: strict per-language presets + fast inner loop + `base/` AI workflow assets (Chosen)**: combines Approach 1 with (a) fast per-file `lint_rules` in `format.py`, (b) AI-guardrail rules baked into each preset (strict typing, complexity bounds, dead code, basic security), and (c) reusable `base/` workflow bricks (isolated `/review` skill + agent, `.editorconfig` preset, optional `.githooks/pre-commit`). Maximizes 0-token defect prevention while keeping each project autonomous.
3. **Approach 3 — Kit-synced linter configs via `sync`**: manage project linter configs with hashes like `.claude/hooks/`. Too rigid across projects with different dependency versions and team conventions.

## Architecture & Design

### 1. Profile Presets & Extended `tooling` Schema (`profiles/<stack>/`)

Each stack profile can include an optional `presets/` folder containing ready-to-use configuration files and declare them inside `profile.json` under `tooling[]`.

Optional new fields on `tooling[].kit` in `profile.json` (documented in `profiles/README.md` and `profiles/_TEMPLATE/profile.json`):
- `preset_files`: list of `{ "src": "presets/<file>", "dest": "<project-relative-path>", "mode": "create" | "snippet" }` (`mode` defaults to `"create"`).
- `install_packages`: dev dependencies / tool packages needed for the preset (list of strings, or mapping by package-manager name e.g. `npm`/`pnpm`/`yarn`/`bun`, `uv`/`poetry`).
- `scripts`: expected project command entries (e.g. `package.json` `scripts` keys `"lint"`, `"format"`, `"typecheck"`).
- `post_edit_check`: optional fast single-file lint rule `{ "extensions": [".ext"], "command": ["tool", "flag", "{file}"] }` suitable for `PostToolUse`.
- `only_when_installed`: optional boolean (default `false`) for optional add-on concerns like Python `typechecker`: when `true`, the concern's commands/verify step are only active if its `kit.markers` (or an alternative) are present in the project rather than assumed by default. *(Our call — prevents breaking existing Python projects that don't use `mypy`.)*

Optional top-level `verify_steps` on `profile.json`:
- Ordered list of `{ "cmd": "<command>", "concern": "<tooling-concern-or-null>" }` representing the components of `commands.verify`. *(Our call — makes filtering `verify` deterministic when one concern is `"skip"`ed or kept without replacement, while keeping `commands.verify` backward-compatible for profiles without `verify_steps`.)*

Coverage across the 7 built-in profiles:
- **`typescript`, `nextjs`, `angular`**:
  - Add `concern: "linter"` (`kit`: ESLint flat config `eslint.config.mjs` with `typescript-eslint` strict rules, unused imports, complexity/size guardrails, framework rules; `alternatives`: `biome`, `oxlint`).
  - Keep `formatter` (`prettier` / `biome`).
  - Add `typechecker` (`tsc --noEmit`, marker `tsconfig.json`, and add `tsc --noEmit` into `typescript` `verify` / `verify_steps` alongside `nextjs`; `scaffold-tooling` only offers a strict `tsconfig.json` preset when absent). *(Our call.)*
- **`python`**:
  - Complete `ruff check` + `ruff format` preset (`presets/ruff.toml` with curated rule groups: `E`, `F`, `I`, `B`, `UP`, `SIM`, `C90` complexity, `S` basic security, `RUF`, `post_edit_check`: `["ruff", "check", "--fix", "{file}"]`).
  - Add `concern: "typechecker"` (`kit`: `mypy` with `only_when_installed: true` and `presets/mypy.ini` or `[tool.mypy]` snippet; `alternatives`: `pyright`). *(Our call — matches existing `Bash(uv run mypy*)` permissions in `python/profile.json` and avoids blocking existing repos unless `mypy` is adopted.)*
- **`csharp-dotnet`**:
  - Keep built-in `dotnet format` (`status: "none"` by default since it ships with the SDK, no missing-tool noise). *(Our call.)*
  - Add `concern: "analyzers"` (`kit`: Roslyn strictness via `presets/Directory.Build.props` + `presets/.globalconfig`, avoiding any filename collision with the universal `.editorconfig`). *(Our call.)*
- **`rust`**:
  - Keep built-in `cargo clippy` / `cargo fmt` working out of the box (`commands.lint` / `commands.verify`).
  - Add optional `concern: "lint-config"` (`kit`: strict `presets/clippy.toml` + `presets/rustfmt.toml`, non-blocking if skipped). *(Our call — avoids flagging Cargo projects as missing a linter just because optional TOML config files aren't present.)*
- **`docker`**:
  - Add `concern: "linter"` (`kit`: `presets/.hadolint.yaml` with `hadolint` command; `only_when_installed: true` on `verify` so `docker compose config --quiet` still works if `hadolint` isn't installed). *(Our call.)*

`apply.py validate` checks:
- `preset_files[].src` resolves strictly inside `profiles/<stack>/` and exists.
- `preset_files[].dest` is a safe relative path within the project root (no `..`, no absolute path, not targeting `.env*` or secret files).
- `post_edit_check` validates like `format_rules` (`extensions` list starting with `.`, `command` includes `{file}`, executable not in `UNSAFE_BASH_COMMANDS`).
- `verify_steps` (if present) references valid `concern` slugs declared in `tooling` (or `null`).

### 2. AI-Guardrail Rules in Presets

Presets explicitly target the failure modes of AI-generated code so prompt space is preserved:
- Strict type safety (`strict`, no `any`, explicit boundary validation / type hints).
- Dead code & unused imports/variables.
- Complexity & size guardrails (cyclomatic complexity threshold, max nesting depth, avoiding giant single functions).
- Explicit error handling (no silent empty `catch`/`except`, no unawaited promises).
- Basic static security checks (unsafe eval/exec patterns, hardcoded secret patterns where supported by the linter).

### 3. Missing-Tooling Detection, `effective_profile`, & Guided Installation (`apply.py` + `/claude-devkit`)

Today `analyze_tooling()` sets `status = "none"` whenever no alternative is found — even when `kit_evidence` is also empty.

Changes in `apply.py`:
- **Status `"missing"`**: when `existing` is empty AND `kit_evidence` is empty AND `kit` declares `preset_files`, `install_packages`, or `scripts` (and no `"skip"` decision is recorded), `analyze_tooling()` sets `status = "missing"`.
- **Decision `"skip"`**: `DECISION_CHOICES` becomes `("keep_existing", "adopt_kit", "keep_both", "skip")`.
- **`effective_profile` behavior** *(Our call)*:
  - When `status` is `"missing"` (not yet `"skip"`ed): keep `effective = "adopt_kit"` unless `kit.only_when_installed` is `true` (this preserves backward compatibility for existing tests and default stack behavior).
  - When the user explicitly records `"skip"` (or `only_when_installed: true` and absent): withhold that concern's owned `commands`, `format_rules`, `lint_rules`, `permissions`, and filter its steps out of `verify_steps` (or clear `verify` if no `verify_steps` and it owns a `COMMAND_KEYS_NEEDING_VERIFY` key) so `verify-stop.py` never blocks turns trying to run a skipped/absent tool.
- **`apply.py audit`**: includes `"missing_tooling"` (all entries with `status == "missing"`) alongside `"tooling"` and `"pending_conflicts"`.
- **`apply.py doctor`** *(Our call)*: introduces a non-fatal `WARN` tier alongside `OK` and `ISSUE`. Unskipped `missing_tooling` prints `WARN   ...` and does **not** cause `doctor` to exit `1` on its own; real drift (`ISSUE`) still exits `1`. Once a preset is scaffolded, user edits to that config file never trigger `doctor` drift.
- **`apply.py scaffold-tooling`**: new subcommand (`--project`, `--profile`, `--concern`, `--dry-run`, `--local` blocked/no-op) that:
  1. Copies `mode: "create"` `preset_files` **non-destructively** (skips if target already exists, never overwrites).
  2. Merges `scripts` into `package.json` deterministically if `package.json` exists, adding only keys not already present.
  3. Prints any `mode: "snippet"` files (e.g. `pyproject.toml`, `Cargo.toml`) so Claude can merge them with user approval (preserving `apply.py`'s stdlib-only zero-dependency constraint). *(Our call.)*

Workflow order in `skills/claude-devkit/SKILL.md` *(Our call)*:
- Run `audit` in Step 1b.
- Settle both `pending_conflicts` AND `missing_tooling` **before** `apply.py apply` (skipping `missing_tooling` entirely in `--local` mode):
  - For each `missing_tooling` item, one at a time, Claude presents the preset (tools, key rules, files to create, packages/scripts to add) and asks: install preset or skip.
  - If **install**: run `apply.py scaffold-tooling`, apply any printed TOML snippets with user approval (explicitly permitted in `SKILL.md` alongside Step 3b/Step 5), and run package installation with user approval (respecting `guard.py` supply-chain rules). Then proceed to `apply.py apply`, which sees the newly placed `kit.markers` and writes the final `CLAUDE.md`, `settings.json`, and `kit.json` in one pass.
  - If **skip**: pass `"<concern>": "skip"` in `--context -` `decisions` to `apply.py apply`.

### 4. Fast Post-Edit Inner Loop (`base/hooks/format.py` + `kit.json`)

- `write_kit_json` in `apply.py` records `lint_rules` alongside `format_rules`, populated from active concerns whose `post_edit_check` is present and active (`effective` is `adopt_kit` / `keep_both`, or an alternative providing one when `keep_existing`).
- `base/hooks/format.py` (bump `claude-devkit-hook-version` and repo `VERSION`):
  1. Runs matching `format_rules` on the edited file (existing behavior).
  2. Runs matching `lint_rules` on the edited file with a short timeout (e.g. 10s), resolving executables from project-local `.venv` / `node_modules/.bin` first (`resolve_executable`).
  3. Remains **non-blocking** (`exit 0`) so Claude is never deadlocked mid-edit, while printing concise remaining lint diagnostics (capped to a small line budget on `stderr`) so Claude sees and fixes them on its very next step instead of waiting for `Stop`.
- `verify-stop.py` (`Stop`) remains the final blocking gate (`exit 2`) executing the full `verify_command`.

### 5. Reusable Agentic Workflow Assets in `base/`

1. **`base/agents/code-reviewer.md` + `base/skills/review/SKILL.md` (`/review`)**:
   - Synced automatically into `.claude/agents/` and `.claude/skills/` via `sync_extras` (never bloats `CLAUDE.md`).
   - Invoked on demand or before `/commit`: spawns an isolated reviewer subagent (`code-reviewer`) over `git diff` to check test coverage, edge cases, boundary validation, security, and adherence to `CLAUDE.md` invariants — explicitly skipping style/lint concerns already enforced by deterministic tools.
2. **Universal `.editorconfig` preset (`base/presets/.editorconfig`)** *(Our call)*:
   - Not auto-copied silently by `sync_extras`; offered non-destructively during `/claude-devkit` setup when root `.editorconfig` is missing (skipped in `--local` mode).
3. **Zero-dependency `.githooks/pre-commit` template (`base/presets/pre-commit`)** *(Our call)*:
   - Chosen over `lefthook.yml` so no extra binary installation is required.
   - Offered during `/claude-devkit` only when no existing git hook setup (`.husky/`, `.pre-commit-config.yaml`, `lefthook.yml`, `.githooks/`) is detected and mode is not `local`.
   - Upon approval, copies `.githooks/pre-commit` (running fast staged/project lint+format checks) and instructs/runs `git config core.hooksPath .githooks` locally (noting that `core.hooksPath` is per-clone).

### 6. Left to the Builder

- Exact rule lists inside each profile's preset files, provided every rule set is grounded in current official tool documentation (and `sources` / `last_verified` are updated in `profile.json`).
- Exact `stderr` line cap for `lint_rules` output in `format.py` and execution order between `format_rules` and `lint_rules` per file.
- Exact UI phrasing in `skills/claude-devkit/SKILL.md` for walking through `missing_tooling` and `.editorconfig`/`.githooks/pre-commit`, and internal helper layout in `apply.py`.
- Exact wording of `base/agents/code-reviewer.md` and `base/skills/review/SKILL.md` (keeping them concise and consistent with `base/skills/commit/SKILL.md` and `base/skills/handoff/SKILL.md`).
