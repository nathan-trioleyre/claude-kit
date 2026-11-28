"""settings.json: build the wanted settings (base + org + profiles) and merge additively."""

import json
from pathlib import Path

from .core import BASE, ORG, write_text


def _kit_hook_tag(command: str) -> str | None:
    if ".claude/hooks/" not in command:
        return None
    for script in ("guard.py", "format.py", "session-check.py", "verify-stop.py"):
        if script in command:
            return script
    return None


def merge_settings(existing: dict, wanted: dict):
    result = json.loads(json.dumps(existing))
    changes = []
    perms = result.setdefault("permissions", {})
    for key in ("allow", "deny"):
        current = perms.setdefault(key, [])
        for rule in wanted.get("permissions", {}).get(key, []):
            if rule not in current:
                current.append(rule)
                changes.append(f"permissions.{key}: {rule}")

    hooks = result.setdefault("hooks", {})
    for event, groups in wanted.get("hooks", {}).items():
        current_groups = hooks.setdefault(event, [])
        for wanted_group in groups:
            wanted_matcher = wanted_group.get("matcher")
            for wanted_hook in wanted_group.get("hooks", []):
                wanted_cmd = wanted_hook["command"]
                wanted_tag = _kit_hook_tag(wanted_cmd)

                exact_group = next(
                    (g for g in current_groups if any(h.get("command") == wanted_cmd for h in g.get("hooks", []))),
                    None,
                )
                if exact_group is not None:
                    if wanted_matcher and exact_group.get("matcher") != wanted_matcher:
                        exact_group["matcher"] = wanted_matcher
                        changes.append(f"hooks.{event} matcher -> {wanted_matcher}")
                    continue

                if wanted_tag:
                    upgraded = False
                    for g in list(current_groups):
                        group_hooks = g.get("hooks", [])
                        kept = [h for h in group_hooks if _kit_hook_tag(h.get("command", "")) != wanted_tag]
                        if len(kept) != len(group_hooks):
                            upgraded = True
                            if kept:
                                g["hooks"] = kept
                            else:
                                current_groups.remove(g)
                    if upgraded:
                        current_groups.append({**wanted_group, "hooks": [wanted_hook]})
                        changes.append(f"upgraded hooks.{event}: {wanted_cmd}")
                        continue

                current_groups.append({**wanted_group, "hooks": [wanted_hook]})
                changes.append(f"hooks.{event}: {wanted_cmd}")

    return result, changes


def load_org_settings() -> dict:
    f = ORG / "settings.json"
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise SystemExit(f"{f} is not valid JSON.")


def build_wanted_settings(profiles: list, use_org: bool = True) -> dict:
    """Layer settings: base -> org -> stack profiles (always additive)."""
    wanted = json.loads((BASE / "settings.base.json").read_text(encoding="utf-8"))
    allow = wanted["permissions"]["allow"]
    deny = wanted["permissions"]["deny"]
    if use_org:
        org = load_org_settings()
        for key, target in (("allow", allow), ("deny", deny)):
            for rule in org.get("permissions", {}).get(key, []):
                if rule not in target:
                    target.append(rule)
        for event, groups in org.get("hooks", {}).items():
            wanted["hooks"].setdefault(event, []).extend(groups)
    for p in profiles:
        for rule in p.get("permissions_allow", []):
            if rule not in allow:
                allow.append(rule)
    return wanted


def read_org_text(name: str) -> str:
    f = ORG / name
    return f.read_text(encoding="utf-8").strip() if f.is_file() else ""


def apply_settings(project: Path, profiles: list, dry: bool, report: list, use_org: bool,
                   local: bool = False) -> None:
    rel_name = ".claude/settings.local.json" if local else ".claude/settings.json"
    settings_path = project / rel_name
    wanted = build_wanted_settings(profiles, use_org)
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise SystemExit(f"{settings_path} is not valid JSON: leaving it untouched. Fix it and re-run.")
        merged, changes = merge_settings(existing, wanted)
        if changes:
            write_text(settings_path, json.dumps(merged, indent=2, ensure_ascii=False) + "\n", dry)
            report.append(f"merged    {rel_name} (+{len(changes)} updates)")
            report.extend(f"           + {c}" for c in changes)
        else:
            report.append(f"unchanged {rel_name} (already up to date)")
    else:
        write_text(settings_path, json.dumps(wanted, indent=2, ensure_ascii=False) + "\n", dry)
        report.append(f"created   {rel_name}")
