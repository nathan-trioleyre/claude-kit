"""`list` and `validate`: profile schema, permission and practices.md checks."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

from .core import (
    age_days,
    COMMAND_LABELS,
    _is_unsafe_dest_path,
    load_profile,
    MAX_PRACTICES_LINES,
    MAX_VERSION_PRACTICES_LINES,
    profile_dirs,
    PROFILES,
    STALE_DAYS,
    UNSAFE_BASH_COMMANDS,
    unsafe_permission,
)


def cmd_list(_args) -> None:
    out = []
    for folder in profile_dirs():
        p = load_profile(folder.name)
        age = age_days(p)
        out.append({
            "stack": p["stack"],
            "display_name": p.get("display_name", p["stack"]),
            "last_verified": p["last_verified"],
            "age_days": age,
            "stale": age > STALE_DAYS,
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


def _detect_entry_problem(entry, allow_all: bool) -> str | None:
    """Why a `detect` entry is invalid, or None. Entries: glob | {file, contains?} | {all: [glob|{file,contains?}]}."""
    if isinstance(entry, str):
        return None if entry else "empty pattern"
    if not isinstance(entry, dict):
        return "must be a glob string or an object"
    if "all" in entry:
        parts = entry["all"]
        if not allow_all or set(entry) != {"all"}:
            return "'all' cannot be nested or combined with other keys"
        if not isinstance(parts, list) or not parts:
            return "'all' must be a non-empty list"
        for part in parts:
            problem = _detect_entry_problem(part, allow_all=False)
            if problem:
                return problem
        return None
    unknown = set(entry) - {"file", "contains"}
    if unknown:
        return f"unknown key(s): {', '.join(sorted(unknown))}"
    if not isinstance(entry.get("file"), str) or not entry["file"]:
        return "'file' must be a non-empty glob"
    if "contains" in entry and (not isinstance(entry["contains"], str) or not entry["contains"]):
        return "'contains' must be a non-empty string"
    return None


def validate_profile_folder(folder: Path) -> list:
    """Validate profile.json and practices.md for one stack folder; return error strings."""
    errors = []
    pjson = folder / "profile.json"
    if not pjson.is_file():
        return [f"{folder.name}: missing profile.json"]
    try:
        data = json.loads(pjson.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{folder.name}: invalid JSON in profile.json ({exc})"]
    if not isinstance(data, dict):
        return [f"{folder.name}: profile.json must be a JSON object"]

    required = ("stack", "display_name", "detect", "commands", "permissions_allow",
                "format_rules", "sources", "last_verified")
    for key in required:
        if key not in data:
            errors.append(f"{folder.name}: missing key '{key}'")

    stack = data.get("stack")
    if isinstance(stack, str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", stack):
            errors.append(f"{folder.name}: stack '{stack}' must be lowercase alphanumeric/hyphens")
        if stack != folder.name:
            errors.append(f"{folder.name}: stack '{stack}' does not match folder name")

    detect = data.get("detect")
    if detect is not None:
        if not isinstance(detect, list) or not detect:
            errors.append(f"{folder.name}: 'detect' must be a non-empty list of entries")
        else:
            for entry in detect:
                problem = _detect_entry_problem(entry, allow_all=True)
                if problem:
                    errors.append(f"{folder.name}: 'detect' entry {entry!r}: {problem}")

    commands = data.get("commands")
    if commands is not None:
        if not isinstance(commands, dict) or "verify" not in commands:
            errors.append(f"{folder.name}: 'commands' must be an object containing 'verify'")
        elif any(v is not None and not isinstance(v, str) for v in commands.values()):
            errors.append(f"{folder.name}: command values must be strings or null")

    perms = data.get("permissions_allow")
    if perms is not None:
        if not isinstance(perms, list) or not all(isinstance(r, str) for r in perms):
            errors.append(f"{folder.name}: 'permissions_allow' must be a list of strings")
        else:
            for rule in perms:
                reason = unsafe_permission(rule, _runners(data.get("tooling")))
                if reason:
                    errors.append(f"{folder.name}: {reason}")

    fmt_rules = data.get("format_rules")
    if fmt_rules is not None:
        if not isinstance(fmt_rules, list):
            errors.append(f"{folder.name}: 'format_rules' must be a list")
        else:
            for idx, rule in enumerate(fmt_rules):
                errors.extend(_validate_tool_rule(f"{folder.name}: format_rules[{idx}]", rule))

    sources = data.get("sources")
    if sources is not None:
        if not isinstance(sources, list) or not sources or not all(isinstance(s, str) and s.startswith(("http://", "https://")) for s in sources):
            errors.append(f"{folder.name}: 'sources' must be a non-empty list of URLs")

    last_verified = data.get("last_verified")
    if isinstance(last_verified, str):
        try:
            date.fromisoformat(last_verified)
        except ValueError:
            errors.append(f"{folder.name}: invalid ISO date '{last_verified}' in last_verified")

    paths = data.get("paths")
    if paths is not None and (not isinstance(paths, list) or not all(isinstance(x, str) and x for x in paths)):
        errors.append(f"{folder.name}: optional 'paths' must be a list of non-empty glob strings")

    supersedes = data.get("supersedes")
    if supersedes is not None and (not isinstance(supersedes, list) or not all(isinstance(x, str) and x for x in supersedes)):
        errors.append(f"{folder.name}: optional 'supersedes' must be a list of non-empty stack names")

    if "tooling" in data:
        errors.extend(validate_tooling(folder.name, data["tooling"], folder))

    if "verify_steps" in data:
        declared_concerns = {
            item.get("concern")
            for item in (data.get("tooling") or [])
            if isinstance(item, dict) and isinstance(item.get("concern"), str)
        }
        vsteps = data["verify_steps"]
        if not isinstance(vsteps, list) or not vsteps:
            errors.append(f"{folder.name}: 'verify_steps' must be a non-empty list")
        else:
            for idx, step in enumerate(vsteps):
                if not isinstance(step, dict) or not isinstance(step.get("cmd"), str) or not step["cmd"].strip():
                    errors.append(f"{folder.name}: verify_steps[{idx}] needs a non-empty 'cmd' string")
                    continue
                concern = step.get("concern")
                if concern is not None and (not isinstance(concern, str) or concern not in declared_concerns):
                    errors.append(f"{folder.name}: verify_steps[{idx}].concern '{concern}' is not declared in tooling")
                cmd_key = step.get("command_key")
                if cmd_key is not None and (not isinstance(cmd_key, str) or cmd_key not in COMMAND_LABELS):
                    errors.append(f"{folder.name}: verify_steps[{idx}].command_key '{cmd_key}' is not a valid command key")

    practices_file = folder / "practices.md"
    if not practices_file.is_file():
        errors.append(f"{folder.name}: missing practices.md")
    else:
        non_empty_lines = [line for line in practices_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not non_empty_lines:
            errors.append(f"{folder.name}: practices.md is empty")
        elif len(non_empty_lines) > MAX_PRACTICES_LINES:
            errors.append(f"{folder.name}: practices.md has {len(non_empty_lines)} lines (max {MAX_PRACTICES_LINES})")

    versions_dir = folder / "versions"
    if versions_dir.is_dir():
        for vf in sorted(versions_dir.glob("*.md")):
            vlines = [line for line in vf.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not vlines:
                errors.append(f"{folder.name}: versions/{vf.name} is empty")
            elif len(vlines) > MAX_VERSION_PRACTICES_LINES:
                errors.append(f"{folder.name}: versions/{vf.name} has {len(vlines)} lines (max {MAX_VERSION_PRACTICES_LINES})")

    return errors


def _marker_errors(prefix: str, markers) -> list:
    if not isinstance(markers, list):
        return [f"{prefix}: 'markers' must be a list"]
    errors = []
    for i, m in enumerate(markers):
        if not isinstance(m, dict) or not isinstance(m.get("file"), str) or not m["file"]:
            errors.append(f"{prefix}: markers[{i}] needs a 'file' glob")
        elif "contains" in m and not (isinstance(m["contains"], str) and m["contains"]):
            errors.append(f"{prefix}: markers[{i}].contains must be a non-empty string")
    return errors


def _runners(tooling) -> set:
    """Every runner prefix declared by the package-manager concern (kit and alternatives)."""
    found = set()
    for item in tooling if isinstance(tooling, list) else []:
        if not isinstance(item, dict) or item.get("concern") != "package-manager":
            continue
        entries = [item.get("kit")] + (item.get("alternatives") if isinstance(item.get("alternatives"), list) else [])
        found.update(e["runner"] for e in entries if isinstance(e, dict) and isinstance(e.get("runner"), str) and e["runner"])
    return found


def _runner_errors(prefix: str, entry: dict) -> list:
    if "runner" in entry and not (isinstance(entry["runner"], str) and entry["runner"].strip()):
        return [f"{prefix}.runner must be a non-empty string (e.g. 'uv run', 'npx')"]
    return []


def _perm_errors(prefix: str, rules, runners=()) -> list:
    if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
        return [f"{prefix}: permissions must be a list of strings"]
    return [f"{prefix}: {reason}" for reason in (unsafe_permission(r, runners) for r in rules) if reason]


def _validate_tool_rule(prefix: str, rule, *, check_exec: bool = False) -> list:
    if not isinstance(rule, dict):
        return [f"{prefix} must be an object"]
    errors = []
    exts = rule.get("extensions")
    fnames = rule.get("filenames")
    cmd = rule.get("command")
    if exts is None and fnames is None:
        errors.append(f"{prefix} must define 'extensions' or 'filenames'")
    if exts is not None and (not isinstance(exts, list) or not exts or not all(isinstance(e, str) and e.startswith(".") for e in exts)):
        errors.append(f"{prefix}.extensions must list '.ext' strings")
    if fnames is not None and (not isinstance(fnames, list) or not fnames or not all(isinstance(f, str) and f for f in fnames)):
        errors.append(f"{prefix}.filenames must list non-empty filename globs")
    if not isinstance(cmd, list) or not cmd or not all(isinstance(c, str) and c for c in cmd) or "{file}" not in cmd:
        errors.append(f"{prefix}.command must be a non-empty list of strings including '{{file}}'")
    elif check_exec:
        exe = Path(cmd[0].replace("\\", "/")).name.lower()
        if exe.endswith(".exe"):
            exe = exe[:-4]
        if exe in UNSAFE_BASH_COMMANDS:
            errors.append(f"{prefix}.command uses unsafe executable '{exe}'")
    return errors


def _validate_preset_files(prefix: str, folder: Path | None, items) -> list:
    if not isinstance(items, list):
        return [f"{prefix}.preset_files must be a list"]
    errors = []
    folder_resolved = folder.resolve() if folder else None
    for i, item in enumerate(items):
        ipre = f"{prefix}.preset_files[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{ipre} must be an object")
            continue
        src = item.get("src")
        dest = item.get("dest")
        mode = item.get("mode", "create")
        if mode not in ("create", "snippet"):
            errors.append(f"{ipre}.mode must be 'create' or 'snippet'")
        if not isinstance(src, str) or not src:
            errors.append(f"{ipre}.src must be a non-empty relative path")
        else:
            src_norm = src.replace("\\", "/")
            if (Path(src_norm).is_absolute() or src_norm.startswith("/")
                    or re.match(r"^[a-zA-Z]:", src_norm) or ".." in Path(src_norm).parts):
                errors.append(f"{ipre}.src '{src}' must stay inside the profile folder")
            elif folder_resolved is not None:
                resolved = (folder_resolved / src_norm).resolve()
                if not resolved.is_relative_to(folder_resolved) or not resolved.is_file():
                    errors.append(f"{ipre}.src '{src}' does not exist inside {folder.name}/")
        if not isinstance(dest, str) or _is_unsafe_dest_path(dest):
            errors.append(f"{ipre}.dest '{dest}' is not a safe relative project path")
    return errors


def _validate_install_packages(prefix: str, pkgs) -> list:
    if isinstance(pkgs, list):
        if not all(isinstance(p, str) and p for p in pkgs):
            return [f"{prefix}.install_packages must list non-empty strings"]
        return []
    if isinstance(pkgs, dict):
        for pm, items in pkgs.items():
            if not isinstance(pm, str) or not pm or not isinstance(items, list) or not all(isinstance(p, str) and p for p in items):
                return [f"{prefix}.install_packages must map package managers to lists of package names"]
        return []
    return [f"{prefix}.install_packages must be a list or mapping"]


def _validate_scripts(prefix: str, scripts) -> list:
    if not isinstance(scripts, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in scripts.items()):
        return [f"{prefix}.scripts must map script names to command strings"]
    return []


def validate_tooling(name: str, tooling, folder: Path | None = None) -> list:
    """Validate the optional 'tooling' section (conflict detection and preset metadata)."""
    if not isinstance(tooling, list):
        return [f"{name}: 'tooling' must be a list"]
    errors, seen = [], set()
    runners = _runners(tooling)
    for idx, item in enumerate(tooling):
        pre = f"{name}: tooling[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{pre} must be an object")
            continue
        concern = item.get("concern")
        if not isinstance(concern, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", concern):
            errors.append(f"{pre}.concern must be a lowercase slug")
        elif concern in seen:
            errors.append(f"{pre}.concern '{concern}' is duplicated")
        else:
            seen.add(concern)
        kit = item.get("kit")
        has_preset = False
        if not isinstance(kit, dict) or not isinstance(kit.get("name"), str) or not kit["name"]:
            errors.append(f"{pre}.kit must be an object with a 'name'")
        else:
            errors.extend(_marker_errors(f"{pre}.kit", kit.get("markers", [])))
            cmds = kit.get("commands", [])
            if not isinstance(cmds, list) or any(c not in COMMAND_LABELS for c in cmds):
                errors.append(f"{pre}.kit.commands must list keys among {', '.join(COMMAND_LABELS)}")
            if not isinstance(kit.get("format_rules", False), bool):
                errors.append(f"{pre}.kit.format_rules must be a boolean")
            if not isinstance(kit.get("only_when_installed", False), bool):
                errors.append(f"{pre}.kit.only_when_installed must be a boolean")
            errors.extend(_runner_errors(f"{pre}.kit", kit))
            errors.extend(_perm_errors(f"{pre}.kit", kit.get("permissions", []), runners))
            terms = kit.get("practice_terms", [])
            if not isinstance(terms, list) or not all(isinstance(t, str) and t for t in terms):
                errors.append(f"{pre}.kit.practice_terms must be a list of strings")
            if "preset_files" in kit:
                errors.extend(_validate_preset_files(f"{pre}.kit", folder, kit["preset_files"]))
            if "install_packages" in kit:
                errors.extend(_validate_install_packages(f"{pre}.kit", kit["install_packages"]))
            if "scripts" in kit:
                errors.extend(_validate_scripts(f"{pre}.kit", kit["scripts"]))
            if "post_edit_check" in kit:
                errors.extend(_validate_tool_rule(f"{pre}.kit.post_edit_check", kit["post_edit_check"], check_exec=True))
            has_preset = bool(kit.get("preset_files") or kit.get("install_packages") or kit.get("scripts"))
        alts = item.get("alternatives")
        if alts is None and has_preset:
            alts = []
        elif not isinstance(alts, list) or not alts:
            errors.append(f"{pre}.alternatives must be a non-empty list")
            continue
        for j, alt in enumerate(alts):
            apre = f"{pre}.alternatives[{j}]"
            if not isinstance(alt, dict) or not isinstance(alt.get("name"), str) or not alt["name"]:
                errors.append(f"{apre} must be an object with a 'name'")
                continue
            if not alt.get("markers") and not alt.get("hooks"):
                errors.append(f"{apre} needs 'markers' or 'hooks' to be detectable")
            errors.extend(_marker_errors(apre, alt.get("markers", [])))
            hooks = alt.get("hooks", [])
            if not isinstance(hooks, list) or not all(isinstance(h, str) and h for h in hooks):
                errors.append(f"{apre}.hooks must be a list of strings")
            acmds = alt.get("commands", {})
            if not isinstance(acmds, dict) or any(k not in COMMAND_LABELS or not isinstance(v, str) for k, v in acmds.items()):
                errors.append(f"{apre}.commands must map command keys to strings")
            errors.extend(_runner_errors(apre, alt))
            errors.extend(_perm_errors(apre, alt.get("permissions_allow", []), runners))
            rule = alt.get("format_rule")
            if rule is not None:
                errors.extend(_validate_tool_rule(f"{apre}.format_rule", rule))
            if "post_edit_check" in alt:
                errors.extend(_validate_tool_rule(f"{apre}.post_edit_check", alt["post_edit_check"], check_exec=True))
    return errors


def cmd_validate(args) -> None:
    if args.profiles:
        folders = [PROFILES / name for name in args.profiles]
    else:
        folders = [p for p in sorted(PROFILES.iterdir()) if p.is_dir() and not p.name.startswith("_")] if PROFILES.is_dir() else []

    if not folders:
        print("No profiles to validate.")
        return

    all_errors = []
    for folder in folders:
        if not folder.is_dir():
            all_errors.append(f"{folder.name}: profile directory not found")
        else:
            all_errors.extend(validate_profile_folder(folder))

    if all_errors:
        for err in all_errors:
            print(f"ERROR: {err}", file=sys.stderr)
        raise SystemExit(1)

    print(f"OK: validated {len(folders)} profile(s).")
