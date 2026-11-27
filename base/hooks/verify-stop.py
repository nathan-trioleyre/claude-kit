#!/usr/bin/env python3
"""Stop hook (opt-in): runs the project's verify command before Claude finishes a turn.
# claude-kit-hook-version: 1

Opt-in per project: only runs when `.claude/kit.json` sets `"stop_verify": true`
and `"verify_command"` is non-empty. Exits immediately (0) otherwise.

Safety guards:
- Checks `stop_hook_active` in stdin JSON to prevent infinite retry loops.
- Skips when the git working tree has no uncommitted changes.
- On failure, prints a concise error to stderr and exits 2 so Claude fixes it.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def has_git_changes(project: Path) -> bool:
    """Return True if git reports modified/untracked files, or if git is unavailable."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return bool(res.stdout.strip())
    except Exception:
        pass
    return True


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("stop_hook_active"):
        return 0

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    kit_file = project / ".claude" / "kit.json"
    if not kit_file.is_file():
        return 0

    try:
        kit_data = json.loads(kit_file.read_text(encoding="utf-8"))
    except Exception:
        return 0

    if not kit_data.get("stop_verify"):
        return 0

    verify_cmd = (kit_data.get("verify_command") or "").strip()
    if not verify_cmd:
        return 0

    if not has_git_changes(project):
        return 0

    try:
        res = subprocess.run(
            verify_cmd,
            shell=True,
            cwd=project,
            capture_output=True,
            text=True,
            timeout=110,
        )
    except subprocess.TimeoutExpired:
        print(f"BLOCKED: verify command timed out: {verify_cmd}", file=sys.stderr)
        return 2

    if res.returncode != 0:
        output = "\n".join(line for line in ((res.stdout or "") + "\n" + (res.stderr or "")).splitlines()[-20:])
        print(f"BLOCKED: '{verify_cmd}' failed (exit {res.returncode}). Fix before concluding:\n{output}",
              file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
