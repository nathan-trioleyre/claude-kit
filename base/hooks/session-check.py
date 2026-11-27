#!/usr/bin/env python3
"""SessionStart hook: injects a concise one-line status if the project has pending kit actions.
# claude-kit-hook-version: 2

Fast and read-only: never modifies files, never blocks (always exits 0).
"""
import json
import os
import sys
from pathlib import Path


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    kit_file = project / ".claude" / "kit.json"
    if not kit_file.is_file():
        return

    notes = []
    for name in ("CLAUDE.md.proposed", "CLAUDE.local.md.proposed"):
        if (project / name).is_file():
            notes.append(f"{name} pending merge")
    rules_dir = project / ".claude" / "rules"
    if rules_dir.is_dir() and any(rules_dir.glob("*.proposed")):
        notes.append(".claude/rules/*.proposed pending merge")

    try:
        kit_data = json.loads(kit_file.read_text(encoding="utf-8"))
        pending = [
            f"{stack}/{concern}"
            for stack, concerns in kit_data.get("decisions", {}).items()
            for concern, val in (concerns or {}).items()
            if isinstance(val, dict) and val.get("choice") == "pending"
        ]
        if pending:
            notes.append(f"unresolved tooling conflicts ({', '.join(pending)})")
    except Exception:
        pass

    if notes:
        print(f"claude-kit: {'; '.join(notes)}. Run /claude-kit doctor for details.")


if __name__ == "__main__":
    main()
    sys.exit(0)
