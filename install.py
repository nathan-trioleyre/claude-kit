#!/usr/bin/env python3
"""Install claude-kit for your user (once per machine).

What it does:
  1. copies the skills (/claude-kit, /claude-kit-refresh) into ~/.claude/skills/
  2. removes legacy /bootstrap and /bootstrap-refresh folders from this kit if present
  3. writes ~/.claude/claude-kit.json with the path to this repository and the Python executable

Why store the path? Skills are copied, while stack profiles and scripts stay
in THIS repository (the single source of truth). That way, when /claude-kit
learns a new stack, it saves the profile here, in your Git repo.

Re-run this script after modifying any SKILL.md in the kit.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
LEGACY_SKILLS = ("bootstrap", "bootstrap-refresh")


def remove_legacy_skills(skills_dest: Path) -> None:
    for old_name in LEGACY_SKILLS:
        old_dir = skills_dest / old_name
        skill_md = old_dir / "SKILL.md"
        if skill_md.is_file():
            content = skill_md.read_text(encoding="utf-8", errors="ignore")
            if "claude-bootstrap" in content or "claude-kit" in content:
                shutil.rmtree(old_dir)
                print(f"Removed legacy skill: {old_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claude-dir", default=str(Path.home() / ".claude"),
                        help="Claude Code config directory (default: ~/.claude)")
    args = parser.parse_args()

    claude_dir = Path(args.claude_dir).expanduser()
    skills_dest = claude_dir / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)

    remove_legacy_skills(skills_dest)

    for skill in sorted((KIT / "skills").iterdir()):
        if not (skill / "SKILL.md").is_file():
            continue
        dest = skills_dest / skill.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill, dest, ignore=shutil.ignore_patterns("__pycache__"))
        print(f"Installed skill: {dest}")

    config = claude_dir / "claude-kit.json"
    config.write_text(
        json.dumps({"kit_path": str(KIT), "python": sys.executable}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Kit config saved: {config}")
    print("\nDone. Open Claude Code in a project and type /claude-kit")


if __name__ == "__main__":
    main()
