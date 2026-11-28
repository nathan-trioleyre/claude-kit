"""`apply`, `sync`, `doctor`, `audit`, `decide`: write and check a project's kit-managed config."""

import json
import re
import shutil
from datetime import date
from pathlib import Path

from .core import (
    age_days,
    BASE,
    emit,
    GENERATED_FOOTER_PREFIXES,
    HARNESS_RECURRING_THRESHOLD,
    hook_version,
    IGNORED_DIRS,
    KIT_VERSION,
    load_context,
    load_kit_json,
    load_profile,
    MAX_CLAUDE_MD_LINES,
    MAX_MEMORY_MD_LINES,
    MEMORY_STALE_DAYS,
    ORG,
    PLACEHOLDER,
    PROFILES,
    sha256_bytes,
    split_sections,
    STALE_DAYS,
    write_non_destructive,
    write_text,
)
from .detect import detect_matched
from .settings import apply_settings, build_wanted_settings, merge_settings, read_org_text
from .tooling import (
    analyze_tooling,
    effective_profile,
    foreign_hooks,
    normalize_decision,
    record_decisions,
    tooling_report,
)
from .render import (
    combined_practices,
    render_commands,
    render_local_delta,
    render_practices,
    render_rule_file,
    resolve_rule_paths,
)
from .codemap import sync_codemap
from .stats import _read_harness_stats, _read_session_stats


def sync_file(src: Path, dest: Path, label: str, managed: dict, dry: bool, report: list, force: bool) -> None:
    """Copy a kit file into the project.

    - missing: created
    - identical: unchanged
    - differs but unmodified since the kit installed it (hash recorded in kit.json): upgraded
    - differs and modified by the user (or installed before hashes were recorded): skipped
      unless `force` (--force-hooks)
    """
    src_bytes = src.read_bytes()
    src_hash = sha256_bytes(src_bytes)

    def put(verb: str) -> None:
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            if src.suffix == ".sh":
                dest.chmod(dest.stat().st_mode | 0o111)
        managed[label] = src_hash
        report.append(f"{verb} {label}")

    if not dest.exists():
        put("created  ")
        return
    dest_hash = sha256_bytes(dest.read_bytes())
    if dest_hash == src_hash:
        managed[label] = src_hash
        report.append(f"unchanged {label}")
    elif force or managed.get(label) == dest_hash:
        put("upgraded " if not force else "forced   ")
    else:
        report.append(f"skipped   {label} differs from the kit and was modified locally (use --force-hooks to overwrite)")


def sync_extras(project: Path, managed: dict, dry: bool, report: list, force: bool, use_org: bool,
                local: bool = False) -> bool:
    """Hooks, then optional agents/commands/rules/skills from base/ and org/ (non-destructive).

    Returns True if .mcp.json was created by org/mcp.json during this run.
    """
    mcp_created = False
    for src in sorted((BASE / "hooks").iterdir()):
        if src.is_file() and not src.name.startswith("."):
            sync_file(src, project / ".claude" / "hooks" / src.name, f".claude/hooks/{src.name}",
                      managed, dry, report, force)

    roots = [BASE] + ([ORG] if use_org else [])
    for root in roots:
        for sub in ("agents", "commands", "rules"):
            folder = root / sub
            if not folder.is_dir():
                continue
            for src in sorted(folder.glob("*.md")):
                sync_file(src, project / ".claude" / sub / src.name, f".claude/{sub}/{src.name}",
                          managed, dry, report, False)

        skills_dir = root / "skills"
        if skills_dir.is_dir():
            for skill_folder in sorted(p for p in skills_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()):
                for src in sorted(p for p in skill_folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
                    rel = src.relative_to(skill_folder).as_posix()
                    label = f".claude/skills/{skill_folder.name}/{rel}"
                    sync_file(src, project / label, label, managed, dry, report, False)

    mcp_src = ORG / "mcp.json" if use_org else None
    if mcp_src and mcp_src.is_file():
        wanted = json.loads(mcp_src.read_text(encoding="utf-8")).get("mcpServers", {})
        target = project / ".mcp.json"
        if local and target.exists():
            report.append("skipped   .mcp.json preserved (local mode)")
            return False
        existed = target.exists()
        existing = {}
        if existed:
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                report.append("skipped   .mcp.json is not valid JSON (left untouched)")
                return False
        servers = existing.setdefault("mcpServers", {})
        added = [name for name in wanted if name not in servers]
        for name in added:
            servers[name] = wanted[name]
        if added:
            write_text(target, json.dumps(existing, indent=2, ensure_ascii=False) + "\n", dry)
            report.append(f"merged    .mcp.json (+{', '.join(added)})")
            mcp_created = not existed
        else:
            report.append("unchanged .mcp.json")
    return mcp_created


def update_git_exclude(project: Path, paths: list, dry: bool, report: list) -> None:
    """Add kit-managed local paths to .git/info/exclude so team git status stays clean."""
    git_dir = project / ".git"
    if not git_dir.is_dir():
        return
    exclude = git_dir / "info" / "exclude"
    current = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    current_set = {line.strip() for line in current}
    missing = [p for p in dict.fromkeys(paths) if p not in current_set]
    if missing:
        text = (exclude.read_text(encoding="utf-8").rstrip("\n") + "\n\n" if current else "")
        write_text(exclude, text + "# claude-kit (local)\n" + "\n".join(missing) + "\n", dry)
        report.append(f"updated   .git/info/exclude (+{len(missing)} lines)")


def update_gitignore(project: Path, dry: bool, report: list) -> None:
    gitignore = project / ".gitignore"
    wanted_lines = [".claude/settings.local.json", ".claude/logs/", "CLAUDE.local.md",
                    "CLAUDE.md.proposed", ".claude/rules/*.proposed"]
    current = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    current_set = {line.strip() for line in current}
    missing = [line for line in wanted_lines if line not in current_set]
    if missing:
        text = (gitignore.read_text(encoding="utf-8").rstrip("\n") + "\n\n" if current else "")
        write_text(gitignore, text + "# Claude Code (local files)\n" + "\n".join(missing) + "\n", dry)
        report.append(f"updated   .gitignore (+{len(missing)} lines)")


def resolve_verify_command(profiles: list, effective: dict, overrides: dict, previous: dict, ctx: dict,
                           *, full: bool = True) -> str:
    if ctx.get("verify_command"):
        return str(ctx["verify_command"]).strip()
    if not full and previous.get("custom_verify") and previous.get("verify_command") and not overrides:
        return str(previous["verify_command"]).strip()
    cmds = []
    for name in list(dict.fromkeys([p["stack"] for p in profiles] + list(previous.get("profiles", {})))):
        ov = overrides.get(name, {})
        cmd = ov.get("verify") if "verify" in ov else (effective.get(name, {}).get("commands", {}).get("verify"))
        if cmd:
            cmds.append(cmd)
    if cmds:
        return " && ".join(dict.fromkeys(cmds))
    return ""


def write_kit_json(project: Path, profiles: list, previous: dict, managed: dict, rendered: dict,
                   decisions: dict, effective: dict, dry: bool, report: list, ctx: dict | None = None,
                   local: bool = False, *, full: bool = True) -> None:
    ctx = ctx or {}
    known = dict(previous.get("profiles", {}))
    versions = ctx.get("stack_versions") or {}
    for p in profiles:
        entry = {"last_verified": p["last_verified"]}
        ver = versions.get(p["stack"]) or (known.get(p["stack"], {}) or {}).get("version")
        if ver:
            entry["version"] = str(ver).strip().lstrip("vV")
        known[p["stack"]] = entry
    format_rules = []
    lint_rules = []
    for name in list(known):
        if name in effective:  # profiles deleted from the kit in the meantime are skipped
            format_rules.extend(effective[name].get("format_rules", []))
            lint_rules.extend(effective[name].get("lint_rules", []))
    overrides = ctx.get("commands_override", {})
    custom_verify = bool(ctx.get("verify_command") or any("verify" in ov for ov in overrides.values())) or (
        not full and bool(previous.get("custom_verify"))
    )
    verify_cmd = resolve_verify_command(profiles, effective, overrides, previous, ctx, full=full)
    if "stop_verify" in ctx:
        stop_verify = bool(ctx["stop_verify"])
    elif "stop_verify" in previous:
        stop_verify = bool(previous["stop_verify"])
    else:
        stop_verify = bool(verify_cmd)
    kit_json = {
        "generated_by": "claude-kit",
        "kit_version": KIT_VERSION,
        "date": date.today().isoformat(),
        "local": local,
        "profiles": known,
        "stop_verify": stop_verify,
        "custom_verify": custom_verify,
        "verify_command": verify_cmd,
        "format_rules": format_rules,
        "lint_rules": lint_rules,
        "decisions": decisions,
        "managed": managed,
        "rendered": rendered,
    }
    write_text(project / ".claude" / "kit.json", json.dumps(kit_json, indent=2, ensure_ascii=False) + "\n", dry)
    report.append("written   .claude/kit.json")


def run(project: Path, profile_names: list, ctx: dict, dry: bool, *, full: bool,
        force_hooks: bool = False, use_org: bool = True, local: bool | None = None) -> list:
    report = []
    previous = load_kit_json(project)
    is_local = bool(previous.get("local", False)) if local is None else local
    managed = dict(previous.get("managed", {}))
    rendered_state = dict(previous.get("rendered", {}))

    # Every profile this project knows (previous runs + this one), adjusted by tooling decisions.
    known_names = list(dict.fromkeys(
        list(profile_names) + [n for n in previous.get("profiles", {}) if (PROFILES / n / "profile.json").is_file()]))
    raw = {name: load_profile(name) for name in known_names}
    decisions = json.loads(json.dumps(previous.get("decisions", {})))
    incoming = {s: {c: normalize_decision(v) for c, v in (cs or {}).items()}
                for s, cs in ctx.get("decisions", {}).items()}
    for stack, concerns in incoming.items():
        decisions.setdefault(stack, {}).update(concerns)
    analysis = analyze_tooling(project, list(raw.values()), decisions)
    record_decisions(decisions, incoming, analysis, report)
    effective = {name: effective_profile(p, analysis) for name, p in raw.items()}
    report.extend(tooling_report(analysis))

    profiles = [effective[name] for name in profile_names]
    for p in profiles:
        if age_days(p) > STALE_DAYS:
            report.append(f"! profile '{p['stack']}' is stale or unverified ({age_days(p)}d): consider /claude-kit-refresh {p['stack']}")

    rule_labels = []
    mem_created = False
    effective_versions = {
        name: info["version"]
        for name, info in previous.get("profiles", {}).items()
        if isinstance(info, dict) and info.get("version")
    }
    effective_versions.update({k: v for k, v in (ctx.get("stack_versions") or {}).items() if v})
    if full:
        # 1. CLAUDE.md or CLAUDE.local.md (never overwritten)
        template = (BASE / "CLAUDE.md.template").read_text(encoding="utf-8")
        org_rules = read_org_text("rules.md") if use_org else ""
        render_ctx = {**ctx, "stack_versions": effective_versions}
        stack_lines = []
        for p in profiles:
            ver = effective_versions.get(p["stack"])
            ver_suffix = f" (v{str(ver).strip().lstrip('vV')})" if ver else ""
            stack_lines.append(f"- {p.get('display_name', p['stack'])}{ver_suffix}")
        values = {
            "PROJECT_NAME": ctx.get("name") or project.name,
            "DESCRIPTION": ctx.get("description") or PLACEHOLDER,
            "STACK": "\n".join(stack_lines) or PLACEHOLDER,
            "COMMANDS": render_commands(profiles, ctx.get("commands_override", {})),
            "ARCHITECTURE": ctx.get("architecture") or PLACEHOLDER,
            "PRACTICES": render_practices(profiles, render_ctx),
            "GOTCHAS": ctx.get("gotchas") or PLACEHOLDER,
            "ORG_RULES": ("\n" + org_rules) if org_rules else "",
            "DATE": date.today().isoformat(),
            "PROFILES": ", ".join(p["stack"] for p in profiles) or "none",
        }
        if is_local and (project / "CLAUDE.md").is_file():
            rendered = render_local_delta(values, bool(ctx.get("gotchas")), template)
        else:
            rendered = template
            for key, value in values.items():
                rendered = rendered.replace("{{" + key + "}}", value)
        md_label = "CLAUDE.local.md" if is_local else "CLAUDE.md"
        write_non_destructive(project / md_label, md_label, rendered, dry, report,
                              GENERATED_FOOTER_PREFIXES, rendered_state)

        # 2. Modular .claude/rules/<stack>.md (optional, never overwritten)
        for p in profiles:
            rule_paths = resolve_rule_paths(p, ctx)
            ver = effective_versions.get(p["stack"])
            if rule_paths and combined_practices(p, ver):
                label = f".claude/rules/{p['stack']}.md"
                rule_labels.append(label)
                write_non_destructive(project / label, label, render_rule_file(p, rule_paths, ver),
                                      dry, report, state=rendered_state)

        # 2b. Inter-session state memory skeleton (never overwritten once created)
        mem_template = BASE / "MEMORY.md.template"
        mem_path = project / "MEMORY.md"
        if mem_template.is_file():
            if not mem_path.exists():
                mem_created = True
                write_text(mem_path, mem_template.read_text(encoding="utf-8"), dry)
                report.append("created   MEMORY.md")
            else:
                report.append("unchanged MEMORY.md (kept existing)")

    # 3. settings.json or settings.local.json (additive merge + legacy kit hook upgrade)
    apply_settings(project, profiles, dry, report, use_org, local=is_local)

    # 4. hooks, agents, commands, rules, skills, MCP servers
    mcp_created = sync_extras(project, managed, dry, report, force_hooks, use_org, local=is_local)
    sync_codemap(project, managed, dry, report)

    # 5. kit.json (metadata, formatting rules, hashes)
    write_kit_json(project, profiles, previous, managed, rendered_state, decisions, effective, dry, report, ctx,
                   local=is_local, full=full)

    # 6. .gitignore (shared mode) or .git/info/exclude (local mode)
    if is_local:
        exclude_paths = [
            "CLAUDE.local.md", "CLAUDE.local.md.proposed",
            ".claude/settings.local.json", ".claude/kit.json", ".claude/logs/", ".claude/rules/*.proposed",
            *sorted(managed), *rule_labels,
        ]
        if mem_created:
            exclude_paths.append("MEMORY.md")
        if mcp_created:
            exclude_paths.append(".mcp.json")
        update_git_exclude(project, exclude_paths, dry, report)
    else:
        update_gitignore(project, dry, report)
    return report


def cmd_apply(args) -> None:
    project = Path(args.project).resolve()
    ctx = load_context(args.context)
    emit(run(project, args.profiles, ctx, args.dry_run, full=True,
             force_hooks=args.force_hooks, use_org=not args.no_org,
             local=True if args.local else None), args.dry_run)


def cmd_sync(args) -> None:
    project = Path(args.project).resolve()
    previous = load_kit_json(project)
    if not previous:
        raise SystemExit("No .claude/kit.json: this project was never configured. Run /claude-kit (apply) first.")
    names = args.profiles or [n for n in previous.get("profiles", {}) if (PROFILES / n / "profile.json").is_file()]
    emit(run(project, names, {}, args.dry_run, full=False,
             force_hooks=args.force_hooks, use_org=not args.no_org,
             local=True if args.local else None), args.dry_run)


def cmd_doctor(args) -> None:
    project = Path(args.project).resolve()
    kit_json = load_kit_json(project)
    issues, oks = [], []
    if not kit_json:
        print("ISSUE: no .claude/kit.json: project not configured. Run /claude-kit.")
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
        if sha256_bytes(dest_bytes) == sha256_bytes(src.read_bytes()):
            oks.append(f"{label} up to date (v{hook_version(src_text)})")
        elif managed.get(label) == sha256_bytes(dest_bytes):
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
                          "run /claude-kit (or `apply.py decide`)")
        elif a["status"] == "migration_pending":
            issues.append(f"{label}: kit adopted but {names} is still configured ("
                          + "; ".join(ev for e in a["existing"] for ev in e["evidence"]) + "): finish the migration")
        elif a["status"] == "missing":
            warns.append(f"missing tooling {label}: no {a['kit']['name']} config detected "
                         f"(install preset or `apply.py decide --profile {a['stack']} --concern {a['concern']} --choice skip`)")
        elif a["status"] == "resolved":
            detail = names or "preset"
            oks.append(f"tooling {label}: {a['effective']} ({detail})")

    is_local = bool(kit_json.get("local", False))
    settings_rel = ".claude/settings.local.json" if is_local else ".claude/settings.json"
    settings_path = project / settings_rel
    if settings_path.is_file():
        try:
            _, changes = merge_settings(json.loads(settings_path.read_text(encoding="utf-8")),
                                        build_wanted_settings(effective, not args.no_org))
            if changes:
                issues.append(f"{settings_rel} is missing {len(changes)} kit entries: run sync")
            else:
                oks.append(f"{settings_rel} has every kit permission and hook")
        except json.JSONDecodeError:
            issues.append(f"{settings_rel} is not valid JSON")
    else:
        issues.append(f"{settings_rel} is missing")

    for name, info in kit_json.get("profiles", {}).items():
        if not (PROFILES / name / "profile.json").is_file():
            issues.append(f"profile '{name}' no longer exists in the kit")
            continue
        p = load_profile(name)
        if age_days(p) > STALE_DAYS:
            issues.append(f"profile '{name}' is stale/unverified ({age_days(p)}d): /claude-kit-refresh {name}")
        if p["last_verified"] != info.get("last_verified"):
            issues.append(f"profile '{name}' was refreshed in the kit since this project was set up: re-run /claude-kit")

    detected = detect_matched(project)
    for name in detected:
        if name not in kit_json.get("profiles", {}):
            issues.append(f"stack '{name}' detected but not configured: re-run /claude-kit")

    md_rel = "CLAUDE.local.md" if is_local else "CLAUDE.md"
    claude_md = project / md_rel
    if claude_md.is_file():
        claude_text = claude_md.read_text(encoding="utf-8")
        left = claude_text.count(PLACEHOLDER)
        (issues if left else oks).append(f"{md_rel} has {left} section(s) still marked '{PLACEHOLDER}'" if left else f"{md_rel} fully filled")
        claude_lines = len(claude_text.splitlines())
        if claude_lines > MAX_CLAUDE_MD_LINES:
            issues.append(f"{md_rel} has {claude_lines} lines (recommended <= {MAX_CLAUDE_MD_LINES}): move stack details to .claude/rules/*.md or @imports")
        else:
            oks.append(f"{md_rel} within budget ({claude_lines} lines)")
    else:
        issues.append(f"{md_rel} is missing")

    mem_path = project / "MEMORY.md"
    if mem_path.is_file():
        mem_text = mem_path.read_text(encoding="utf-8")
        mem_lines = len(mem_text.splitlines())
        if mem_lines > MAX_MEMORY_MD_LINES:
            issues.append(f"MEMORY.md has {mem_lines} lines (warning threshold {MAX_MEMORY_MD_LINES} before 200-line truncation): prune or promote via /claude-kit-learn")
        old_entries = 0
        today = date.today()
        for raw_d in re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", mem_text):
            try:
                if (today - date.fromisoformat(raw_d)).days > MEMORY_STALE_DAYS:
                    old_entries += 1
            except ValueError:
                pass
        if old_entries:
            issues.append(f"MEMORY.md has {old_entries} entry(ies) older than {MEMORY_STALE_DAYS} days: promote durable rules to CLAUDE.md via /claude-kit-learn")
        if mem_lines <= MAX_MEMORY_MD_LINES and not old_entries:
            oks.append(f"MEMORY.md within budget ({mem_lines} lines)")
    else:
        issues.append("MEMORY.md is missing: re-run /claude-kit")

    harness_stats = _read_harness_stats(project)
    if harness_stats["total_blocks"]:
        for rec in harness_stats["recurring"]:
            issues.append(f"harness.log shows {rec['count']}x blocks for '{rec['key']}': add an explicit rule + alternative in CLAUDE.md via /claude-kit-learn")
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


def cmd_audit(args) -> None:
    """Read-only inventory of what the project already has, plus tooling conflicts."""
    project = Path(args.project).resolve()
    kit_json = load_kit_json(project)
    names = args.profiles or sorted(set(detect_matched(project)) | set(kit_json.get("profiles", {})))
    names = [n for n in names if (PROFILES / n / "profile.json").is_file()]
    profiles = [load_profile(n) for n in names]
    analysis = analyze_tooling(project, profiles, kit_json.get("decisions", {}))

    claude_md = project / "CLAUDE.md"
    sections = list(split_sections(claude_md.read_text(encoding="utf-8"))) if claude_md.is_file() else []
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
        try:
            allow = json.loads(settings_path.read_text(encoding="utf-8")).get("permissions", {}).get("allow", [])
            wanted = build_wanted_settings([effective_profile(p, analysis) for p in profiles], not args.no_org)
            extra_allow = [r for r in allow if r not in wanted["permissions"]["allow"]]
        except (json.JSONDecodeError, AttributeError):
            pass

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


def cmd_decide(args) -> None:
    project = Path(args.project).resolve()
    kit_json = load_kit_json(project)
    if not kit_json:
        raise SystemExit("No .claude/kit.json: run /claude-kit (apply) first, or pass decisions in its context.")
    if args.profile not in kit_json.get("profiles", {}) or not (PROFILES / args.profile / "profile.json").is_file():
        raise SystemExit(f"Profile '{args.profile}' is not configured in this project.")
    profile = load_profile(args.profile)
    analysis = analyze_tooling(project, [profile], kit_json.get("decisions", {}))
    report = []
    decisions = kit_json.setdefault("decisions", {})
    record_decisions(decisions, {args.profile: {args.concern: args.choice}}, analysis, report)
    if report:
        raise SystemExit("\n".join(report))
    kit_json["decisions"] = decisions
    write_text(project / ".claude" / "kit.json", json.dumps(kit_json, indent=2, ensure_ascii=False) + "\n", args.dry_run)
    print(("[DRY-RUN: nothing was written]\n" if args.dry_run else "")
          + f"recorded {args.profile}/{args.concern}: {args.choice}. Run `sync` to apply it to settings and kit.json.")
