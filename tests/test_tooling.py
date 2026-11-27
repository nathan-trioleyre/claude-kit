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
            write(proj / "pyproject.toml", "[project]\nname = 'x'\n")
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


if __name__ == "__main__":
    unittest.main()
