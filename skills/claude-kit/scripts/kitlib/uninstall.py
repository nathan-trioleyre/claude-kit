"""`uninstall`: remove what the kit added to a project, keeping everything the user owns or edited."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core import backup_file, emit, sha256_norm, write_text
from .ignore import remove_kit_lines, resolve_git_exclude
from .preflight import preflight
from .settings import _kit_hook_tag, read_settings


def _prune_settings(data: dict, added: dict | None) -> tuple:
    """Remove kit hooks and (when recorded) the permission rules the kit added. Returns (data, notes)."""
    notes = []
    hooks = data.get("hooks") or {}
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            kept = [h for h in group.get("hooks", []) if _kit_hook_tag(str(h.get("command", ""))) is None]
            removed = len(group.get("hooks", [])) - len(kept)
            if removed:
                notes.append(f"hooks.{event}: -{removed} kit hook(s)")
            if kept or "hooks" not in group:
                groups.append({**group, "hooks": kept} if "hooks" in group else group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        data.pop("hooks", None)
    perms = data.get("permissions")
    if isinstance(perms, dict) and added:
        for key in ("allow", "deny", "ask"):
            drop = set(added.get(key, []))
            current = perms.get(key, [])
            kept = [r for r in current if r not in drop]
            if len(kept) != len(current):
                notes.append(f"permissions.{key}: -{len(current) - len(kept)} rule(s) added by the kit")
            if kept:
                perms[key] = kept
            else:
                perms.pop(key, None)
        if not perms:
            data.pop("permissions", None)
    return data, notes


def _prune_empty_dirs(claude_dir: Path, dry: bool) -> None:
    if dry or not claude_dir.is_dir():
        return
    for root, _dirs, _files in os.walk(claude_dir, topdown=False):
        try:
            Path(root).rmdir()  # only succeeds when empty
        except OSError:
            pass


def cmd_uninstall(args) -> None:
    project = Path(args.project).resolve()
    dry = args.dry_run
    kit_json = preflight(project)
    if not kit_json:
        raise SystemExit("No .claude/kit.json: this project was never configured by the kit, nothing to uninstall.")
    report = []

    # 1. kit-managed files: removed only while they still match what the kit installed
    for label, recorded_hash in sorted(kit_json.get("managed", {}).items()):
        path = project / label
        if not path.is_file():
            continue
        if sha256_norm(path.read_bytes()) == recorded_hash:
            if not dry:
                path.unlink()
            report.append(f"removed   {label}")
        else:
            report.append(f"kept      {label} (modified since the kit installed it)")

    # 2. kit hooks and permission rules in settings(.local).json
    all_added = kit_json.get("added_permissions")
    for name in ("settings.json", "settings.local.json"):
        rel = f".claude/{name}"
        path = project / rel
        if not path.is_file():
            continue
        data, notes = _prune_settings(read_settings(path, rel), (all_added or {}).get(rel))
        if not notes:
            report.append(f"unchanged {rel} (no kit entries found)")
            continue
        if not data:
            if not dry:
                backup_file(path, dry)
                path.unlink()
            report.append(f"removed   {rel} (nothing but kit entries was left)")
        else:
            backup_file(path, dry)
            write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", dry)
            report.append(f"cleaned   {rel} (the .bak the kit wrote is removed at the end)")
        report.extend(f"           - {n}" for n in notes)
    if all_added is None:
        report.append("note      kit.json predates permission tracking: permission rules the kit added were "
                      "left in settings (remove them by hand if unwanted)")

    # 3. ignore lines the kit appended
    recorded_ignore = kit_json.get("added_ignore")
    targets = {".gitignore": project / ".gitignore"}
    exclude = resolve_git_exclude(project)
    if exclude is not None:
        targets[".git/info/exclude"] = exclude
    for label, path in targets.items():
        removed = remove_kit_lines(path, None if recorded_ignore is None else recorded_ignore.get(label, []), dry)
        if removed:
            report.append(f"cleaned   {label} (-{len(removed)} kit line(s))")
            if (label in kit_json.get("created_files", []) and path.is_file()
                    and not path.read_bytes().decode("utf-8", errors="replace").strip()):
                if not dry:
                    path.unlink()
                report.append(f"removed   {label} (the kit created it and nothing else was left in it)")

    # 4. files that are never deleted automatically
    left = [p for p in ("CLAUDE.md", "CLAUDE.local.md") if (project / p).is_file()]
    left += [k for k in sorted(kit_json.get("rendered", {})) if k.startswith(".claude/rules/") and (project / k).is_file()]
    for rel in dict.fromkeys(left):
        report.append(f"left      {rel} (yours: review and delete by hand if you want it gone)")
    if (project / ".claude" / "logs").is_dir():
        report.append("left      .claude/logs/ (session logs)")

    # 4b. backups the kit wrote next to settings
    for name in ("settings.json.bak", "settings.local.json.bak"):
        bak = project / ".claude" / name
        if bak.is_file():
            if not dry:
                bak.unlink()
            report.append(f"removed   .claude/{name} (backup written by the kit)")

    # 5. kit.json last
    kit_file = project / ".claude" / "kit.json"
    if not dry:
        kit_file.unlink()
    report.append("removed   .claude/kit.json")
    _prune_empty_dirs(project / ".claude", dry)
    emit(report, dry)
