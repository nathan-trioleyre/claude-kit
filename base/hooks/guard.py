#!/usr/bin/env python3
"""PreToolUse hook: blocks destructive actions BEFORE they execute.
# claude-kit-hook-version: 4

Claude Code passes JSON on stdin (tool name + tool parameters).
Exiting with code 2 blocks the action and sends stderr back to Claude.
Code 0 allows the action to proceed.

WARNING: this is a safety net against accidents, not a security boundary.
`deny` rules in settings.json and an isolated environment remain more reliable.
"""
from datetime import datetime, timezone
import json
import os
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
# Shells that take an inline script: the script is inspected recursively.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"}
SHELL_INLINE_FLAGS = {"-c", "-command", "/c", "-encodedcommand"}
# Commands that read/copy/send a file: forbidden on secret files.
READER_CMDS = {
    "cat", "type", "less", "more", "head", "tail", "bat", "nl", "tac", "xxd", "strings",
    "get-content", "gc", "select-string", "sls", "grep", "rg", "egrep", "fgrep", "sed", "awk",
    "cp", "copy", "mv", "move", "scp", "base64", "openssl", "source", ".",
}
MAX_SHELL_DEPTH = 3


def log_block(payload: dict, tool: str, target: str, reason: str) -> None:
    try:
        project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
        claude_dir = project / ".claude"
        if not claude_dir.is_dir():
            return
        log_dir = claude_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": "guard",
            "tool": tool,
            "target": target[:200],
            "reason": reason,
        }
        with (log_dir / "harness.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def block(message: str, payload: dict | None = None, tool: str = "", target: str = "") -> None:
    if payload is not None:
        log_block(payload, tool, target, message)
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
    if recursive and any(_is_dangerous_rm_target(t) or _is_dangerous_win_target(t, True) for t in targets):
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


def _cmd_name(token: str) -> str:
    name = Path(token.replace("\\", "/")).name.lower()
    return name[:-4] if name.endswith(".exe") else name


def _inline_script(tokens: list) -> str | None:
    """For `bash -c "..."` / `pwsh -Command "..."` return the inline script, else None."""
    if not tokens or _cmd_name(tokens[0]) not in SHELLS:
        return None
    for idx, tok in enumerate(tokens[1:], start=1):
        low = tok.lower()
        if low in SHELL_INLINE_FLAGS and idx + 1 < len(tokens):
            return " ".join(tokens[idx + 1:])
        if low.startswith("-") and not low.startswith("--") and "c" in low[1:] and len(low) <= 4 and idx + 1 < len(tokens):
            return " ".join(tokens[idx + 1:])  # combined flags such as -lc
    return None


def _check_secret_access(tokens: list, segment: str) -> str | None:
    if tokens and _cmd_name(tokens[0]) in READER_CMDS:
        for tok in tokens[1:]:
            if not tok.startswith("-") and is_protected_file(tok.strip("\"'")):
                return f"reading/copying a protected file ({tok}). Use the provider's environment variables instead."
    for target in re.findall(r">>?\s*[\"']?([^\s\"'|;&]+)", segment):
        if is_protected_file(target):
            return f"redirecting output into a protected file ({target})."
    return None


def _npmrc_has_ignore_scripts() -> bool:
    try:
        npmrc = Path.home() / ".npmrc"
        if not npmrc.is_file():
            return False
        text = npmrc.read_text(encoding="utf-8", errors="ignore")
        return bool(re.search(r"(?im)^\s*ignore-scripts\s*=\s*true\s*$", text))
    except OSError:
        return False


def _check_supply_chain(tokens: list) -> str | None:
    if not tokens:
        return None
    cmd = _cmd_name(tokens[0])
    # Block raw pip install / pip3 install / python -m pip install (runs setup.py)
    if cmd in {"pip", "pip3"} and len(tokens) > 1 and tokens[1].lower() == "install":
        return "raw pip install executes arbitrary setup.py scripts. Use 'uv add' / 'uv sync' instead."
    if cmd in {"python", "python3", "py"} and len(tokens) >= 4:
        if tokens[1] == "-m" and tokens[2].lower() == "pip" and tokens[3].lower() == "install":
            return "raw python -m pip install executes arbitrary setup.py scripts. Use 'uv add' / 'uv sync' instead."
    # Block `npm install <pkg>` when ignore-scripts is not set globally or via CLI flag
    if cmd == "npm" and len(tokens) >= 2 and tokens[1].lower() in {"install", "i"}:
        args = [t for t in tokens[2:] if not t.startswith("-")]
        has_flag = any(t == "--ignore-scripts" for t in tokens[2:])
        if args and not has_flag and not _npmrc_has_ignore_scripts():
            return "npm install <pkg> without ignore-scripts can run malicious postinstall scripts. Add 'ignore-scripts=true' to ~/.npmrc or pass '--ignore-scripts'."
    return None


def _check_git_and_find(segment: str, tokens: list) -> str | None:
    if re.search(r"\bgit\s+branch\b[^|;&]*\s-D\b", segment):
        return "git branch -D deletes a branch irrecoverably. Ask for confirmation."
    if re.search(r"\bgit\s+push\b[^|;&]*(?:--delete\b|\s:\S+)", segment):
        return "git push deleting a remote branch/tag. Ask for confirmation."
    if re.search(r"\bgit\s+(?:checkout\s+--\s|restore\s+(?!--staged))", segment):
        return "discarding working-tree changes (git checkout -- / git restore). Ask for confirmation."
    if tokens and _cmd_name(tokens[0]) == "find" and any(t in {"-delete", "-exec", "-execdir", "-ok"} for t in tokens):
        if "-delete" in tokens or any(t in {"rm", "rmdir", "del"} for t in tokens):
            return "find ... -delete / -exec rm deletes files in bulk. Ask for confirmation."
    return None


def check_bash_command(command: str, _depth: int = 0) -> str | None:
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
        if _depth < MAX_SHELL_DEPTH:
            inline = _inline_script(posix_tokens)
            if inline:
                nested = check_bash_command(inline, _depth + 1)
                if nested:
                    return nested
        extra = _check_secret_access(posix_tokens, seg) or _check_git_and_find(seg, posix_tokens) or _check_supply_chain(posix_tokens)
        if extra:
            return extra
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
            block(f"writing to a protected file ({path}). Use the provider's environment variables instead.",
                  payload, tool, path)

    if tool == "Bash":
        cmd = tool_input.get("command", "") or ""
        reason = check_bash_command(cmd)
        if reason:
            block(reason, payload, tool, cmd)

    sys.exit(0)


if __name__ == "__main__":
    main()
