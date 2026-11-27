#!/usr/bin/env python3
"""PreToolUse hook: blocks destructive actions BEFORE they execute.

Claude Code passes JSON on stdin (tool name + tool parameters).
Exiting with code 2 blocks the action and sends stderr back to Claude.
Code 0 allows the action to proceed.

WARNING: this is a safety net against accidents, not a security boundary.
`deny` rules in settings.json and an isolated environment remain more reliable.
"""
import json
import re
import shlex
import sys
from pathlib import Path

SAFE_ENV_SUFFIXES = (".env.example", ".env.sample", ".env.template", ".env.dist")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
SECRET_NAMES = {"credentials", "credentials.json", ".npmrc", ".pypirc"}

PROTECTED_POSIX_DIRS = {
    "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64",
    "/opt", "/proc", "/root", "/sbin", "/sys", "/usr", "/var",
}
PROTECTED_WIN_DIRS = {
    "windows", "users", "program files", "program files (x86)", "programdata", "system32",
}
WIN_DELETE_CMDS = {"remove-item", "ri", "rd", "rmdir", "del", "erase"}


def block(message: str) -> None:
    print(f"BLOCKED: {message}", file=sys.stderr)
    sys.exit(2)


def is_protected_file(path: str) -> bool:
    """Return True if path points to a secret/key/credential file (excluding .env templates)."""
    if not path:
        return False
    name = Path(path.replace("\\", "/")).name.lower()
    if not name or name.endswith(SAFE_ENV_SUFFIXES):
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name.endswith(SECRET_SUFFIXES):
        return True
    if name.startswith(("id_rsa", "id_ed25519")):
        return True
    return name in SECRET_NAMES


def _tokenize(segment: str, posix: bool = True) -> list:
    try:
        return shlex.split(segment, posix=posix)
    except ValueError:
        return segment.split()


def _is_dangerous_rm_target(raw_target: str) -> bool:
    target = raw_target.strip().strip("\"'")
    if not target:
        return False
    normalized = target.rstrip("/") or "/"
    if normalized in {"/", "/*", ".", "..", "*", "~", "$HOME", "${HOME}"}:
        return True
    if normalized.startswith(("~/", "$HOME/", "${HOME}/", "./*", "../*")):
        return True
    if normalized in {"/tmp", "/tmp/*"}:
        return True
    for protected in PROTECTED_POSIX_DIRS:
        if normalized == protected or normalized.startswith(protected + "/"):
            return True
    return False


def _check_rm_segment(tokens: list) -> str | None:
    if not tokens or Path(tokens[0]).name.lower() != "rm":
        return None
    recursive = False
    targets = []
    after_double_dash = False
    for tok in tokens[1:]:
        if not after_double_dash and tok == "--":
            after_double_dash = True
            continue
        if not after_double_dash and tok.startswith("-"):
            if tok == "--recursive" or (not tok.startswith("--") and any(c in tok[1:] for c in "rR")):
                recursive = True
            continue
        targets.append(tok)
    if recursive and any(_is_dangerous_rm_target(t) for t in targets):
        return "recursive rm on a dangerous path (root, system dir, home, parent, '.', '*')."
    return None


def _is_dangerous_win_target(raw_target: str, recursive: bool) -> bool:
    target = raw_target.strip().strip("\"'").replace("/", "\\")
    if not target:
        return False
    low = target.lower().rstrip("\\")
    if re.fullmatch(r"[a-z]:(?:\\?\*)?", low):
        return True
    m = re.match(r"^[a-z]:\\([^\\]+)", low)
    if m and m.group(1) in PROTECTED_WIN_DIRS:
        return True
    if recursive and low in {".", "..", "*", "~", "$home", "$env:userprofile"}:
        return True
    if recursive and low.startswith(("~\\", "$home\\", "$env:userprofile\\")):
        return True
    return False


def _check_win_delete_segment(tokens: list) -> str | None:
    if not tokens or tokens[0].lower() not in WIN_DELETE_CMDS:
        return None
    cmd = tokens[0].lower()
    recursive = cmd in {"rd", "rmdir"} and any(t.lower() in {"/s", "-recurse"} for t in tokens[1:])
    if cmd in {"remove-item", "ri"}:
        recursive = any(t.lower() in {"-recurse", "-r"} for t in tokens[1:])
    if cmd in {"del", "erase"}:
        recursive = any(t.lower() == "/s" for t in tokens[1:])

    targets = [t for t in tokens[1:] if not t.startswith(("-", "/"))]
    for target in targets:
        if _is_dangerous_win_target(target, recursive):
            return f"dangerous Windows deletion ({tokens[0]} on drive root, system dir, or recursive wildcard/home)."
    return None


def check_bash_command(command: str) -> str | None:
    """Return a block reason if command matches a destructive pattern, else None."""
    if re.search(r"\b(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z)?sh\b", command):
        return "executing a downloaded script (curl | sh)."

    for segment in re.split(r"(?:\|\||&&|[|;&\n])", command):
        seg = segment.strip()
        if not seg:
            continue
        if re.search(r"\bsudo\b", seg):
            return "sudo is not allowed."
        if re.search(r"(?i)\bdrop\s+(?:database|table|schema)\b", seg):
            return "DROP on a database. Use a manually reviewed migration instead."
        if re.search(r"\bgit\s+reset\s+--hard\b", seg):
            return "git reset --hard destroys uncommitted changes. Ask for confirmation."
        if re.search(r"\bgit\s+clean\b[^|;&]*(?:\s-[a-zA-Z]*f|\s--force\b)", seg):
            return "git clean -f deletes untracked files. Ask for confirmation."
        if re.search(r"\bgit\s+push\b", seg):
            if re.search(r"(?:--force\b|--force-with-lease\b|\s-f\b)", seg):
                return "git push --force / --force-with-lease. Ask the user for explicit confirmation."
            if re.search(r"\bgit\s+push\b(?:\s+\S+)*\s+\+\S+", seg):
                return "git push with '+' force refspec. Ask the user for explicit confirmation."

        posix_tokens = _tokenize(seg, posix=True)
        rm_reason = _check_rm_segment(posix_tokens)
        if rm_reason:
            return rm_reason

        win_tokens = _tokenize(seg, posix=False)
        win_reason = _check_win_delete_segment(win_tokens)
        if win_reason:
            return win_reason
    return None


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # unreadable input: do not block

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool in ("Write", "Edit", "MultiEdit"):
        path = tool_input.get("file_path", "") or ""
        if is_protected_file(path):
            block(f"writing to a protected file ({path}). Use the provider's environment variables instead.")

    if tool == "Bash":
        reason = check_bash_command(tool_input.get("command", "") or "")
        if reason:
            block(reason)

    sys.exit(0)


if __name__ == "__main__":
    main()
