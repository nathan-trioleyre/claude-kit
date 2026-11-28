"""`doctor`: report drift between a project and the current kit."""

from __future__ import annotations

from pathlib import Path

from .core import (
    age_days,
    BASE,
    HARNESS_RECURRING_THRESHOLD,
    hook_version,
    IGNORED_DIRS,
    KIT_VERSION,
    load_profile,
    MAX_CLAUDE_MD_LINES,
    PLACEHOLDER,
    PROFILES,
    read_text_lossy,
    sha256_norm,
    STALE_DAYS,
)
from .detect import detect_matched
from .preflight import preflight
from .settings import build_wanted_settings, merge_settings, read_settings
from .stats import _read_harness_stats, _read_session_stats
from .tooling import analyze_tooling, effective_profile


def cmd_doctor(args) -> None:
    project = Path(args.project).resolve()
    kit_json = preflight(project)
    issues, oks = [], []
    if not kit_json:
        print("ISSUE: no .claude/kit.json: project not configured. Run /claude-devkit.")
        raise SystemExit(1)

    if kit_json.get("kit_version") != KIT_VERSION:
        issues.append(f"project configured with kit {kit_json.get('kit_version', '?')}, current kit is {KIT_VERSION}: run sync")
    else:
        oks.append(f"kit version {KIT_VERSION}")

    managed = kit_json.get("managed", {})
    for src in sorted((BASE / "hooks").iterdir()):
        if not src.is_file() or src.name.startswith("."):
            continue
        label = f".claude/hooks/{src.name}"
        dest = project / label
        if not dest.is_file():
            issues.append(f"{label} is missing")
            continue
        src_text, dest_bytes = src.read_text(encoding="utf-8"), dest.read_bytes()
        if sha256_norm(dest_bytes) == sha256_norm(src.read_bytes()):
            oks.append(f"{label} up to date (v{hook_version(src_text)})")
        elif managed.get(label) == sha256_norm(dest_bytes):
            issues.append(f"{label} outdated (v{hook_version(dest_bytes.decode('utf-8', 'ignore'))} < v{hook_version(src_text)}): run sync")
        else:
            issues.append(f"{label} modified locally or predates hash tracking: run sync --force-hooks to reset")

    warns = []
    profile_names = [n for n in kit_json.get("profiles", {}) if (PROFILES / n / "profile.json").is_file()]
    raw_profiles = [load_profile(n) for n in profile_names]
    analysis = analyze_tooling(project, raw_profiles, kit_json.get("decisions", {}))
    effective = [effective_profile(p, analysis) for p in raw_profiles]
    for a in analysis:
        label = f"{a['stack']}/{a['concern']}"
        names = ", ".join(e["name"] for e in a["existing"])
        if a["status"] == "pending":
            issues.append(f"tooling conflict {label}: project uses {names}, kit prefers {a['kit']['name']}, no decision recorded: "
                          "run /claude-devkit (or `apply.py decide`)")
        elif a["status"] == "migration_pending":
            issues.append(f"{label}: kit adopted but {names} is still configured ("
                          + "; ".join(ev for e in a["existing"] for ev in e["evidence"]) + "): finish the migration")
        elif a["status"] == "missing":
            state = "adopted but not installed yet" if a["effective"] != "skip" else "withheld from commands and verify"
            warns.append(f"missing tooling {label}: no {a['kit']['name']} config detected, {state} "
                         f"(install the preset then `apply.py decide --profile {a['stack']} --concern {a['concern']} --choice adopt_kit`, or `--choice skip`)")
        elif a["status"] == "resolved":
            detail = names or "preset"
            oks.append(f"tooling {label}: {a['effective']} ({detail})")

    is_local = bool(kit_json.get("local", False))
    settings_rel = ".claude/settings.local.json" if is_local else ".claude/settings.json"
    settings_path = project / settings_rel
    if settings_path.is_file():
        _, changes = merge_settings(read_settings(settings_path, settings_rel),
                                    build_wanted_settings(effective, not args.no_org))
        if changes:
            issues.append(f"{settings_rel} is missing {len(changes)} kit entries: run sync")
        else:
            oks.append(f"{settings_rel} has every kit permission and hook")
    else:
        issues.append(f"{settings_rel} is missing")

    for name, info in kit_json.get("profiles", {}).items():
        if not (PROFILES / name / "profile.json").is_file():
            issues.append(f"profile '{name}' no longer exists in the kit")
            continue
        p = load_profile(name)
        if age_days(p) > STALE_DAYS:
            issues.append(f"profile '{name}' is stale/unverified ({age_days(p)}d): /claude-devkit-refresh {name}")
        if p["last_verified"] != info.get("last_verified"):
            issues.append(f"profile '{name}' was refreshed in the kit since this project was set up: re-run /claude-devkit")

    detected = detect_matched(project)
    for name in detected:
        if name not in kit_json.get("profiles", {}):
            issues.append(f"stack '{name}' detected but not configured: re-run /claude-devkit")

    md_rel = "CLAUDE.local.md" if is_local else "CLAUDE.md"
    claude_md = project / md_rel
    if claude_md.is_file():
        claude_text = read_text_lossy(claude_md)
        left = claude_text.count(PLACEHOLDER)
        (issues if left else oks).append(f"{md_rel} has {left} section(s) still marked '{PLACEHOLDER}'" if left else f"{md_rel} fully filled")
        claude_lines = len(claude_text.splitlines())
        if claude_lines > MAX_CLAUDE_MD_LINES:
            issues.append(f"{md_rel} has {claude_lines} lines (recommended <= {MAX_CLAUDE_MD_LINES}): move stack details to .claude/rules/*.md or @imports")
        else:
            oks.append(f"{md_rel} within budget ({claude_lines} lines)")
    else:
        issues.append(f"{md_rel} is missing")

    harness_stats = _read_harness_stats(project)
    if harness_stats["total_blocks"]:
        for rec in harness_stats["recurring"]:
            issues.append(f"harness.log shows {rec['count']}x blocks for '{rec['key']}': add an explicit rule + alternative in CLAUDE.md via /claude-devkit-learn")
        if not harness_stats["recurring"]:
            oks.append(f"harness.log: {harness_stats['total_blocks']} logged block(s), no recurring pattern (>={HARNESS_RECURRING_THRESHOLD})")

    sess_stats = _read_session_stats(project)
    if sess_stats["count"]:
        oks.append(f"sessions.jsonl: {sess_stats['count']} session(s) tracked ({sess_stats['input_tokens']} input / {sess_stats['output_tokens']} output tokens)")
    leftovers = [p.relative_to(project).as_posix() for p in project.rglob("*.proposed")
                 if not any(part in IGNORED_DIRS for part in p.relative_to(project).parts)]
    for rel in leftovers:
        issues.append(f"{rel} is waiting to be merged or deleted")

    print("\n".join([f"ok     {o}" for o in oks] + [f"WARN   {w}" for w in warns] + [f"ISSUE  {i}" for i in issues]))
    if issues:
        raise SystemExit(1)
