import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


class TestInstall(unittest.TestCase):
    def test_install_copies_skills_cleans_legacy_and_records_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = Path(tmp) / ".claude"
            skills_dir = claude_dir / "skills"

            # Seed legacy kit skills + an unrelated third-party skill
            for old in ("bootstrap", "bootstrap-refresh"):
                (skills_dir / old).mkdir(parents=True)
                (skills_dir / old / "SKILL.md").write_text("---\nname: old\n---\nclaude-bootstrap", encoding="utf-8")
            (skills_dir / "third-party").mkdir(parents=True)
            (skills_dir / "third-party" / "SKILL.md").write_text("---\nname: third-party\n---\nCustom skill", encoding="utf-8")

            res = subprocess.run(
                [sys.executable, str(KIT / "install.py"), "--claude-dir", str(claude_dir)],
                capture_output=True, text=True, check=True,
            )
            self.assertIn("Done.", res.stdout)
            self.assertTrue((skills_dir / "claude-kit" / "SKILL.md").is_file())
            self.assertTrue((skills_dir / "claude-kit-refresh" / "SKILL.md").is_file())
            self.assertFalse((skills_dir / "bootstrap").exists())
            self.assertFalse((skills_dir / "bootstrap-refresh").exists())
            self.assertTrue((skills_dir / "third-party" / "SKILL.md").is_file())

            config_path = claude_dir / "claude-kit.json"
            self.assertTrue(config_path.is_file(), "install.py should write claude-kit.json")
            data = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(data["kit_path"]), KIT)
            self.assertEqual(Path(data["python"]), Path(sys.executable))


if __name__ == "__main__":
    unittest.main()
