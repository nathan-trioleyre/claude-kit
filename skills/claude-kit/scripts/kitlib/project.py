"""`apply`, `sync`, `decide`: write a project's kit-managed config."""

from __future__ import annotations

import difflib
import json
import shutil
from datetime import date
from pathlib import Path

from .core import (
    age_days,
    BASE,
    emit,
    GENERATED_FOOTER_PREFIXES,
    KIT_VERSION,
    load_context,
    load_kit_json,
    load_profile,
    ORG,
    PLACEHOLDER,
    PROFILES,
    read_json,
    sha256_norm,
    STALE_DAYS,
    write_non_destructive,
    write_text,
)
from .ignore import LOCAL_ARTIFACTS, update_git_exclude, update_gitignore
from .preflight import preflight
from .settings import apply_settings, read_org_text
from .tooling import (
    analyze_tooling,
    effective_profile,
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


def sync_file(src: Path, dest: Path, label: str, managed: dict, dry: bool, report: list, force: bool) -> None:
    """Copy a kit file into the project.

    - missing: created
    - identical: unchanged
    - differs but unmodified since the kit installed it (hash recorded in kit.json): upgraded
    - differs and modified by the user (or installed before hashes were recorded): skipped
      unless `force` (--force-hooks)
    """
    src_hash = sha256_norm(src.read_bytes())

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
    dest_hash = sha256_norm(dest.read_bytes())
    if dest_hash == src_hash:
        managed[label] = src_hash
        report.append(f"unchanged {label}")
    elif force or managed.get(label) == dest_hash:
        put("upgraded " if not force else "forced   ")
    else:
        report.append(f"skipped   {label} differs from the kit and was modified locally (use --force-hooks to overwrite)")
        if dry:
            diff = difflib.unified_diff(
                dest.read_text(encoding="utf-8", errors="replace").splitlines(),
                src.read_text(encoding="utf-8", errors="replace").splitlines(),
                fromfile=f"{label} (yours)", tofile=f"{label} (kit)", lineterm="", n=1)
            shown = list(diff)
            report.extend(f"          {line}" for line in shown[:24])
            if len(shown) > 24:
                report.append(f"          ... ({len(shown) - 24} more diff lines)")


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
        wanted = read_json(mcp_src, "org/mcp.json").get("mcpServers", {})
        target = project / ".mcp.json"
        if local and target.exists():
            report.append("skipped   .mcp.json preserved (local mode)")
            return False
        existed = target.exists()
        existing = read_json(target, ".mcp.json") if existed else {}
        servers = existing.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise SystemExit(".mcp.json: 'mcpServers' must be an object: leaving it untouched.")
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
                   local: bool = False, *, full: bool = True, extra: dict | None = None) -> None:
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
        **(extra or {}),
    }
    write_text(project / ".claude" / "kit.json", json.dumps(kit_json, indent=2, ensure_ascii=False) + "\n", dry)
    report.append("written   .claude/kit.json")


def run(project: Path, profile_names: list, ctx: dict, dry: bool, *, full: bool,
        force_hooks: bool = False, use_org: bool = True, local: bool | None = None) -> list:
    report = []
    previous = preflight(project)
    is_local = bool(previous.get("local", False)) if local is None else local
    managed = dict(previous.get("managed", {}))
    rendered_state = dict(previous.get("rendered", {}))

    # Every profile this project knows (previous runs + this one), adjusted by tooling decisions.
    known_names = list(dict.fromkeys(
        list(profile_names) + [n for n in previous.get("profiles", {}) if (PROFILES / n / "profile.json").is_file()]))
    raw = {name: load_profile(name) for name in known_names}
    decisions = json.loads(json.dumps(previous.get("decisions", {})))
    ctx_decisions = ctx.get("decisions") or {}
    if not isinstance(ctx_decisions, dict) or not all(isinstance(cs, dict) or cs is None for cs in ctx_decisions.values()):
        raise SystemExit("--context: 'decisions' must be {stack: {concern: choice}}.")
    incoming = {s: {c: normalize_decision(v) for c, v in (cs or {}).items()}
                for s, cs in ctx_decisions.items()}
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

    # 3. settings.json or settings.local.json (additive merge + legacy kit hook upgrade; backup first)
    added_permissions = apply_settings(project, profiles, dry, report, use_org, local=is_local)

    # 4. hooks, agents, commands, rules, skills, MCP servers
    mcp_created = sync_extras(project, managed, dry, report, force_hooks, use_org, local=is_local)
    sync_codemap(project, managed, dry, report)
    hook_skips = [line.split()[1] for line in report if line.startswith("skipped   .claude/hooks/")]
    if hook_skips:
        report.append(f"! {len(hook_skips)} hook(s) modified locally were NOT updated: {', '.join(hook_skips)} "
                      "(see the diff with --dry-run; --force-hooks overwrites them)")

    # 5. .gitignore (shared mode) or .git/info/exclude (local mode)
    if is_local:
        exclude_paths = [
            "CLAUDE.local.md", "CLAUDE.local.md.proposed",
            ".claude/settings.local.json", ".claude/kit.json", ".claude/logs/", ".claude/rules/*.proposed",
            *LOCAL_ARTIFACTS, *sorted(managed), *rule_labels,
        ]
        if mcp_created:
            exclude_paths.append(".mcp.json")
        ignore_target, ignore_added = ".git/info/exclude", update_git_exclude(project, exclude_paths, dry, report)
    else:
        ignore_target, ignore_added = ".gitignore", update_gitignore(project, dry, report)

    # 6. kit.json (metadata, formatting rules, hashes, and what the kit added: needed by `uninstall`)
    recorded_perms = json.loads(json.dumps(previous.get("added_permissions", {})))
    settings_key = ".claude/settings.local.json" if is_local else ".claude/settings.json"
    for key, rules in added_permissions.items():
        bucket = recorded_perms.setdefault(settings_key, {}).setdefault(key, [])
        bucket.extend(r for r in rules if r not in bucket)
    recorded_ignore = json.loads(json.dumps(previous.get("added_ignore", {})))
    bucket = recorded_ignore.setdefault(ignore_target, [])
    bucket.extend(line for line in ignore_added if line not in bucket)
    write_kit_json(project, profiles, previous, managed, rendered_state, decisions, effective, dry, report, ctx,
                   local=is_local, full=full,
                   extra={"added_permissions": recorded_perms, "added_ignore": recorded_ignore})
    return report


def cmd_apply(args) -> None:
    project = Path(args.project).resolve()
    ctx = load_context(args.context)
    emit(run(project, args.profiles, ctx, args.dry_run, full=True,
             force_hooks=args.force_hooks, use_org=not args.no_org,
             local=True if args.local else None), args.dry_run)


def cmd_sync(args) -> None:
    project = Path(args.project).resolve()
    previous = preflight(project)
    if not previous:
        raise SystemExit("No .claude/kit.json: this project was never configured. Run /claude-kit (apply) first.")
    names = args.profiles or [n for n in previous.get("profiles", {}) if (PROFILES / n / "profile.json").is_file()]
    emit(run(project, names, {}, args.dry_run, full=False,
             force_hooks=args.force_hooks, use_org=not args.no_org,
             local=True if args.local else None), args.dry_run)


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
