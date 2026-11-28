#!/usr/bin/env python3
"""Install claude-kit for your user (once per machine).

What it does:
  1. installs the skills (/claude-kit, /claude-kit-refresh, /claude-kit-learn) into ~/.claude/skills/
  2. writes ~/.claude/claude-kit.json with the path to this repository and the Python executable

Two modes:
  default   copies the skills (re-run this script after editing a SKILL.md)
  --link    links the skills to this repository instead (symlink, or a junction on
            Windows): edits to SKILL.md files and apply.py are live, no reinstall needed.

  --uninstall  removes the kit's skills and ~/.claude/claude-kit.json (other skills and
               configured projects are left alone; use `apply.py uninstall` per project).

Why store the path? Stack profiles and scripts stay in THIS repository (the single
source of truth). When /claude-kit learns a new stack, it saves the profile here,
in your Git repo.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent


def remove_path(path: Path) -> None:
    """Remove a file, a (real or junction) link, or a directory tree."""
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        if os.name == "nt" and is_junction(path):
            os.rmdir(path)  # removes the junction only, never the target's content
        else:
            shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def is_junction(path: Path) -> bool:
    try:
        return bool(os.path.isjunction(path))  # Python 3.12+
    except AttributeError:
        return os.name == "nt" and path.is_dir() and bool(
            os.stat(path, follow_symlinks=False).st_file_attributes & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        )


def link_dir(src: Path, dest: Path) -> str:
    """Create dest -> src. Returns the link kind used. Raises OSError if impossible."""
    try:
        os.symlink(src, dest, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(dest), str(src)], capture_output=True, text=True)
    if result.returncode != 0:
        raise OSError(result.stderr.strip() or result.stdout.strip() or "mklink /J failed")
    return "junction"


def kit_skill_names() -> list:
    return sorted(s.name for s in (KIT / "skills").iterdir() if (s / "SKILL.md").is_file())


def uninstall(claude_dir: Path) -> None:
    """Remove only what install.py created: the kit's skills (links or copies) and the kit config."""
    skills_dest = claude_dir / "skills"
    for name in kit_skill_names():
        dest = skills_dest / name
        if dest.exists() or dest.is_symlink():
            remove_path(dest)  # a link/junction is removed without touching this repository
            print(f"Removed skill: {dest}")
    config = claude_dir / "claude-kit.json"
    if config.is_file():
        config.unlink()
        print(f"Removed kit config: {config}")
    print("\nDone. Projects configured with /claude-kit keep their files; "
          "run `apply.py uninstall --project <path>` in each one first if you want them cleaned too.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claude-dir", default=str(Path.home() / ".claude"),
                        help="Claude Code config directory (default: ~/.claude)")
    parser.add_argument("--link", action="store_true",
                        help="link skills to this repository instead of copying them")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove the kit's skills and ~/.claude/claude-kit.json (projects are untouched)")
    args = parser.parse_args()

    claude_dir = Path(args.claude_dir).expanduser()
    if args.uninstall:
        uninstall(claude_dir)
        return
    skills_dest = claude_dir / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)

    for skill in sorted((KIT / "skills").iterdir()):
        if not (skill / "SKILL.md").is_file():
            continue
        dest = skills_dest / skill.name
        if dest.exists() or dest.is_symlink():
            remove_path(dest)
        if args.link:
            try:
                kind = link_dir(skill, dest)
                print(f"Linked skill ({kind}): {dest} -> {skill}")
                continue
            except OSError as exc:
                print(f"Could not link {dest.name} ({exc}); copying instead.")
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
