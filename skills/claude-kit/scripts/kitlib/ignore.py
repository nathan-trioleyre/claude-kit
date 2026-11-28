"""Ignore files the kit appends to: .gitignore (shared mode) and .git/info/exclude (local mode)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .core import append_lines, read_text_lossy

GITIGNORE_HEADER = "# Claude Code (local files)"
EXCLUDE_HEADER = "# claude-kit (local)"
KIT_IGNORE_HEADERS = (GITIGNORE_HEADER, EXCLUDE_HEADER)
# Files the kit (or its skills) generates that must never be committed.
LOCAL_ARTIFACTS = [".claude/handoff.md", ".claude/settings.json.bak", ".claude/settings.local.json.bak"]
GITIGNORE_LINES = [".claude/settings.local.json", ".claude/logs/", "CLAUDE.local.md",
                   "CLAUDE.md.proposed", ".claude/rules/*.proposed", *LOCAL_ARTIFACTS]


def resolve_git_exclude(project: Path) -> Path | None:
    """Path of the repository's info/exclude (works for worktrees and submodules), or None without git."""
    try:
        out = subprocess.run(["git", "-C", str(project), "rev-parse", "--git-path", "info/exclude"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0 and out.stdout.strip():
            path = Path(out.stdout.strip())
            return path if path.is_absolute() else project / path
    except (OSError, subprocess.SubprocessError):
        pass
    dot_git = project / ".git"
    if dot_git.is_dir():
        return dot_git / "info" / "exclude"
    if dot_git.is_file():  # worktree/submodule: ".git" is a file "gitdir: <path>"
        text = read_text_lossy(dot_git).strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text[len("gitdir:"):].strip())
            gitdir = gitdir if gitdir.is_absolute() else project / gitdir
            common = gitdir / "commondir"
            if common.is_file():
                target = Path(read_text_lossy(common).strip())
                gitdir = target if target.is_absolute() else gitdir / target
            return gitdir / "info" / "exclude"
    return None


def _missing_lines(path: Path, wanted: list) -> list:
    present = {line.strip() for line in read_text_lossy(path).splitlines()} if path.exists() else set()
    return [p for p in dict.fromkeys(wanted) if p not in present]


def update_git_exclude(project: Path, paths: list, dry: bool, report: list) -> list:
    """Add kit-managed local paths to .git/info/exclude. Returns the lines added."""
    exclude = resolve_git_exclude(project)
    if exclude is None:
        report.append("WARNING   no git repository found: local files cannot be hidden from git "
                      "(add these to .git/info/exclude yourself once the repo exists): "
                      + ", ".join(dict.fromkeys(paths)))
        return []
    missing = _missing_lines(exclude, paths)
    if missing:
        append_lines(exclude, EXCLUDE_HEADER, missing, dry)
        report.append(f"updated   .git/info/exclude (+{len(missing)} lines)")
    return missing


def update_gitignore(project: Path, dry: bool, report: list) -> list:
    """Add the kit's lines to .gitignore. Returns the lines added."""
    gitignore = project / ".gitignore"
    missing = _missing_lines(gitignore, GITIGNORE_LINES)
    if missing:
        append_lines(gitignore, GITIGNORE_HEADER, missing, dry)
        report.append(f"updated   .gitignore (+{len(missing)} lines)")
    return missing


def remove_kit_lines(path: Path, recorded: list | None, dry: bool) -> list:
    """Remove the kit's block(s) from an ignore file. Returns the removed lines.

    With `recorded` (kit.json), only those lines are removed; for an older kit.json every line of
    a kit-headed block is. The rest of the file is kept byte for byte (EOL included).
    """
    if not path.is_file():
        return []
    raw = path.read_bytes().decode("utf-8", errors="surrogateescape")
    lines = raw.splitlines(keepends=True)
    keep, removed, i = [], [], 0
    while i < len(lines):
        if lines[i].strip() in KIT_IGNORE_HEADERS:
            j = i + 1
            while j < len(lines) and lines[j].strip() and (recorded is None or lines[j].strip() in recorded):
                removed.append(lines[j].strip())
                j += 1
            if keep and not keep[-1].strip():
                keep.pop()  # the blank separator the kit added before its block
            i = j
            continue
        keep.append(lines[i])
        i += 1
    if removed and not dry:
        path.write_bytes("".join(keep).encode("utf-8", errors="surrogateescape"))
    return removed

