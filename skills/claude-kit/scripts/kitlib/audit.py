"""`audit`: read-only inventory of what a project already has, plus tooling conflicts (JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from .core import load_profile, PROFILES, read_text_lossy, split_sections
from .detect import detect_matched
from .preflight import preflight
from .settings import build_wanted_settings, read_settings
from .tooling import analyze_tooling, effective_profile, foreign_hooks


def cmd_audit(args) -> None:
    """Read-only inventory of what the project already has, plus tooling conflicts."""
    project = Path(args.project).resolve()
    kit_json = preflight(project)
    names = args.profiles or sorted(set(detect_matched(project)) | set(kit_json.get("profiles", {})))
    names = [n for n in names if (PROFILES / n / "profile.json").is_file()]
    profiles = [load_profile(n) for n in names]
    analysis = analyze_tooling(project, profiles, kit_json.get("decisions", {}))

    claude_md = project / "CLAUDE.md"
    sections = list(split_sections(read_text_lossy(claude_md))) if claude_md.is_file() else []
    managed = set(kit_json.get("managed", {}))
    claude_dir = project / ".claude"
    own_files = []
    if claude_dir.is_dir():
        for path in sorted(claude_dir.rglob("*")):
            rel = path.relative_to(project).as_posix()
            if (path.is_file() and rel not in managed and not rel.endswith((".proposed", "settings.json", "kit.json"))
                    and ".claude/logs/" not in rel and not rel.endswith("settings.local.json")):
                own_files.append(rel)
    extra_allow = []
    settings_path = claude_dir / "settings.json"
    if settings_path.is_file():
        allow = read_settings(settings_path, ".claude/settings.json").get("permissions", {}).get("allow", [])
        wanted = build_wanted_settings([effective_profile(p, analysis) for p in profiles], not args.no_org)
        extra_allow = [r for r in allow if r not in wanted["permissions"]["allow"]]

    print(json.dumps({
        "profiles": names,
        "kit_configured": bool(kit_json),
        "existing": {
            "claude_md": claude_md.is_file(),
            "claude_md_sections": sections,
            "project_owned_claude_files": own_files,
            "foreign_hooks": foreign_hooks(project),
            "foreign_permissions": extra_allow,
        },
        "tooling": [a for a in analysis if a["status"] not in ("none", "missing")],
        "missing_tooling": [a for a in analysis if a["status"] == "missing"],
        "pending_conflicts": sum(1 for a in analysis if a["status"] == "pending"),
    }, ensure_ascii=False, indent=2))
