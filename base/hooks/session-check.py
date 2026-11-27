#!/usr/bin/env python3
"""SessionStart hook: injects a concise one-line status if the project has pending kit actions.
# claude-kit-hook-version: 3

Fast and read-only: never modifies files, never blocks (always exits 0).
"""
import json
import os
import re
import sys
from pathlib import Path

NODE_PROFILES = {"typescript", "nextjs", "angular", "javascript", "node", "react", "vue"}


def check_npmrc_supply_chain(kit_data: dict) -> str | None:
    profiles = set(kit_data.get("profiles", {}))
    if not (profiles & NODE_PROFILES):
        return None
    npmrc = Path.home() / ".npmrc"
    text = ""
    try:
        if npmrc.is_file():
            text = npmrc.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    missing = []
    if not re.search(r"(?im)^\s*ignore-scripts\s*=\s*true\s*$", text):
        missing.append("ignore-scripts=true")
    if not re.search(r"(?im)^\s*save-exact\s*=\s*true\s*$", text):
        missing.append("save-exact=true")
    if missing:
        return f"~/.npmrc missing {', '.join(missing)} (supply-chain hardening)"
    return None


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
        npm_note = check_npmrc_supply_chain(kit_data)
        if npm_note:
            notes.append(npm_note)
    except Exception:
        pass

    if notes:
        print(f"claude-kit: {'; '.join(notes)}. Run /claude-kit doctor for details.")


if __name__ == "__main__":
    main()
    sys.exit(0)
