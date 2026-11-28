# Full Harness Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Equip `claude-devkit` with strict per-language linter/formatter/static-analysis presets, missing-tooling detection and guided scaffolding, fast post-edit lint feedback, and reusable `base/` workflow assets (`/review`, `.editorconfig`, `.githooks/pre-commit`).

**Architecture:** Extend `profile.json`'s `tooling[]` schema (`preset_files`, `install_packages`, `scripts`, `post_edit_check`, `only_when_installed`) and top-level `verify_steps`, update `apply.py` (`validate`, `audit`, `doctor`, `effective_profile`, `write_kit_json`, and new `scaffold-tooling`) while staying stdlib-only, extend `base/hooks/format.py` with bounded `lint_rules`, and add `base/` workflow bricks plus presets across all 7 built-in profiles.

**Tech Stack:** Python 3.9+ (stdlib only), JSON, Markdown skills/agents, `unittest` suite, target ecosystem configs (ESLint flat config, Prettier/Biome, Ruff, Mypy, Roslyn `.globalconfig`/`Directory.Build.props`, Clippy/rustfmt, Hadolint).

**Spec:** `docs/superpowers/specs/2026-11-27-full-harness-workflow-design.md`

## Global Constraints

- `skills/claude-devkit/scripts/apply.py` and `base/hooks/*.py` must remain dependency-free Python 3.9+ (stdlib only) and cross-platform (Windows + Linux/macOS).
- Existing `apply.py` invariants hold: `--dry-run` writes nothing; existing files (`CLAUDE.md`, `.claude/rules/*.md`, and any scaffolded config files) are never silently overwritten; `apply.py validate` enforces schema and permission safety.
- Modifying `base/` requires bumping `VERSION`; modifying `base/hooks/format.py` requires bumping its `claude-devkit-hook-version` marker.
- `tests/` unittest suite must remain dependency-free and pass (`python -m unittest discover -s tests -v`), plus `python skills/claude-devkit/scripts/apply.py validate`.
- `practices.md` <= 15 non-empty lines; `CLAUDE.md` <= 80 lines; `--local` mode never creates or edits repo-wide configs (`package.json`, `pyproject.toml`, `.editorconfig`, `.githooks/`, linter presets).

## Review Focus

- Path traversal or secret-file overwrite via `preset_files` (`src: "../..."`, `dest: ".env"` or `"../x"`) must fail `apply.py validate` and be rejected by `scaffold-tooling` (pinned in Task 1 and Task 3).
- Pre-existing `package.json` scripts or malformed `package.json` must never be overwritten or corrupted by `scaffold-tooling` (pinned in Task 3).
- Partial `verify_command` filtering when `"skip"` or `only_when_installed: true` omits one concern must drop only that concern's step from `verify_steps` while preserving remaining `test`/`build` steps (pinned in Task 2).
- Failing or noisy `lint_rules` in `base/hooks/format.py` must truncate `stderr` to a small line budget and always exit `0` so `PostToolUse` never deadlocks Claude (pinned in Task 4).
- `--local` mode (`apply --local`, `scaffold-tooling --local`) must never write repo-wide root files (`.editorconfig`, `.githooks/pre-commit`, linter presets, `package.json`) (pinned in Task 3 and Task 6).

---

### Task 1: Extended `tooling` & `verify_steps` Schema Validation

**Files:**
- Modify: `skills/claude-devkit/scripts/apply.py:186-367`
- Modify: `profiles/README.md`
- Modify: `profiles/_TEMPLATE/profile.json`
- Test: `tests/test_tooling.py`

**Interfaces:**
- Produces: validated `profile.json` fields:
  - `verify_steps`: list of `{"cmd": str, "concern": str | None}`
  - `tooling[].kit.preset_files`: list of `{"src": str, "dest": str, "mode"?: "create" | "snippet"}`
  - `tooling[].kit.install_packages`: `list[str] | dict[str, list[str]]`
  - `tooling[].kit.scripts`: `dict[str, str]`
  - `tooling[].kit.post_edit_check`: `{"extensions": list[str], "command": list[str]}`
  - `tooling[].kit.only_when_installed`: `bool`
  - Note: `tooling[].alternatives` becomes optional (allowed to be empty or omitted) when `kit` declares `preset_files` / `install_packages` / `scripts` (e.g. `docker` or `csharp-dotnet` `analyzers`).

- [ ] **Step 1: Write failing validation tests in `tests/test_tooling.py`**

Add tests covering:
- `test_validate_accepts_extended_preset_fields_and_verify_steps`: valid `preset_files`, `install_packages` (list or dict), `scripts`, `post_edit_check`, `only_when_installed`, `verify_steps` pass `apply.py validate`.
- `test_validate_rejects_unsafe_preset_paths_and_unsafe_post_edit_check`: rejects `src` escaping profile dir (`../secret`), `dest` escaping project (`../x` or `/abs`), `dest` targeting `.env` or `.env.local`, missing `src` file, `post_edit_check` invoking `UNSAFE_BASH_COMMANDS` (`bash`, `npx`, etc.) or missing `{file}`, and `verify_steps` referencing an unknown `concern`.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_tooling -v`
Expected: FAIL on new tests (validation ignores/rejects new fields or lacks path/command checks).

- [ ] **Step 3: Implement schema validation in `skills/claude-devkit/scripts/apply.py` and document in `profiles/README.md` & `profiles/_TEMPLATE/profile.json`**

In `apply.py`:
- Add helper `_validate_preset_files(prefix: str, folder: Path, items) -> list[str]` checking relative path bounds (`resolve()` strictly inside `folder`), existence of `src`, safe relative `dest` (no `..`, not absolute, not matching protected secret filenames like `.env*`, `*.pem`, `*.key`, `credentials.json`), and `mode in ("create", "snippet")`.
- Add helper `_validate_tool_rule(prefix: str, rule) -> list[str]` reused by both `format_rules[]` and `post_edit_check` (extensions starting with `.`, command list containing `{file}`, executable not in `UNSAFE_BASH_COMMANDS`).
- Validate `install_packages` (`list[str]` or `dict[str, list[str]]`), `scripts` (`dict[str, str]`), `only_when_installed` (`bool`), and `verify_steps` (`list[{"cmd": str, "concern": str | None}]` with `concern` in `None` or declared `tooling` concerns).
- Allow `alternatives` to be empty/omitted only when `kit` defines at least one of `preset_files`, `install_packages`, or `scripts` (keep rejecting empty `alternatives` when `kit` defines none — preserving `test_validate_rejects_malformed_tooling`).
- Update `profiles/README.md` and `profiles/_TEMPLATE/profile.json` concisely.

- [ ] **Step 4: Run tests and `validate` to verify pass**

Run: `python -m unittest tests.test_tooling -v && python skills/claude-devkit/scripts/apply.py validate`
Expected: PASS (all existing + new tests green, `OK: validated 7 profile(s).`).

- [ ] **Step 5: Commit**

```bash
git add skills/claude-devkit/scripts/apply.py profiles/README.md profiles/_TEMPLATE/profile.json tests/test_tooling.py
git commit -m "feat(apply): validate preset_files, post_edit_check, and verify_steps in profiles"
```

---

### Task 2: Missing-Tooling Detection, `"skip"` Decision, `verify_steps` Filtering, & `doctor` `WARN` Tier

**Files:**
- Modify: `skills/claude-devkit/scripts/apply.py:453-623, 1040-1055, 1260-1305, 1420-1463`
- Test: `tests/test_tooling.py`

**Interfaces:**
- Consumes: Task 1 extended `profile.json` fields.
- Produces:
  - `DECISION_CHOICES = ("keep_existing", "adopt_kit", "keep_both", "skip")`
  - `analyze_tooling(project: Path, profiles: list, decisions: dict) -> list[dict]` returning `status` in `("none", "missing", "pending", "resolved", "migration_pending")` and `effective` in `("adopt_kit", "keep_existing", "keep_both", "skip")`
  - `cmd_audit` JSON key `"missing_tooling": [...]`
  - `cmd_doctor` `WARN  ...` lines (exit `0` when only `OK` + `WARN`, exit `1` when `ISSUE` non-empty).

- [ ] **Step 1: Write failing tests in `tests/test_tooling.py`**

Add tests covering:
- `test_audit_reports_missing_tooling_when_no_markers_and_preset_declared`: profile with `kit.markers` + `preset_files` reports `status == "missing"` in `missing_tooling` when markers are absent, and `status == "none"` once a `kit.markers` file exists.
- `test_skip_decision_withholds_commands_permissions_format_and_verify_step`: recording `{"<stack>": {"linter": "skip"}}` omits linter `commands`, `permissions`, `format_rules` (if owned), `lint_rules`, and drops only the linter's `verify_steps` entry while keeping `pytest` in `verify_command`.
- `test_only_when_installed_withholds_until_marker_present`: concern with `only_when_installed: true` (e.g. `mypy`) is withheld from `verify_command` when absent, and included once its marker (`mypy.ini`) is present.
- `test_doctor_warns_without_failing_on_missing_tooling_and_silences_on_skip`: `doctor` outputs `WARN` and exits `0` on unskipped `missing_tooling`, exits `1` if a real `ISSUE` also exists, and stops warning after `apply.py decide ... --choice skip`.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_tooling -v`
Expected: FAIL on the 4 new tests.

- [ ] **Step 3: Implement missing detection, `skip` / `only_when_installed` withholding, `verify_steps` resolution, and `doctor` `WARN` tier in `skills/claude-devkit/scripts/apply.py`**

- In `analyze_tooling`: when `existing` is empty, if `recorded` has `choice == "skip"` -> `status = "resolved", effective = "skip"`; elif `kit_evidence` is empty and (`kit.get("preset_files")` or `kit.get("install_packages")` or `kit.get("scripts")`) -> `status = "missing", effective = ("skip" if kit.get("only_when_installed") else "adopt_kit")`; else `status = "none", effective = ("skip" if kit.get("only_when_installed") and not kit_evidence else "adopt_kit")`.
- In `effective_profile`: apply the same withholding logic to concerns whose `effective == "skip"` (withhold owned `commands`, `permissions`, `format_rules`, `post_edit_check`, `practice_terms`, without injecting a `"Keep the project's own..."` line). When `verify_steps` is present on the profile, compute `eff["commands"]["verify"]` by joining active steps (keeping steps whose `concern` is `None` or not withheld, or replaced if `keep_existing` supplied a `verify` override) with `" && "`.
- In `cmd_audit`: expose `"missing_tooling": [a for a in analysis if a["status"] == "missing"]`.
- In `cmd_doctor`: collect `warns` for `status == "missing"` and print `WARN   ...` lines without raising `SystemExit(1)` unless `issues` is non-empty.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_tooling tests.test_apply -v`
Expected: PASS (all existing tests including `test_no_competing_tool_means_no_conflict_and_kit_applies_as_before` remain green).

- [ ] **Step 5: Commit**

```bash
git add skills/claude-devkit/scripts/apply.py tests/test_tooling.py
git commit -m "feat(apply): detect missing tooling, support skip and verify_steps, warn in doctor"
```

---

### Task 3: `apply.py scaffold-tooling` Subcommand & `base/presets/` Scaffolding

**Files:**
- Modify: `skills/claude-devkit/scripts/apply.py` (add `scaffold_tooling`, `cmd_scaffold_tooling`, CLI parser)
- Create: `base/presets/.editorconfig`
- Create: `base/presets/pre-commit`
- Test: `tests/test_tooling.py`

**Interfaces:**
- Consumes: Task 1 `preset_files`, `scripts`, `install_packages`.
- Produces:
  - CLI `apply.py scaffold-tooling --project <dir> [--profile <stack> --concern <slug>] [--base-preset editorconfig|pre-commit] [--dry-run] [--local]`
  - Helper `merge_package_json_scripts(pkg_path: Path, scripts: dict[str, str], dry: bool, report: list) -> None`

- [ ] **Step 1: Write failing tests in `tests/test_tooling.py`**

Add tests covering:
- `test_scaffold_tooling_creates_presets_non_destructively_and_respects_dry_run`: `--dry-run` creates nothing; real run copies `mode: "create"` files, skips an already-existing destination file without overwriting, and prints `mode: "snippet"` content to stdout without editing TOML files.
- `test_scaffold_tooling_merges_package_json_scripts_without_overwriting`: adds missing `"lint"` / `"format"` keys to `package.json`, preserves existing keys untouched, and fails cleanly if `package.json` is invalid JSON.
- `test_scaffold_tooling_blocks_local_mode_and_supports_base_presets`: `--local` writes nothing (exits non-zero or prints refused message); `--base-preset editorconfig` creates `.editorconfig` non-destructively; `--base-preset pre-commit` creates `.githooks/pre-commit` (executable bit on POSIX) when no `.husky`/`.pre-commit-config.yaml`/`lefthook.yml`/`.githooks` exists.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_tooling -v`
Expected: FAIL (`invalid choice: 'scaffold-tooling'`).

- [ ] **Step 3: Implement `base/presets/.editorconfig`, `base/presets/pre-commit`, and `cmd_scaffold_tooling` in `skills/claude-devkit/scripts/apply.py`**

- Create concise universal `base/presets/.editorconfig` (UTF-8, LF default, 2/4 space conventions by extension, trim trailing whitespace, final newline).
- Create zero-dependency POSIX sh `base/presets/pre-commit` (detects staged files and runs available project format/lint checks fast: `ruff`, `npm run lint` / `eslint` / `prettier`, `dotnet format --verify-no-changes`, `cargo fmt --check`, etc., exiting non-zero on failure).
- Implement `cmd_scaffold_tooling` in `apply.py`:
  - Reject `--local` (or if project `.claude/kit.json` has `"local": true`) with a clear message and non-zero exit so team repo files are never touched in stealth mode.
  - Validate resolved source/dest paths again at runtime against project root & secret patterns.
  - Handle `mode == "create"` via non-destructive copy (`exists()` -> `skipped`, else write + record in report); handle `mode == "snippet"` by printing `SNIPPET <dest>:\n<content>` for Claude/user confirmation.
  - Print `install_packages` summary (selecting the detected package manager's list if keyed by PM) so Claude knows the exact install command to propose.
  - Handle `--base-preset editorconfig` and `--base-preset pre-commit` (checking existing `.husky`, `.pre-commit-config.yaml`, `lefthook.yml`, `.githooks`).

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_tooling -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/claude-devkit/scripts/apply.py base/presets/.editorconfig base/presets/pre-commit tests/test_tooling.py
git commit -m "feat(apply): add scaffold-tooling subcommand and base .editorconfig/pre-commit presets"
```

---

### Task 4: Fast Post-Edit `lint_rules` in `kit.json` & `base/hooks/format.py`

**Files:**
- Modify: `skills/claude-devkit/scripts/apply.py:1057-1095` (`write_kit_json`)
- Modify: `base/hooks/format.py:1-79` (bump `# claude-devkit-hook-version: 4`)
- Modify: `VERSION` (bump minor e.g. `1.7.0` -> `1.8.0`)
- Test: `tests/test_hooks.py`, `tests/test_tooling.py`

**Interfaces:**
- Consumes: Task 1/2 `effective[name]["tooling"]` `post_edit_check` and `lint_rules` extraction.
- Produces:
  - `.claude/kit.json` field `"lint_rules": [{"extensions": [...], "command": [...]}]`
  - `base/hooks/format.py` running `format_rules` and `lint_rules`, truncating lint `stderr` output, always exiting `0`.

- [ ] **Step 1: Write failing tests in `tests/test_tooling.py` and `tests/test_hooks.py`**

Add tests covering:
- `tests/test_tooling.py::test_write_kit_json_records_active_lint_rules_and_drops_skipped`: `kit.json` contains `"lint_rules"` from active `post_edit_check` concerns and omits rules for `"skip"`ed or withheld concerns.
- `tests/test_hooks.py::test_format_hook_runs_lint_rules_truncates_output_and_never_blocks`: invoke `format.py` on a temp project whose `kit.json` defines `lint_rules` calling a tiny temp Python helper script that prints 30 lines of lint errors and exits `1`; assert exit code is `0` and `stderr` contains the tool header plus a truncated tail (<= 15 lines) so Claude gets concise feedback mid-turn.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_hooks tests.test_tooling -v`
Expected: FAIL (`lint_rules` not written to `kit.json` and ignored by `format.py`).

- [ ] **Step 3: Implement `lint_rules` emission in `apply.py`, `lint_rules` execution in `base/hooks/format.py`, and bump `VERSION`**

- In `apply.py` (`effective_profile` + `write_kit_json`): collect active `lint_rules` from each active profile's `tooling` items (or `keep_existing` alternative if it defines `post_edit_check`, omitting `"skip"` or `only_when_installed` when absent) and store `"lint_rules": lint_rules` in `.claude/kit.json`.
- In `base/hooks/format.py`:
  - Bump `# claude-devkit-hook-version: 4`.
  - Extract a shared helper `_run_file_rules(rules, file_path, file_path_str, project, label, max_lines)` used for both `format_rules` (timeout 20s) and `lint_rules` (timeout 10s, truncating output to last 10 non-empty lines when non-zero).
  - Keep `sys.exit(0)` guaranteed.
- Bump `VERSION` to `1.8.0`.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_hooks tests.test_tooling -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/claude-devkit/scripts/apply.py base/hooks/format.py VERSION tests/test_hooks.py tests/test_tooling.py
git commit -m "feat(hooks): run fast per-file lint_rules in format.py and emit them in kit.json"
```

---

### Task 5: Strict AI-Guardrail Presets Across All 7 Built-in Profiles

**Files:**
- Modify & Create presets under:
  - `profiles/python/profile.json` + `profiles/python/presets/ruff.toml` + `profiles/python/presets/mypy.ini`
  - `profiles/typescript/profile.json` + `profiles/typescript/presets/eslint.config.mjs` + `profiles/typescript/presets/.prettierrc` + `profiles/typescript/presets/tsconfig.json`
  - `profiles/nextjs/profile.json` + `profiles/nextjs/presets/eslint.config.mjs` + `profiles/nextjs/presets/.prettierrc`
  - `profiles/angular/profile.json` + `profiles/angular/presets/eslint.config.mjs` + `profiles/angular/presets/.prettierrc`
  - `profiles/csharp-dotnet/profile.json` + `profiles/csharp-dotnet/presets/Directory.Build.props` + `profiles/csharp-dotnet/presets/.globalconfig`
  - `profiles/rust/profile.json` + `profiles/rust/presets/clippy.toml` + `profiles/rust/presets/rustfmt.toml`
  - `profiles/docker/profile.json` + `profiles/docker/presets/.hadolint.yaml`
- Test: `tests/test_tooling.py`

**Interfaces:**
- Consumes: Tasks 1-4 schema, `audit` (`missing_tooling`), `scaffold-tooling`, `verify_steps`, `post_edit_check`.
- Produces: Complete validated profiles with official `sources` and `last_verified` updated.

- [ ] **Step 1: Write failing integration tests for the 7 real profiles in `tests/test_tooling.py`**

Add tests covering:
- `test_real_profiles_report_expected_missing_tooling_on_bare_projects`: bare `tsconfig.json` project reports `typescript/linter` and `typescript/formatter` missing; bare `pyproject.toml` reports `python/linter`, `python/formatter`, `python/typechecker` missing; bare `Dockerfile` reports `docker/linter` missing; bare `Cargo.toml` keeps `cargo clippy` active (`none`) and reports `rust/lint-config` optional preset; bare `*.csproj` keeps `dotnet format` active and reports `csharp-dotnet/analyzers` missing.
- `test_real_profiles_scaffold_presets_cleanly`: scaffolding `python` and `typescript` presets on temp repos places valid config files and updates `package.json` scripts cleanly.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_tooling -v`
Expected: FAIL (real profiles lack `presets/` and new `tooling` concerns).

- [ ] **Step 3: Author presets and update `profile.json` for all 7 profiles**

For each profile, keep official documentation rules (checking current official docs if any rule name is uncertain), focusing on: strict types, dead code/unused imports, complexity/nesting thresholds, explicit error handling, and basic security checks:
- **Python**: `presets/ruff.toml` (`select = ["E", "F", "I", "B", "UP", "SIM", "C90", "S", "RUF"]`, `mccabe.max-complexity = 12`, per-file-ignores for `tests/**` on `S101`), `presets/mypy.ini` (`strict = True`, `warn_unreachable = True`), `post_edit_check: ["ruff", "check", "--fix", "{file}"]`, `verify_steps` separating `ruff check .`, `mypy .` (`only_when_installed: true`), `pytest`.
- **TypeScript / Next.js / Angular**: `presets/eslint.config.mjs` (ESLint 9+ flat config with `@eslint/js`, `typescript-eslint` strictTypeChecked/recommended + `complexity`, `max-depth`, `no-unused-vars`, explicit `any` forbidden; Next.js plugin rules for `nextjs`; `angular-eslint` for `angular`), `presets/.prettierrc`, `presets/tsconfig.json` (strict TS baseline), `post_edit_check` for `eslint --fix` (or `biome check --write` on `biome` alternative), `verify_steps` including `tsc --noEmit`.
- **C# / .NET**: `presets/Directory.Build.props` (`Nullable=enable`, `ImplicitUsings=enable`, `AnalysisLevel=latest-recommended`, `EnforceCodeStyleInBuild=true`) + `presets/.globalconfig` (Roslyn CA/IDE severity rules), under `concern: "analyzers"` (`only_when_installed: true` on build warnings so existing repos aren't surprised).
- **Rust**: `presets/clippy.toml` (`cognitive-complexity-threshold`, `too-many-lines-threshold`) + `presets/rustfmt.toml` under `concern: "lint-config"`.
- **Docker**: `presets/.hadolint.yaml` under `concern: "linter"` (`only_when_installed: true` so projects without `hadolint` installed still use `docker compose config --quiet`).
- Update `sources` and `last_verified` on modified profiles.

- [ ] **Step 4: Run `validate` and `tests` to verify pass**

Run: `python skills/claude-devkit/scripts/apply.py validate && python -m unittest discover -s tests -v`
Expected: `OK: validated 7 profile(s).` and all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add profiles/ tests/test_tooling.py
git commit -m "feat(profiles): add strict AI-guardrail linter and formatter presets for all stacks"
```

---

### Task 6: Reusable `base/` AI Workflow Assets (`/review`, `code-reviewer`) & `/claude-devkit` Skill Update

**Files:**
- Create: `base/agents/code-reviewer.md`
- Create: `base/skills/review/SKILL.md`
- Modify: `skills/claude-devkit/SKILL.md`
- Modify: `README.md`
- Test: `tests/test_apply.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 4, 5 (`audit` `missing_tooling`, `scaffold-tooling`, `--base-preset`, `lint_rules`).
- Produces: `/review` skill + `code-reviewer` agent synced into target projects via `sync_extras`; complete `/claude-devkit` guided workflow.

- [ ] **Step 1: Write failing tests in `tests/test_apply.py`**

Add tests covering:
- `test_apply_syncs_base_review_agent_and_skill_without_copying_base_presets`: running `apply.py apply` copies `.claude/agents/code-reviewer.md` and `.claude/skills/review/SKILL.md` into the project, records them in `kit.json["managed"]`, and does **not** copy `base/presets/*` into `.claude/`.
- `test_local_mode_never_creates_root_presets`: running `apply.py apply --local` keeps `.editorconfig` and `.githooks/pre-commit` absent and leaves `.gitignore` untouched.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_apply -v`
Expected: FAIL (`code-reviewer.md` and `review/SKILL.md` do not exist yet).

- [ ] **Step 3: Author `base/agents/code-reviewer.md`, `base/skills/review/SKILL.md`, and update `skills/claude-devkit/SKILL.md` + `README.md`**

- `base/agents/code-reviewer.md`: concise isolated reviewer prompt (inspect `git diff`, verify `CLAUDE.md` invariants, test coverage, boundary validation, error handling, security; explicitly skip formatting/linting handled by deterministic hooks; classify findings Critical / Important / Minor).
- `base/skills/review/SKILL.md`: `/review` command (`disable-model-invocation: true`) that gathers `git status -sb` + `git diff`, delegates to `code-reviewer` (or runs the checklist inline if subagents unavailable), and outputs actionable findings before `/commit`.
- `skills/claude-devkit/SKILL.md`: update Steps 1b, 3b (add missing-tooling + `.editorconfig` + `.githooks/pre-commit` guided setup *before* `apply.py apply`, skipped in `local` mode, explicitly allowing approved manifest snippet merges + package install + `git config core.hooksPath .githooks`), and Step 6 (mention `/review`).
- `README.md`: briefly document missing-tooling presets, `lint_rules` in `format.py`, `/review`, `.editorconfig`, and `.githooks/pre-commit`.

- [ ] **Step 4: Run full test suite & validation**

Run: `python -m unittest discover -s tests -v && python skills/claude-devkit/scripts/apply.py validate`
Expected: All tests PASS and all 7 profiles validate `OK`.

- [ ] **Step 5: Commit**

```bash
git add base/agents/code-reviewer.md base/skills/review/SKILL.md skills/claude-devkit/SKILL.md README.md tests/test_apply.py
git commit -m "feat(base,skills): add /review workflow, code-reviewer agent, and guided preset setup"
```
