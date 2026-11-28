import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
SKILLS = ("claude-devkit", "claude-devkit-refresh", "claude-devkit-learn")


def install(claude_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(KIT / "install.py"), "--claude-dir", str(claude_dir), *extra],
        capture_output=True, text=True, check=True,
    )


class TestInstall(unittest.TestCase):
    def test_install_copies_skills_and_records_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = Path(tmp) / ".claude"
            skills_dir = claude_dir / "skills"
            (skills_dir / "third-party").mkdir(parents=True)
            (skills_dir / "third-party" / "SKILL.md").write_text("---\nname: third-party\n---\nCustom skill", encoding="utf-8")

            res = install(claude_dir)
            self.assertIn("Done.", res.stdout)
            for name in SKILLS:
                self.assertTrue((skills_dir / name / "SKILL.md").is_file(), name)
                self.assertFalse((skills_dir / name).is_symlink())
            self.assertTrue((skills_dir / "third-party" / "SKILL.md").is_file())

            data = json.loads((claude_dir / "claude-devkit.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(data["kit_path"]), KIT)
            self.assertEqual(Path(data["python"]), Path(sys.executable))

    def test_link_mode_reflects_kit_edits_and_reinstall_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = Path(tmp) / ".claude"
            install(claude_dir, "--link")
            install(claude_dir, "--link")  # second run must replace links cleanly
            for name in SKILLS:
                self.assertTrue((claude_dir / "skills" / name / "SKILL.md").is_file(), name)
            link = claude_dir / "skills" / "claude-devkit"
            self.assertEqual((link / "SKILL.md").read_text(encoding="utf-8"),
                             (KIT / "skills" / "claude-devkit" / "SKILL.md").read_text(encoding="utf-8"))
            # switching back to copy mode must not delete the kit's own skill files
            install(claude_dir)
            self.assertTrue((KIT / "skills" / "claude-devkit" / "SKILL.md").is_file())
            self.assertFalse((claude_dir / "skills" / "claude-devkit").is_symlink())

    def test_uninstall_removes_only_kit_skills_and_config(self):
        for mode in ((), ("--link",)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                claude_dir = Path(tmp) / ".claude"
                skills_dir = claude_dir / "skills"
                (skills_dir / "third-party").mkdir(parents=True)
                (skills_dir / "third-party" / "SKILL.md").write_text("custom", encoding="utf-8")
                install(claude_dir, *mode)

                res = install(claude_dir, "--uninstall")
                self.assertIn("Done.", res.stdout)
                for name in SKILLS:
                    self.assertFalse((skills_dir / name).exists(), name)
                    # removing a link must never delete the kit's own files
                    self.assertTrue((KIT / "skills" / name / "SKILL.md").is_file(), name)
                self.assertFalse((claude_dir / "claude-devkit.json").exists())
                self.assertTrue((skills_dir / "third-party" / "SKILL.md").is_file())

                install(claude_dir, "--uninstall")  # idempotent when nothing is installed


if __name__ == "__main__":
    unittest.main()
