"""settings.json: build the wanted settings (base + org + profiles) and merge additively."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .core import backup_file, BASE, ORG, read_json, write_text

KIT_HOOK_SCRIPTS = ("guard.py", "format.py", "session-check.py", "verify-stop.py")
_HOOK_SCRIPT_RE = re.compile(r"^\s*HOOK_SCRIPT=([\w.-]+)\s*;")
_HOOK_PATH_RE = re.compile(r"(?:^|/)\.claude/hooks/(" + "|".join(re.escape(s) for s in KIT_HOOK_SCRIPTS) + r")$")


def _kit_hook_tag(command: str) -> str | None:
    """Name of the kit script a hook command runs, or None. Exact matches only (my-guard.py is not guard.py)."""
    m = _HOOK_SCRIPT_RE.match(command)
    if m:
        return m.group(1) if m.group(1) in KIT_HOOK_SCRIPTS else None
    for token in re.findall(r"[^\s\"']+", command):
        m = _HOOK_PATH_RE.search(token.replace("\\", "/"))
        if m:
            return m.group(1)
    return None


def validate_settings_shape(data, label: str) -> None:
    """Abort (SystemExit) if a parsed settings file has a shape the merge cannot handle."""
    def bad(what: str):
        raise SystemExit(f"{label}: {what}. Fix it and re-run (nothing was written).")

    if not isinstance(data, dict):
        bad("top level must be a JSON object")
    perms = data.get("permissions")
    if "permissions" in data and not isinstance(perms, dict):
        bad("'permissions' must be an object")
    for key in ("allow", "deny"):
        rules = (perms or {}).get(key)
        if key in (perms or {}) and (not isinstance(rules, list) or not all(isinstance(r, str) for r in rules)):
            bad(f"'permissions.{key}' must be a list of strings")
    if "hooks" in data and not isinstance(data["hooks"], dict):
        bad("'hooks' must be an object")
    for event, groups in (data.get("hooks") or {}).items():
        if not isinstance(groups, list):
            bad(f"'hooks.{event}' must be a list")
        for group in groups:
            if not isinstance(group, dict):
                bad(f"'hooks.{event}' entries must be objects")
            hooks = group.get("hooks")
            if "hooks" in group and (not isinstance(hooks, list) or not all(isinstance(h, dict) for h in hooks)):
                bad(f"'hooks.{event}[].hooks' must be a list of objects")


def read_settings(path: Path, label: str) -> dict:
    data = read_json(path, label)
    validate_settings_shape(data, f"{path}")
    return data


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
    return read_json(f, "org/settings.json")


def build_wanted_settings(profiles: list, use_org: bool = True) -> dict:
    """Layer settings: base -> org -> stack profiles (always additive)."""
    wanted = read_json(BASE / "settings.base.json", "base/settings.base.json")
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
                   local: bool = False) -> dict:
    """Create or merge settings(.local).json. Returns the permission rules the kit added ({allow, deny})."""
    rel_name = ".claude/settings.local.json" if local else ".claude/settings.json"
    settings_path = project / rel_name
    wanted = build_wanted_settings(profiles, use_org)
    added = {"allow": [], "deny": []}
    if settings_path.exists():
        existing = read_settings(settings_path, rel_name)
        merged, changes = merge_settings(existing, wanted)
        if changes:
            backup_file(settings_path, dry)
            write_text(settings_path, json.dumps(merged, indent=2, ensure_ascii=False) + "\n", dry)
            report.append(f"merged    {rel_name} (+{len(changes)} updates; previous version kept as {rel_name}.bak)")
            report.extend(f"           + {c}" for c in changes)
            for key in added:
                prefix = f"permissions.{key}: "
                added[key] = [c[len(prefix):] for c in changes if c.startswith(prefix)]
        else:
            report.append(f"unchanged {rel_name} (already up to date)")
    else:
        write_text(settings_path, json.dumps(wanted, indent=2, ensure_ascii=False) + "\n", dry)
        report.append(f"created   {rel_name}")
        for key in added:
            added[key] = list(wanted["permissions"].get(key, []))
    return added
