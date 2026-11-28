"""Preflight: parse and shape-check every JSON file a command will read, before ANY write."""

from __future__ import annotations

from pathlib import Path

from .core import load_kit_json, read_json
from .settings import read_settings


def preflight(project: Path) -> dict:
    """Abort with a clear message (SystemExit) if a project file is unreadable or has the wrong shape.

    Returns kit.json (empty dict when the project was never configured).
    """
    kit_json = load_kit_json(project)
    for name in ("settings.json", "settings.local.json"):
        f = project / ".claude" / name
        if f.is_file():
            read_settings(f, f".claude/{name}")
    mcp = project / ".mcp.json"
    if mcp.is_file():
        data = read_json(mcp, ".mcp.json")
        if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
            raise SystemExit(f".mcp.json ({mcp}): 'mcpServers' must be an object: leaving it untouched.")
    pkg = project / "package.json"
    if pkg.is_file():
        data = read_json(pkg, "package.json")
        if "scripts" in data and not isinstance(data["scripts"], dict):
            raise SystemExit(f"package.json ({pkg}): 'scripts' must be an object: leaving it untouched.")
    for key, kind in (("profiles", dict), ("decisions", dict), ("managed", dict), ("rendered", dict)):
        if key in kit_json and not isinstance(kit_json[key], kind):
            raise SystemExit(f"kit.json: '{key}' must be an object. Fix or delete .claude/kit.json and re-run.")
    return kit_json
