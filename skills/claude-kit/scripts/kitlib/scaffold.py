"""`scaffold-tooling`: non-destructive linter/formatter preset scaffolding."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .core import BASE, detect_eol, emit, _is_unsafe_dest_path, load_kit_json, load_profile, PROFILES, read_json, write_text
from .tooling import analyze_tooling
from .ci import render_ci_workflow


def _copy_preset_non_destructive(src: Path, dest: Path, label: str, project: Path, dry: bool,
                                 report: list, *, executable: bool = False) -> None:
    proj_root = project.resolve()
    dest_resolved = dest.resolve()
    if (_is_unsafe_dest_path(label) or _is_unsafe_dest_path(dest_resolved.name)
            or dest_resolved == proj_root or not dest_resolved.is_relative_to(proj_root)):
        raise SystemExit(f"Unsafe preset destination: {label}")
    if dest.exists():
        report.append(f"skipped   {label} (already exists)")
        return
    write_text(dest, src.read_text(encoding="utf-8"), dry)
    if executable and not dry:
        dest.chmod(dest.stat().st_mode | 0o111)
    report.append(f"created   {label}")


def _detect_indent(text: str):
    """Indent unit of a JSON text: a tab, or a number of spaces (2 when undetectable)."""
    m = re.search(r"^([ \t]+)\S", text, re.MULTILINE)
    if not m:
        return 2
    lead = m.group(1)
    return "\t" if lead.startswith("\t") else (len(lead) if len(lead) in (2, 4) else 2)


def merge_package_json_scripts(pkg_path: Path, scripts: dict, dry: bool, report: list) -> None:
    """Add missing scripts to package.json, keeping the file's indentation and line endings."""
    if not pkg_path.is_file() or not scripts:
        return
    data = read_json(pkg_path, "package.json")
    raw = pkg_path.read_bytes().decode("utf-8-sig", errors="replace")
    pkg_scripts = data.setdefault("scripts", {})
    if not isinstance(pkg_scripts, dict):
        raise SystemExit(f"{pkg_path} 'scripts' must be a JSON object.")
    added = [k for k in scripts if k not in pkg_scripts]
    for k in added:
        pkg_scripts[k] = scripts[k]
    if added:
        eol = detect_eol(raw)
        text = json.dumps(data, indent=_detect_indent(raw), ensure_ascii=False).replace("\n", eol)
        if raw.endswith("\n") or not raw.strip():
            text += eol
        if not dry:
            pkg_path.write_bytes(text.encode("utf-8"))
        report.append(f"merged    package.json scripts (+{', '.join(added)})")


def _resolve_install_packages(profile: dict, project: Path, pkgs) -> list:
    if isinstance(pkgs, list):
        return pkgs
    if isinstance(pkgs, dict) and pkgs:
        kit_json = load_kit_json(project)
        analysis = analyze_tooling(project, [profile], kit_json.get("decisions", {}))
        pm = next((a["existing"][0]["name"] for a in analysis
                   if a["concern"] == "package-manager" and a["existing"] and a["effective"] == "keep_existing"), None)
        if pm and pm in pkgs:
            return pkgs[pm]
        for item in profile.get("tooling", []):
            if item.get("concern") == "package-manager" and item["kit"]["name"] in pkgs:
                return pkgs[item["kit"]["name"]]
        return next(iter(pkgs.values()))
    return []


def cmd_scaffold_tooling(args) -> None:
    project = Path(args.project).resolve()
    kit_json = load_kit_json(project)
    if args.local or kit_json.get("local"):
        raise SystemExit("scaffold-tooling is disabled in local mode (must not modify shared repo files).")
    if not args.base_preset and not (args.profile and args.concern):
        raise SystemExit("Specify --base-preset or both --profile and --concern.")

    report = []
    if args.base_preset:
        if args.base_preset == "editorconfig":
            _copy_preset_non_destructive(
                BASE / "presets" / ".editorconfig.template", project / ".editorconfig",
                ".editorconfig", project, args.dry_run, report,
            )
        elif args.base_preset == "pre-commit":
            hook_markers = (".husky", ".pre-commit-config.yaml", "lefthook.yml", ".githooks")
            if any((project / m).exists() for m in hook_markers):
                report.append("skipped   .githooks/pre-commit (existing git hook framework detected)")
            else:
                _copy_preset_non_destructive(
                    BASE / "presets" / "pre-commit.template", project / ".githooks" / "pre-commit",
                    ".githooks/pre-commit", project, args.dry_run, report, executable=True,
                )
                report.append("hint      run `git config core.hooksPath .githooks` locally to activate")
        elif args.base_preset == "ci":
            ci_dest = project / ".github" / "workflows" / "ci.yml"
            if ci_dest.exists():
                report.append("skipped   .github/workflows/ci.yml (already exists)")
            else:
                ci_content = render_ci_workflow(project)
                write_text(ci_dest, ci_content, args.dry_run)
                report.append("created   .github/workflows/ci.yml")
        emit(report, args.dry_run)
        return

    profile = load_profile(args.profile)
    item = next((i for i in profile.get("tooling", []) if i.get("concern") == args.concern), None)
    if item is None:
        raise SystemExit(f"No tooling concern '{args.concern}' in profile '{args.profile}'.")

    kit = item["kit"]
    if kit.get("scripts"):
        merge_package_json_scripts(project / "package.json", kit["scripts"], True, [])
    prof_root = (PROFILES / profile["stack"]).resolve()
    for pf in kit.get("preset_files", []):
        src_path = (prof_root / pf["src"]).resolve()
        if not src_path.is_relative_to(prof_root) or not src_path.is_file():
            raise SystemExit(f"Invalid preset source '{pf['src']}' in profile '{profile['stack']}'.")
        mode = pf.get("mode", "create")
        if mode == "snippet":
            report.append(f"SNIPPET {pf['dest']}:\n{src_path.read_text(encoding='utf-8').strip()}")
        else:
            _copy_preset_non_destructive(
                src_path, project / pf["dest"], pf["dest"], project, args.dry_run, report,
            )

    if kit.get("scripts"):
        merge_package_json_scripts(project / "package.json", kit["scripts"], args.dry_run, report)

    pkgs = _resolve_install_packages(profile, project, kit.get("install_packages"))
    if pkgs:
        report.append(f"install_packages: {', '.join(pkgs)}")

    emit(report, args.dry_run)
