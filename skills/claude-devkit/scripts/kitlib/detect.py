"""`detect`: walk a project and match it against known stack profiles."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path

from .core import IGNORED_DIRS, load_profile, MAX_DETECT_DEPTH, MAX_MARKER_BYTES, profile_dirs


def collect_project_files(project: Path, max_depth: int = MAX_DETECT_DEPTH) -> list:
    """Single top-down walk pruning IGNORED_DIRS up to max_depth."""
    rel_files = []
    for root, dirs, files in os.walk(project, topdown=True):
        rel_root = Path(root).relative_to(project)
        depth = 0 if rel_root == Path(".") else len(rel_root.parts)
        if depth >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)

        prefix = "" if rel_root == Path(".") else rel_root.as_posix() + "/"
        for fname in files:
            rel_files.append(prefix + fname)
    return rel_files


def file_matches(rel_path: str, pattern: str) -> bool:
    if "/" in pattern:
        return fnmatch.fnmatch(rel_path, pattern)
    return fnmatch.fnmatch(rel_path.rsplit("/", 1)[-1], pattern)


def pattern_matches(rel_files: list, pattern: str) -> bool:
    return any(file_matches(rp, pattern) for rp in rel_files)


def entry_hits(project: Path, rel_files: list, entry) -> list:
    """Files satisfying one `detect` entry.

    entry is a glob string, `{"file": glob, "contains": text}` (marker_evidence rules: case-insensitive,
    first MAX_MARKER_BYTES, undecodable bytes replaced), or `{"all": [entry, ...]}`: every sub-entry
    must hit inside the SAME directory (so a monorepo package is not mixed with another's files).
    """
    if isinstance(entry, str):
        return [rp for rp in rel_files if file_matches(rp, entry)]
    if "all" in entry:
        per_part = [entry_hits(project, rel_files, part) for part in entry["all"]]
        dir_of = lambda rp: rp.rsplit("/", 1)[0] if "/" in rp else "."
        common = set.intersection(*(({dir_of(rp) for rp in hits}) for hits in per_part)) if per_part else set()
        return sorted({rp for hits in per_part for rp in hits if dir_of(rp) in common})
    needle = entry.get("contains")
    matched = [rp for rp in rel_files if file_matches(rp, entry["file"])]
    if not needle:
        return matched
    found = []
    for rp in matched:
        try:
            text = (project / rp).read_text(encoding="utf-8", errors="replace")[:MAX_MARKER_BYTES]
        except OSError:
            continue
        if needle.lower() in text.lower():
            found.append(rp)
    return found


def detect_details(project: Path) -> dict:
    """Return {stack: {"dirs": [...], "rule_paths": [...]}} for matched profiles, honoring supersedes."""
    rel_files = collect_project_files(project)
    loaded = [load_profile(f.name) for f in profile_dirs()]
    raw_matches = {}
    superseded = set()
    for p in loaded:
        hits = sorted({rp for entry in p.get("detect", []) for rp in entry_hits(project, rel_files, entry)})
        if hits:
            dirs = sorted({rp.rsplit("/", 1)[0] if "/" in rp else "." for rp in hits})
            rule_paths = ["**/*" if d == "." else f"{d}/**" for d in dirs]
            raw_matches[p["stack"]] = {"dirs": dirs, "rule_paths": rule_paths}
            superseded.update(p.get("supersedes") or [])
    return {s: info for s, info in raw_matches.items() if s not in superseded}


def detect_matched(project: Path) -> list:
    return list(detect_details(project).keys())


def cmd_detect(args) -> None:
    project = Path(args.project).resolve()
    known = [load_profile(f.name)["stack"] for f in profile_dirs()]
    details = detect_details(project)
    print(json.dumps({"matched": list(details.keys()), "known_profiles": known, "details": details}, ensure_ascii=False))
