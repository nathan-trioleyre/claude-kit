import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_apply import KIT, copy_kit, make_profile, run_apply


def kit_with_real_profiles(tmp: Path, *stacks: str) -> Path:
    kit = tmp / "kit"
    copy_kit(kit)
    for stack in stacks:
        shutil.copytree(KIT / "profiles" / stack, kit / "profiles" / stack)
    return kit


def apply_bin_of(kit: Path) -> Path:
    return kit / "skills" / "claude-kit" / "scripts" / "apply.py"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def audit(apply_bin: Path, proj: Path) -> dict:
    return json.loads(run_apply(apply_bin, "audit", "--project", str(proj)).stdout)


def kit_json(proj: Path) -> dict:
    return json.loads((proj / ".claude" / "kit.json").read_text(encoding="utf-8"))


def black_project(tmp: Path) -> Path:
    proj = tmp / "proj"
    write(proj / "pyproject.toml", "[tool.black]\nline-length = 100\n")
    return proj


class TestToolingConflicts(unittest.TestCase):
    def test_audit_reports_black_vs_ruff_and_hand_made_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = black_project(t)
            write(proj / ".claude" / "settings.json", json.dumps({"hooks": {"PostToolUse": [
                {"matcher": "Edit", "hooks": [{"type": "command", "command": "black $CLAUDE_FILE"}]}]}}))
            write(proj / "CLAUDE.md", "# Mine\n\n## Conventions\n- black\n")

            report = audit(apply_bin, proj)
            self.assertEqual(report["pending_conflicts"], 1)
            conflict = next(c for c in report["tooling"] if c["concern"] == "formatter")
            self.assertEqual(conflict["status"], "pending")
            self.assertEqual(conflict["existing"][0]["name"], "black")
            self.assertTrue(any(e.startswith("hook:") for e in conflict["existing"][0]["evidence"]))
            self.assertEqual(report["existing"]["claude_md_sections"], ["Conventions"])
            self.assertEqual(len(report["existing"]["foreign_hooks"]), 1)

    def test_undecided_conflict_withholds_kit_rules_and_keeps_black(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = black_project(t)

            out = run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python").stdout
            self.assertIn("CONFLICT python/formatter", out)
            data = kit_json(proj)
            # the kit's ruff rule is not imposed; black's rule takes its place
            self.assertEqual(data["format_rules"], [{"extensions": [".py"], "command": ["black", "{file}"]}])
            self.assertEqual(data["decisions"], {})
            claude_md = (proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertNotIn("Format and lint with `ruff`", claude_md)
            self.assertIn("Keep the project's own formatter (black)", claude_md)
            doctor = run_apply(apply_bin, "doctor", "--project", str(proj), check=False).stdout
            self.assertIn("tooling conflict python/formatter", doctor)

    def test_adopt_kit_applies_ruff_and_flags_leftovers_until_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = black_project(t)
            ctx = json.dumps({"decisions": {"python": {"formatter": "adopt_kit"}}})
            out = run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python", "--context", "-", input=ctx).stdout
            self.assertIn("traces of black remain", out)
            data = kit_json(proj)
            self.assertEqual(data["format_rules"][0]["command"][0], "ruff")
            self.assertEqual(data["decisions"]["python"]["formatter"]["choice"], "adopt_kit")
            self.assertEqual(data["decisions"]["python"]["formatter"]["existing"], ["black"])
            doctor = run_apply(apply_bin, "doctor", "--project", str(proj), check=False).stdout
            self.assertIn("finish the migration", doctor)

            # migration done by hand: the traces disappear, the issue with them
            write(proj / "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
            doctor = run_apply(apply_bin, "doctor", "--project", str(proj), check=False).stdout
            self.assertNotIn("finish the migration", doctor)
            self.assertNotIn("tooling conflict", doctor)

    def test_keep_existing_decision_persists_across_sync_and_decide_can_flip_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = black_project(t)
            ctx = json.dumps({"decisions": {"python": {"formatter": {"choice": "keep_existing"}}}})
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python", "--context", "-", input=ctx)
            self.assertEqual(kit_json(proj)["format_rules"][0]["command"][0], "black")

            out = run_apply(apply_bin, "sync", "--project", str(proj)).stdout
            self.assertIn("tooling   python/formatter: keep_existing (black)", out)
            self.assertNotIn("CONFLICT", out)
            self.assertEqual(kit_json(proj)["format_rules"][0]["command"][0], "black")
            doctor = run_apply(apply_bin, "doctor", "--project", str(proj), check=False).stdout
            self.assertNotIn("tooling conflict", doctor)

            run_apply(apply_bin, "decide", "--project", str(proj), "--profile", "python",
                      "--concern", "formatter", "--choice", "adopt_kit")
            run_apply(apply_bin, "sync", "--project", str(proj))
            self.assertEqual(kit_json(proj)["format_rules"][0]["command"][0], "ruff")

    def test_permissions_commands_and_practices_follow_the_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = t / "poetry-proj"
            write(proj / "pyproject.toml", "[tool.poetry]\nname = 'x'\n")
            write(proj / "poetry.lock", "")
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python")

            allow = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
            self.assertNotIn("Bash(uv sync*)", allow)
            self.assertNotIn("Bash(uv run pytest*)", allow)
            self.assertIn("Bash(poetry install*)", allow)
            self.assertIn("Bash(pytest*)", allow)  # unrelated kit permission stays
            claude_md = (proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("- Install: `poetry install`", claude_md)
            self.assertNotIn("uv sync", claude_md)
            self.assertNotIn("Manage dependencies and the virtualenv with `uv`", claude_md)

    def test_no_competing_tool_means_no_conflict_and_kit_applies_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = t / "clean"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n\n[tool.ruff]\nline-length = 100\n")
            out = run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python").stdout
            self.assertNotIn("CONFLICT", out)
            self.assertEqual(kit_json(proj)["format_rules"][0]["command"][0], "ruff")
            self.assertEqual(audit(apply_bin, proj)["pending_conflicts"], 0)

    def test_invalid_decision_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = black_project(t)
            ctx = json.dumps({"decisions": {"python": {"formatter": "whatever"}}})
            res = run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python",
                            "--context", "-", input=ctx, check=False)
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse((proj / "CLAUDE.md").exists())

    def test_decide_requires_a_configured_project_and_known_concern(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = black_project(t)
            args = ("decide", "--project", str(proj), "--profile", "python", "--concern", "formatter", "--choice", "keep_existing")
            self.assertNotEqual(run_apply(apply_bin, *args, check=False).returncode, 0)
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python")
            bad = run_apply(apply_bin, "decide", "--project", str(proj), "--profile", "python",
                            "--concern", "nope", "--choice", "adopt_kit", check=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("no tooling concern", bad.stderr)
            self.assertEqual(run_apply(apply_bin, *args).returncode, 0)

    def test_angular_pnpm_project_gets_pnpm_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "angular"))
            proj = t / "ng"
            write(proj / "angular.json", "{}")
            write(proj / "pnpm-lock.yaml", "")
            out = run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "angular").stdout
            self.assertIn("angular/package-manager", out)
            claude_md = (proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("pnpm install --frozen-lockfile", claude_md)
            self.assertNotIn("npm ci", claude_md)

    def test_existing_claude_md_gets_a_section_level_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = t / "p"
            write(proj / "pyproject.toml", "[project]\nname='x'\n")
            write(proj / "CLAUDE.md", "# Mine\n\n## Conventions\n- tabs forever\n\n## Deploy\n- push to prod\n")
            out = run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python", "--dry-run").stdout
            self.assertIn("only in the kit's version", out)
            self.assertIn("only in your file (kept as is): Deploy", out)
            self.assertIn("present in both but different: Conventions", out)

    def test_validate_rejects_malformed_tooling(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python")
            apply_bin = apply_bin_of(kit)
            pj = kit / "profiles" / "python" / "profile.json"
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["tooling"][0]["alternatives"] = []
            data["tooling"][1]["kit"]["permissions"] = ["Bash(curl *)"]
            data["tooling"][2]["concern"] = "formatter"
            pj.write_text(json.dumps(data), encoding="utf-8")
            res = run_apply(apply_bin, "validate", check=False)
            self.assertNotEqual(res.returncode, 0)
            err = res.stdout + res.stderr
            self.assertIn("alternatives must be a non-empty list", err)
            self.assertIn("curl", err)
            self.assertIn("duplicated", err)

    def test_poetry_with_ruff_or_flake8_keeps_correct_linter_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))

            # Poetry + ruff (no linter conflict) keeps poetry run ruff lint/format/verify
            proj_ruff = t / "poetry-ruff"
            write(proj_ruff / "pyproject.toml", "[tool.poetry]\nname = 'x'\n\n[tool.ruff]\n")
            write(proj_ruff / "poetry.lock", "")
            run_apply(apply_bin, "apply", "--project", str(proj_ruff), "--profiles", "python")
            md_ruff = (proj_ruff / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("- Lint: `poetry run ruff check .`", md_ruff)
            self.assertIn("- Verify (before concluding a task): `poetry run ruff check . && poetry run pytest`", md_ruff)

            # Poetry + flake8 (both package-manager and linter kept): flake8 wins for lint
            proj_f8 = t / "poetry-flake8"
            write(proj_f8 / "pyproject.toml", "[tool.poetry]\nname = 'x'\n")
            write(proj_f8 / "poetry.lock", "")
            write(proj_f8 / ".flake8", "[flake8]\n")
            run_apply(apply_bin, "apply", "--project", str(proj_f8), "--profiles", "python")
            md_f8 = (proj_f8 / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("- Install: `poetry install`", md_f8)
            self.assertIn("- Lint: `poetry run flake8 .`", md_f8)
            self.assertIn("`poetry run flake8 . && poetry run pytest`", md_f8)
            self.assertNotIn("`poetry run ruff check", md_f8)

    def test_validate_accepts_extended_preset_fields_and_verify_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python")
            apply_bin = apply_bin_of(kit)
            prof_dir = kit / "profiles" / "custom"
            write(prof_dir / "presets" / "lint.toml", "line-length = 100\n")
            write(prof_dir / "practices.md", "- Use customlint.\n")
            write(prof_dir / "profile.json", json.dumps({
                "stack": "custom",
                "display_name": "Custom Stack",
                "detect": ["custom.toml"],
                "commands": {
                    "install": "custom install",
                    "dev": None,
                    "test": "custom test",
                    "lint": "customlint check .",
                    "format": "customlint format .",
                    "build": None,
                    "verify": "customlint check . && custom test",
                },
                "verify_steps": [
                    {"cmd": "customlint check .", "concern": "linter"},
                    {"cmd": "custom test", "concern": None},
                ],
                "permissions_allow": ["Bash(custom test*)"],
                "format_rules": [{"extensions": [".cst"], "command": ["customlint", "format", "{file}"]}],
                "tooling": [
                    {
                        "concern": "linter",
                        "kit": {
                            "name": "customlint",
                            "markers": [{"file": "lint.toml"}],
                            "commands": ["lint"],
                            "preset_files": [{"src": "presets/lint.toml", "dest": "lint.toml", "mode": "create"}],
                            "install_packages": {"npm": ["customlint"], "uv": ["customlint"]},
                            "scripts": {"lint": "customlint check ."},
                            "post_edit_check": {"extensions": [".cst"], "command": ["customlint", "check", "--fix", "{file}"]},
                            "only_when_installed": False,
                        }
                    }
                ],
                "sources": ["https://example.test/docs"],
                "last_verified": "2026-11-27",
            }, indent=2))
            res = run_apply(apply_bin, "validate", "--profiles", "custom", check=False)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_validate_rejects_unsafe_preset_paths_and_unsafe_post_edit_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python")
            apply_bin = apply_bin_of(kit)
            prof_dir = kit / "profiles" / "badpreset"
            write(prof_dir / "presets" / "ok.toml", "x = 1\n")
            write(prof_dir / "practices.md", "- Practice.\n")
            base_profile = {
                "stack": "badpreset",
                "display_name": "Bad Preset",
                "detect": ["bad.toml"],
                "commands": {"verify": "pytest"},
                "verify_steps": [{"cmd": "pytest", "concern": "unknown_concern"}],
                "permissions_allow": [],
                "format_rules": [],
                "tooling": [
                    {
                        "concern": "linter",
                        "kit": {
                            "name": "badlint",
                            "markers": [],
                            "preset_files": [
                                {"src": "../python/profile.json", "dest": "ok.toml"},
                                {"src": "presets/missing.toml", "dest": "../escape.toml"},
                                {"src": "presets/ok.toml", "dest": ".env"},
                            ],
                            "post_edit_check": {"extensions": [".py"], "command": ["bash", "-c", "{file}"]},
                        }
                    }
                ],
                "sources": ["https://example.test/docs"],
                "last_verified": "2026-11-27",
            }
            write(prof_dir / "profile.json", json.dumps(base_profile, indent=2))
            res = run_apply(apply_bin, "validate", "--profiles", "badpreset", check=False)
            self.assertNotEqual(res.returncode, 0)
            err = res.stdout + res.stderr
            self.assertIn("unknown_concern", err)
            self.assertIn("preset_files", err)
            self.assertIn(".env", err)
            self.assertIn("post_edit_check", err)

    def _kit_with_preset_profile(self, tmp: Path, *, only_when_installed: bool = False):
        kit = tmp / "kit"
        copy_kit(kit)
        prof = kit / "profiles" / "pydemo"
        write(prof / "presets" / "ruff.toml", "line-length = 100\n")
        write(prof / "presets" / "mypy.ini", "[mypy]\nstrict = True\n")
        write(prof / "practices.md", "- Use ruff.\n- Use pytest.\n")
        write(prof / "profile.json", json.dumps({
            "stack": "pydemo",
            "display_name": "PyDemo",
            "detect": ["pyproject.toml"],
            "commands": {
                "install": "uv sync",
                "dev": None,
                "test": "uv run pytest",
                "lint": "uv run ruff check .",
                "format": "uv run ruff format .",
                "build": None,
                "verify": "uv run ruff check . && uv run mypy . && uv run pytest",
            },
            "verify_steps": [
                {"cmd": "uv run ruff check .", "concern": "linter"},
                {"cmd": "uv run mypy .", "concern": "typechecker"},
                {"cmd": "uv run pytest", "concern": None},
            ],
            "permissions_allow": ["Bash(uv run pytest*)", "Bash(uv run ruff*)", "Bash(uv run mypy*)"],
            "format_rules": [{"extensions": [".py"], "command": ["ruff", "format", "{file}"]}],
            "tooling": [
                {
                    "concern": "linter",
                    "kit": {
                        "name": "ruff",
                        "markers": [{"file": "ruff.toml"}],
                        "commands": ["lint", "format"],
                        "format_rules": True,
                        "permissions": ["Bash(uv run ruff*)"],
                        "practice_terms": ["ruff"],
                        "preset_files": [{"src": "presets/ruff.toml", "dest": "ruff.toml"}],
                    }
                },
                {
                    "concern": "typechecker",
                    "kit": {
                        "name": "mypy",
                        "markers": [{"file": "mypy.ini"}],
                        "commands": [],
                        "permissions": ["Bash(uv run mypy*)"],
                        "only_when_installed": only_when_installed,
                        "preset_files": [{"src": "presets/mypy.ini", "dest": "mypy.ini"}],
                    }
                },
            ],
            "sources": ["https://example.test"],
            "last_verified": "2026-11-27",
        }, indent=2))
        return kit, apply_bin_of(kit)

    def test_unsafe_permission_allows_runner_with_specific_tool_only(self):
        scripts = str(KIT / "skills" / "claude-kit" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kitlib.core import unsafe_permission
        for rule in ("Bash(npx *)", "Bash(npx*)", "Bash(uvx *)", "Bash(docker *)", "Bash(docker run*)",
                     "Bash(docker exec*)", "Bash(npx bash*)", "Bash(uvx python*)", "Bash(docker compose run*)"):
            self.assertIsNotNone(unsafe_permission(rule), rule)
        for rule in ("Bash(npx tsc*)", "Bash(npx eslint*)", "Bash(uvx deptry*)", "Bash(uvx vulture*)",
                     "Bash(uvx pip-audit*)", "Bash(bunx tsc*)", "Bash(docker build*)", "Bash(docker compose config*)"):
            self.assertIsNone(unsafe_permission(rule), rule)

    def test_missing_tooling_is_withheld_from_verify_until_adopt_kit(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            apply_bin = apply_bin_of(kit_with_real_profiles(t, "python"))
            proj = t / "bare"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python")
            kj = kit_json(proj)
            self.assertNotIn("ruff", kj["verify_command"])
            self.assertNotIn("mypy", kj["verify_command"])
            self.assertEqual(kj["lint_rules"], [])
            md = (proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertNotIn("ruff check", md)
            missing = audit(apply_bin, proj)["missing_tooling"]
            self.assertTrue(missing)
            self.assertTrue(all(m["effective"] == "skip" for m in missing))

            ctx = json.dumps({"decisions": {"python": {"linter": "adopt_kit"}}})
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "python", "--context", "-", input=ctx)
            kj = kit_json(proj)
            self.assertIn("uv run ruff check .", kj["verify_command"])
            self.assertEqual(kj["lint_rules"][0]["command"][0], "ruff")

    def test_audit_reports_missing_tooling_when_no_markers_and_preset_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            _, apply_bin = self._kit_with_preset_profile(t)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            rep = audit(apply_bin, proj)
            missing_concerns = [m["concern"] for m in rep["missing_tooling"]]
            self.assertEqual(missing_concerns, ["linter", "typechecker"])

            write(proj / "ruff.toml", "line-length = 100\n")
            rep2 = audit(apply_bin, proj)
            self.assertEqual([m["concern"] for m in rep2["missing_tooling"]], ["typechecker"])

    def test_skip_decision_withholds_commands_permissions_format_and_verify_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            _, apply_bin = self._kit_with_preset_profile(t)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            ctx = json.dumps({"decisions": {"pydemo": {"linter": "skip"}}})
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "pydemo", "--context", "-", input=ctx)
            kj = kit_json(proj)
            self.assertEqual(kj["format_rules"], [])
            self.assertEqual(kj["verify_command"], "uv run pytest")  # typechecker is missing too: withheld
            allow = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
            self.assertNotIn("Bash(uv run ruff*)", allow)
            self.assertIn("Bash(uv run pytest*)", allow)
            md = (proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertNotIn("uv run ruff check .", md)
            self.assertNotIn("Use ruff.", md)

    def test_only_when_installed_withholds_until_marker_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            _, apply_bin = self._kit_with_preset_profile(t, only_when_installed=True)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            write(proj / "ruff.toml", "line-length = 100\n")
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "pydemo")
            self.assertEqual(kit_json(proj)["verify_command"], "uv run ruff check . && uv run pytest")
            allow = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
            self.assertNotIn("Bash(uv run mypy*)", allow)

            write(proj / "mypy.ini", "[mypy]\n")
            run_apply(apply_bin, "sync", "--project", str(proj))
            self.assertEqual(kit_json(proj)["verify_command"], "uv run ruff check . && uv run mypy . && uv run pytest")

    def test_doctor_warns_without_failing_on_missing_tooling_and_silences_on_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            _, apply_bin = self._kit_with_preset_profile(t, only_when_installed=True)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            ctx = json.dumps({"name": "P", "description": "D", "architecture": "A", "gotchas": "G"})
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "pydemo", "--context", "-", input=ctx)
            doc = run_apply(apply_bin, "doctor", "--project", str(proj), check=False)
            self.assertEqual(doc.returncode, 0, doc.stdout)
            self.assertIn("WARN", doc.stdout)
            self.assertIn("pydemo/linter", doc.stdout)

            # A real issue still makes doctor exit 1 alongside WARN
            (proj / "CLAUDE.md").unlink()
            doc_fail = run_apply(apply_bin, "doctor", "--project", str(proj), check=False)
            self.assertEqual(doc_fail.returncode, 1)
            self.assertIn("WARN", doc_fail.stdout)
            self.assertIn("ISSUE", doc_fail.stdout)

            # Skipping both silences WARN
            run_apply(apply_bin, "decide", "--project", str(proj), "--profile", "pydemo", "--concern", "linter", "--choice", "skip")
            run_apply(apply_bin, "decide", "--project", str(proj), "--profile", "pydemo", "--concern", "typechecker", "--choice", "skip")
            doc_clean = run_apply(apply_bin, "doctor", "--project", str(proj), check=False)
            self.assertNotIn("WARN", doc_clean.stdout)

    def test_scaffold_tooling_creates_presets_non_destructively_and_respects_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = t / "kit"
            copy_kit(kit)
            prof = kit / "profiles" / "pydemo"
            write(prof / "presets" / "ruff.toml", "line-length = 100\n")
            write(prof / "presets" / "pyproject.snippet.toml", "[tool.ruff]\nline-length = 100\n")
            write(prof / "practices.md", "- Use ruff.\n")
            write(prof / "profile.json", json.dumps({
                "stack": "pydemo",
                "display_name": "PyDemo",
                "detect": ["pyproject.toml"],
                "commands": {"verify": "ruff check ."},
                "permissions_allow": [],
                "format_rules": [],
                "tooling": [{
                    "concern": "linter",
                    "kit": {
                        "name": "ruff",
                        "markers": [{"file": "ruff.toml"}],
                        "preset_files": [
                            {"src": "presets/ruff.toml", "dest": "ruff.toml", "mode": "create"},
                            {"src": "presets/pyproject.snippet.toml", "dest": "pyproject.toml", "mode": "snippet"},
                        ],
                        "install_packages": ["ruff"],
                    }
                }],
                "sources": ["https://example.test"],
                "last_verified": "2026-11-27",
            }, indent=2))
            apply_bin = apply_bin_of(kit)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")

            dry = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                            "--profile", "pydemo", "--concern", "linter", "--dry-run")
            self.assertFalse((proj / "ruff.toml").exists())
            self.assertIn("DRY-RUN", dry.stdout)

            out = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                            "--profile", "pydemo", "--concern", "linter").stdout
            self.assertEqual((proj / "ruff.toml").read_text(encoding="utf-8"), "line-length = 100\n")
            self.assertIn("SNIPPET pyproject.toml:", out)
            self.assertIn("[tool.ruff]", out)
            self.assertIn("install_packages: ruff", out)
            self.assertEqual((proj / "pyproject.toml").read_text(encoding="utf-8"), "[project]\nname = 'x'\n")

            # Existing destination file is never overwritten
            (proj / "ruff.toml").write_text("# custom\n", encoding="utf-8")
            out2 = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                             "--profile", "pydemo", "--concern", "linter").stdout
            self.assertIn("skipped", out2)
            self.assertEqual((proj / "ruff.toml").read_text(encoding="utf-8"), "# custom\n")

    def test_scaffold_tooling_merges_package_json_scripts_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = t / "kit"
            copy_kit(kit)
            prof = kit / "profiles" / "tsdemo"
            write(prof / "presets" / "eslint.config.mjs", "export default [];\n")
            write(prof / "practices.md", "- Use eslint.\n")
            write(prof / "profile.json", json.dumps({
                "stack": "tsdemo",
                "display_name": "TSDemo",
                "detect": ["tsconfig.json"],
                "commands": {"verify": "npm run lint"},
                "permissions_allow": [],
                "format_rules": [],
                "tooling": [{
                    "concern": "linter",
                    "kit": {
                        "name": "eslint",
                        "markers": [{"file": "eslint.config.mjs"}],
                        "preset_files": [{"src": "presets/eslint.config.mjs", "dest": "eslint.config.mjs"}],
                        "scripts": {"lint": "eslint .", "format": "prettier --write ."},
                        "install_packages": {"npm": ["eslint"], "pnpm": ["eslint"]},
                    }
                }],
                "sources": ["https://example.test"],
                "last_verified": "2026-11-27",
            }, indent=2))
            apply_bin = apply_bin_of(kit)
            proj = t / "proj"
            write(proj / "tsconfig.json", "{}")
            write(proj / "package.json", json.dumps({"name": "demo", "scripts": {"lint": "custom-lint"}}))

            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                      "--profile", "tsdemo", "--concern", "linter")
            pkg = json.loads((proj / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(pkg["scripts"]["lint"], "custom-lint")
            self.assertEqual(pkg["scripts"]["format"], "prettier --write .")

            # Invalid package.json fails cleanly without corrupting file
            bad_proj = t / "badproj"
            write(bad_proj / "tsconfig.json", "{}")
            write(bad_proj / "package.json", "{not-json")
            res = run_apply(apply_bin, "scaffold-tooling", "--project", str(bad_proj),
                            "--profile", "tsdemo", "--concern", "linter", check=False)
            self.assertNotEqual(res.returncode, 0)
            self.assertEqual((bad_proj / "package.json").read_text(encoding="utf-8"), "{not-json")

    def test_scaffold_tooling_blocks_local_mode_and_supports_base_presets(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            _, apply_bin = self._kit_with_preset_profile(t)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            res = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                            "--base-preset", "editorconfig", "--local", check=False)
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse((proj / ".editorconfig").exists())

            # Base preset editorconfig & pre-commit work in normal mode
            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj), "--base-preset", "editorconfig")
            self.assertTrue((proj / ".editorconfig").is_file())
            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj), "--base-preset", "pre-commit")
            self.assertTrue((proj / ".githooks" / "pre-commit").is_file())

            # Skips pre-commit if another hook framework already exists
            proj2 = t / "proj2"
            (proj2 / ".husky").mkdir(parents=True)
            out = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj2), "--base-preset", "pre-commit").stdout
            self.assertIn("skipped", out)
            self.assertFalse((proj2 / ".githooks" / "pre-commit").exists())

    def test_write_kit_json_records_active_lint_rules_and_drops_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = t / "kit"
            copy_kit(kit)
            prof = kit / "profiles" / "pydemo"
            write(prof / "presets" / "ruff.toml", "line-length = 100\n")
            write(prof / "practices.md", "- Use ruff.\n")
            write(prof / "profile.json", json.dumps({
                "stack": "pydemo",
                "display_name": "PyDemo",
                "detect": ["pyproject.toml"],
                "commands": {"verify": "ruff check ."},
                "permissions_allow": [],
                "format_rules": [],
                "tooling": [{
                    "concern": "linter",
                    "kit": {
                        "name": "ruff",
                        "markers": [{"file": "ruff.toml"}],
                        "preset_files": [{"src": "presets/ruff.toml", "dest": "ruff.toml"}],
                        "post_edit_check": {"extensions": [".py"], "command": ["ruff", "check", "--fix", "{file}"]},
                    },
                    "alternatives": [{
                        "name": "flake8",
                        "markers": [{"file": ".flake8"}],
                        "post_edit_check": {"extensions": [".py"], "command": ["flake8", "{file}"]},
                    }],
                }],
                "sources": ["https://example.test"],
                "last_verified": "2026-11-27",
            }, indent=2))
            apply_bin = apply_bin_of(kit)
            proj = t / "proj"
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
            run_apply(apply_bin, "apply", "--project", str(proj), "--profiles", "pydemo")
            self.assertEqual(kit_json(proj)["lint_rules"], [])  # missing tool: withheld until adopt_kit
            run_apply(apply_bin, "decide", "--project", str(proj), "--profile", "pydemo", "--concern", "linter", "--choice", "adopt_kit")
            run_apply(apply_bin, "sync", "--project", str(proj))
            self.assertEqual(kit_json(proj)["lint_rules"], [{"extensions": [".py"], "command": ["ruff", "check", "--fix", "{file}"]}])

            run_apply(apply_bin, "decide", "--project", str(proj), "--profile", "pydemo", "--concern", "linter", "--choice", "skip")
            run_apply(apply_bin, "sync", "--project", str(proj))
            self.assertEqual(kit_json(proj)["lint_rules"], [])

            # Keep existing alternative uses alternative's post_edit_check if present
            proj2 = t / "proj2"
            write(proj2 / "pyproject.toml", "[project]\nname = 'x'\n")
            write(proj2 / ".flake8", "[flake8]\n")
            ctx = json.dumps({"decisions": {"pydemo": {"linter": "keep_existing"}}})
            run_apply(apply_bin, "apply", "--project", str(proj2), "--profiles", "pydemo", "--context", "-", input=ctx)
            self.assertEqual(kit_json(proj2)["lint_rules"], [{"extensions": [".py"], "command": ["flake8", "{file}"]}])

    def test_real_profiles_report_expected_missing_tooling_on_bare_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python", "typescript", "docker", "rust", "csharp-dotnet")
            apply_bin = apply_bin_of(kit)

            ts_proj = t / "ts"
            write(ts_proj / "tsconfig.json", "{}")
            ts_missing = {m["concern"] for m in audit(apply_bin, ts_proj)["missing_tooling"]}
            self.assertEqual(ts_missing, {"linter", "formatter"})

            py_proj = t / "py"
            write(py_proj / "pyproject.toml", "[project]\nname='p'\n")
            py_missing = {m["concern"] for m in audit(apply_bin, py_proj)["missing_tooling"]}
            self.assertEqual(py_missing, {"linter", "formatter", "typechecker"})

            dk_proj = t / "dk"
            write(dk_proj / "Dockerfile", "FROM python:3.12-slim\n")
            dk_missing = {m["concern"] for m in audit(apply_bin, dk_proj)["missing_tooling"]}
            self.assertEqual(dk_missing, {"linter"})

            rs_proj = t / "rs"
            write(rs_proj / "Cargo.toml", "[package]\nname='r'\nversion='0.1.0'\n")
            rs_rep = audit(apply_bin, rs_proj)
            self.assertEqual({m["concern"] for m in rs_rep["missing_tooling"]}, {"lint-config"})
            self.assertEqual(rs_rep["pending_conflicts"], 0)

            cs_proj = t / "cs"
            write(cs_proj / "App.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n")
            cs_rep = audit(apply_bin, cs_proj)
            self.assertEqual({m["concern"] for m in cs_rep["missing_tooling"]}, {"analyzers"})
            self.assertEqual(cs_rep["pending_conflicts"], 0)

    def test_real_profiles_scaffold_presets_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python", "typescript")
            apply_bin = apply_bin_of(kit)

            py_proj = t / "py"
            write(py_proj / "pyproject.toml", "[project]\nname='p'\n")
            run_apply(apply_bin, "scaffold-tooling", "--project", str(py_proj), "--profile", "python", "--concern", "linter")
            self.assertTrue((py_proj / "ruff.toml").is_file())

            ts_proj = t / "ts"
            write(ts_proj / "tsconfig.json", "{}")
            write(ts_proj / "package.json", json.dumps({"name": "ts-app"}))
            run_apply(apply_bin, "scaffold-tooling", "--project", str(ts_proj), "--profile", "typescript", "--concern", "linter")
            run_apply(apply_bin, "scaffold-tooling", "--project", str(ts_proj), "--profile", "typescript", "--concern", "formatter")
            self.assertTrue((ts_proj / "eslint.config.mjs").is_file())
            self.assertTrue((ts_proj / ".prettierrc").is_file())
            pkg = json.loads((ts_proj / "package.json").read_text(encoding="utf-8"))
            self.assertIn("lint", pkg["scripts"])
            self.assertIn("format", pkg["scripts"])

    def test_verify_steps_with_package_manager_and_skip_across_real_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "typescript", "python", "angular")
            apply_bin = apply_bin_of(kit)

            # 1. TypeScript + pnpm + linter skipped preserves tsc, pnpm test, pnpm build
            ts_proj = t / "ts-pnpm"
            write(ts_proj / "tsconfig.json", "{}")
            write(ts_proj / "pnpm-lock.yaml", "")
            ctx_ts = json.dumps({"decisions": {"typescript": {"linter": "skip", "package-manager": "keep_existing"}}})
            run_apply(apply_bin, "apply", "--project", str(ts_proj), "--profiles", "typescript", "--context", "-", input=ctx_ts)
            self.assertEqual(kit_json(ts_proj)["verify_command"], "pnpm exec tsc --noEmit && pnpm test && pnpm run build")

            # 2. Python + poetry + linter skipped uses poetry run pytest, never uv run pytest
            py_proj = t / "py-poetry"
            write(py_proj / "pyproject.toml", "[tool.poetry]\nname='p'\n")
            write(py_proj / "poetry.lock", "")
            ctx_py = json.dumps({"decisions": {"python": {"linter": "skip", "package-manager": "keep_existing"}}})
            run_apply(apply_bin, "apply", "--project", str(py_proj), "--profiles", "python", "--context", "-", input=ctx_py)
            self.assertEqual(kit_json(py_proj)["verify_command"], "poetry run pytest")

            # 3. Angular + linter skipped keeps test && build (not None), and eslint preset uses eslint .
            ng_proj = t / "ng"
            write(ng_proj / "angular.json", "{}")
            write(ng_proj / "package.json", json.dumps({"name": "ng-app"}))
            ctx_ng = json.dumps({"decisions": {"angular": {"linter": "skip"}}})
            run_apply(apply_bin, "apply", "--project", str(ng_proj), "--profiles", "angular", "--context", "-", input=ctx_ng)
            self.assertEqual(kit_json(ng_proj)["verify_command"], "npm test -- --no-watch && npm run build")
            run_apply(apply_bin, "scaffold-tooling", "--project", str(ng_proj), "--profile", "angular", "--concern", "linter")
            ng_pkg = json.loads((ng_proj / "package.json").read_text(encoding="utf-8"))
            self.assertEqual(ng_pkg["scripts"]["lint"], "eslint .")

    def test_validate_rejects_dot_dest_and_scaffold_is_atomic_on_bad_package_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "typescript")
            apply_bin = apply_bin_of(kit)

            # dest="." must fail validate
            bad = kit / "profiles" / "dotdest"
            write(bad / "presets" / "x.txt", "hi\n")
            write(bad / "practices.md", "- Practice.\n")
            write(bad / "profile.json", json.dumps({
                "stack": "dotdest",
                "display_name": "DotDest",
                "detect": ["dot.txt"],
                "commands": {"verify": "true"},
                "permissions_allow": [],
                "format_rules": [],
                "tooling": [{"concern": "linter", "kit": {"name": "x", "preset_files": [{"src": "presets/x.txt", "dest": "."}]}}],
                "sources": ["https://example.test"],
                "last_verified": "2026-11-27",
            }))
            res = run_apply(apply_bin, "validate", "--profiles", "dotdest", check=False)
            self.assertNotEqual(res.returncode, 0)

            # Bad package.json must abort before writing eslint.config.mjs
            proj = t / "badpkg"
            write(proj / "tsconfig.json", "{}")
            write(proj / "package.json", "{bad-json")
            res2 = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                             "--profile", "typescript", "--concern", "linter", check=False)
            self.assertNotEqual(res2.returncode, 0)
            self.assertFalse((proj / "eslint.config.mjs").exists())

    def test_kit_presets_do_not_trigger_stack_detect_false_positives(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "angular", "csharp-dotnet", "docker", "nextjs", "python", "rust", "typescript")
            apply_bin = apply_bin_of(kit)
            out = run_apply(apply_bin, "detect", "--project", str(kit)).stdout
            data = json.loads(out)
            self.assertEqual(data["matched"], [])

    def test_scaffold_tooling_base_preset_ci_generates_non_destructive_workflow_and_blocks_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python", "typescript")
            apply_bin = apply_bin_of(kit)
            proj = t / "mono"
            write(proj / "pyproject.toml", "[project]\nname='api'\n")
            write(proj / "tsconfig.json", "{}")
            write(proj / "pnpm-lock.yaml", "")

            res_local = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                                  "--base-preset", "ci", "--local", check=False)
            self.assertNotEqual(res_local.returncode, 0)
            self.assertFalse((proj / ".github" / "workflows" / "ci.yml").exists())

            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj), "--base-preset", "ci")
            ci_file = proj / ".github" / "workflows" / "ci.yml"
            self.assertTrue(ci_file.is_file())
            ci_text = ci_file.read_text(encoding="utf-8")
            self.assertIn("uv sync", ci_text)
            self.assertIn("uv run pytest", ci_text)
            self.assertIn("pnpm install --frozen-lockfile", ci_text)
            self.assertIn("pnpm test", ci_text)

            # Never overwrites existing ci.yml
            ci_file.write_text("name: custom\n", encoding="utf-8")
            out2 = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj), "--base-preset", "ci").stdout
            self.assertIn("skipped", out2)
            self.assertEqual(ci_file.read_text(encoding="utf-8"), "name: custom\n")

    def test_scaffold_tooling_base_preset_ci_targets_gitlab_when_remote_is_gitlab(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python", "typescript")
            apply_bin = apply_bin_of(kit)
            proj = t / "mono"
            write(proj / "pyproject.toml", "[project]\nname='api'\n")
            write(proj / "tsconfig.json", "{}")
            write(proj / "pnpm-lock.yaml", "")
            subprocess.run(["git", "init", "-q", str(proj)], check=True)
            subprocess.run(["git", "-C", str(proj), "remote", "add", "origin",
                            "git@gitlab.com:team/mono.git"], check=True)

            out = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj), "--base-preset", "ci").stdout
            self.assertIn(".gitlab-ci.yml", out)
            self.assertFalse((proj / ".github").exists())
            gl = (proj / ".gitlab-ci.yml").read_text(encoding="utf-8")
            self.assertIn("image: python:3.12", gl)
            self.assertIn("pip install uv", gl)
            self.assertIn("uv sync", gl)
            self.assertIn("image: node:22", gl)
            self.assertIn("corepack enable", gl)
            self.assertIn("pnpm install --frozen-lockfile", gl)
            self.assertIn("merge_request_event", gl)
            self.assertNotIn("actions/", gl)

            # Never overwrites an existing .gitlab-ci.yml
            (proj / ".gitlab-ci.yml").write_text("stages: [x]\n", encoding="utf-8")
            out2 = run_apply(apply_bin, "scaffold-tooling", "--project", str(proj), "--base-preset", "ci").stdout
            self.assertIn("skipped", out2)
            self.assertEqual((proj / ".gitlab-ci.yml").read_text(encoding="utf-8"), "stages: [x]\n")

    def test_scaffold_tooling_ci_provider_flag_overrides_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "rust")
            apply_bin = apply_bin_of(kit)
            proj = t / "selfhosted"
            write(proj / "Cargo.toml", "[package]\nname='x'\nversion='0.1.0'\n")
            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                      "--base-preset", "ci", "--ci-provider", "gitlab")
            gl = (proj / ".gitlab-ci.yml").read_text(encoding="utf-8")
            self.assertIn("image: rust:1", gl)
            self.assertIn("rustup component add clippy rustfmt", gl)
            self.assertIn("cargo fetch", gl)

    def test_scaffold_tooling_ci_installs_go_toolchain_and_golangci_lint(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "go")
            apply_bin = apply_bin_of(kit)
            proj = t / "svc"
            write(proj / "go.mod", "module example.com/svc\n\ngo 1.23\n")
            write(proj / ".golangci.yml", "version: \"2\"\n")

            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                      "--base-preset", "ci", "--ci-provider", "github")
            gh = (proj / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertIn("actions/setup-go@v5", gh)
            self.assertIn("go-version-file: go.mod", gh)
            self.assertIn("golangci/golangci-lint-action@v9", gh)
            self.assertIn("install-only: true", gh)
            self.assertIn("golangci-lint run", gh)

            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj),
                      "--base-preset", "ci", "--ci-provider", "gitlab")
            gl = (proj / ".gitlab-ci.yml").read_text(encoding="utf-8")
            self.assertIn("image: golangci/golangci-lint:v2.", gl)
            self.assertIn("golangci-lint run", gl)

            # Without the linter in verify, plain Go image and no lint install
            proj2 = t / "nolint"
            write(proj2 / "go.mod", "module example.com/nolint\n\ngo 1.23\n")
            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj2),
                      "--base-preset", "ci", "--ci-provider", "github")
            gh2 = (proj2 / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
            self.assertIn("actions/setup-go@v5", gh2)
            self.assertNotIn("golangci", gh2)
            run_apply(apply_bin, "scaffold-tooling", "--project", str(proj2),
                      "--base-preset", "ci", "--ci-provider", "gitlab")
            self.assertIn("image: golang:1", (proj2 / ".gitlab-ci.yml").read_text(encoding="utf-8"))

    def test_real_profiles_expose_targeted_tests_hygiene_and_audit_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            kit = kit_with_real_profiles(t, "python", "typescript", "rust", "csharp-dotnet")
            apply_bin = apply_bin_of(kit)

            py_proj = t / "py"
            write(py_proj / "pyproject.toml", "[project]\nname='p'\n")
            run_apply(apply_bin, "apply", "--project", str(py_proj), "--profiles", "python")
            py_md = (py_proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("Test (targeted):", py_md)
            self.assertIn("Dead code / unused deps:", py_md)
            self.assertIn("Security / dependency audit:", py_md)
            self.assertLessEqual(len(py_md.splitlines()), 80)

            ts_proj = t / "ts"
            write(ts_proj / "tsconfig.json", "{}")
            write(ts_proj / "pnpm-lock.yaml", "")
            ctx = json.dumps({"decisions": {"typescript": {"package-manager": {"choice": "keep_existing"}}}})
            run_apply(apply_bin, "apply", "--project", str(ts_proj), "--profiles", "typescript", "--context", "-", input=ctx)
            ts_md = (ts_proj / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn("pnpm audit", ts_md)


class TestRunnerPlaceholder(unittest.TestCase):
    """The {run} placeholder resolves to the runner of the package manager in effect."""

    @staticmethod
    def _effective(stack: str, files: dict, decisions: dict | None = None) -> dict:
        scripts = str(KIT / "skills" / "claude-kit" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kitlib.core import load_profile
        from kitlib.tooling import analyze_tooling, effective_profile

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            for name, text in files.items():
                write(proj / name, text)
            profile = load_profile(stack)
            analysis = analyze_tooling(proj, [profile], {stack: decisions or {}})
            return effective_profile(profile, analysis)

    def test_poetry_with_flake8_uses_poetry_runner(self):
        eff = self._effective("python", {"pyproject.toml": "[tool.poetry]\n", "poetry.lock": "", ".flake8": "[flake8]\n"})
        self.assertEqual(eff["commands"]["lint"], "poetry run flake8 .")
        self.assertEqual(eff["commands"]["verify"], "poetry run flake8 . && poetry run pytest")
        self.assertIn("Bash(poetry run flake8*)", eff["permissions_allow"])

    def test_poetry_with_mypy_verify_step(self):
        eff = self._effective("python", {"pyproject.toml": "[tool.poetry]\n[tool.ruff]\n[tool.mypy]\n", "poetry.lock": ""})
        self.assertEqual(eff["commands"]["verify"], "poetry run ruff check . && poetry run mypy . && poetry run pytest")
        self.assertIn("Bash(poetry run mypy*)", eff["permissions_allow"])
        self.assertFalse(any("uv run" in r for r in eff["permissions_allow"]))

    def test_kit_runner_when_nothing_kept(self):
        eff = self._effective("python", {"pyproject.toml": "[tool.uv]\n[tool.mypy]\n", "uv.lock": ""})
        self.assertIn("uv run mypy .", eff["commands"]["verify"])
        self.assertIn("Bash(uv run pytest*)", eff["permissions_allow"])
        self.assertIn("Bash(uvx deptry*)", eff["permissions_allow"])

    def test_js_runners_per_package_manager(self):
        expected = {"pnpm-lock.yaml": "pnpm exec", "yarn.lock": "yarn", "bun.lock": "bunx", "package-lock.json": "npx"}
        for lock, runner in expected.items():
            with self.subTest(lock=lock):
                eff = self._effective("typescript", {"tsconfig.json": "{}", lock: ""}, {"package-manager": {"choice": "keep_existing"}})
                self.assertIn(f"{runner} tsc --noEmit", eff["commands"]["verify"])
                self.assertIn(f"Bash({runner} tsc*)", eff["permissions_allow"])
                self.assertIn(f"{runner} knip", eff["commands"]["hygiene"])
                self.assertFalse(any("{run}" in r for r in eff["permissions_allow"]))

    def test_vue_and_react_vite_keep_runner_in_verify(self):
        eff = self._effective("vue", {"package.json": "{}", "pnpm-lock.yaml": ""}, {"package-manager": {"choice": "keep_existing"}})
        self.assertIn("pnpm exec vue-tsc --build", eff["commands"]["verify"])
        eff = self._effective("react-vite", {"package.json": "{}", "yarn.lock": ""}, {"package-manager": {"choice": "keep_existing"}})
        self.assertIn("yarn tsc -b", eff["commands"]["verify"])

    def test_profile_without_runner_gets_bare_tool(self):
        scripts = str(KIT / "skills" / "claude-kit" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kitlib.tooling import substitute_runner

        self.assertEqual(substitute_runner("{run} flake8 .", None), "flake8 .")
        self.assertEqual(substitute_runner("Bash({run} flake8*)", None), "Bash(flake8*)")
        self.assertEqual(substitute_runner(["{run}", "ruff", "{file}"], "uv run"), ["uv", "run", "ruff", "{file}"])
        self.assertEqual(substitute_runner(["{run}", "ruff", "{file}"], None), ["ruff", "{file}"])
        eff = self._effective("php", {"composer.json": "{}"})
        self.assertNotIn("{run}", json.dumps(eff["commands"]))

    def test_no_placeholder_leaks_in_any_real_profile(self):
        scripts = str(KIT / "skills" / "claude-kit" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kitlib.core import profile_dirs
        for folder in profile_dirs():
            with self.subTest(stack=folder.name):
                eff = self._effective(folder.name, {})
                dumped = json.dumps({k: eff.get(k) for k in ("commands", "verify_steps", "permissions_allow", "format_rules", "lint_rules")})
                self.assertNotIn("{run}", dumped)

    def test_validate_expands_runner_in_permissions(self):
        scripts = str(KIT / "skills" / "claude-kit" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kitlib.core import unsafe_permission

        runners = {"uv run", "poetry run", "npx", "bunx", "pnpm exec"}
        self.assertIsNone(unsafe_permission("Bash({run} flake8*)", runners))
        self.assertIsNone(unsafe_permission("Bash(npx tsc*)"))
        self.assertIsNone(unsafe_permission("Bash(uvx deptry*)"))
        self.assertIsNone(unsafe_permission("Bash(bunx eslint*)"))
        self.assertIsNone(unsafe_permission("Bash(pnpm exec tsc*)"))
        self.assertIsNotNone(unsafe_permission("Bash({run} *)", runners))
        self.assertIsNotNone(unsafe_permission("Bash({run} bash*)", runners))
        self.assertIsNotNone(unsafe_permission("Bash(npx *)"))

    def test_verify_steps_match_default_verify_in_real_profiles(self):
        scripts = str(KIT / "skills" / "claude-kit" / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from kitlib.core import load_profile, profile_dirs
        for folder in profile_dirs():
            p = load_profile(folder.name)
            if p.get("verify_steps") and p["commands"].get("verify"):
                with self.subTest(stack=folder.name):
                    joined = " && ".join(s["cmd"] for s in p["verify_steps"])
                    self.assertEqual(joined, p["commands"]["verify"])


if __name__ == "__main__":
    unittest.main()
