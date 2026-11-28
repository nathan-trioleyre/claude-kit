#!/usr/bin/env python3
"""PreToolUse hook: blocks destructive actions BEFORE they execute.
# claude-kit-hook-version: 5

Claude Code passes JSON on stdin (tool name + tool parameters).
Exiting with code 2 blocks the action and sends stderr back to Claude.
Code 0 allows the action to proceed.

Covered tools: Bash and PowerShell (command), Write/Edit/MultiEdit (file_path),
NotebookEdit (notebook_path) and Read (file_path, second layer behind Read deny rules).

WARNING: this is a safety net against accidents, not a security boundary.
`deny` rules in settings.json and an isolated environment remain more reliable.
"""
from datetime import datetime, timezone
import json
import os
import re
import sys
from pathlib import Path

SAFE_ENV_SUFFIXES = (".env.example", ".env.sample", ".env.template", ".env.dist")
SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".tfvars")
SECRET_NAMES = {
    "credentials", "credentials.json", ".npmrc", ".pypirc", ".git-credentials", ".netrc", "_netrc",
}

# POSIX top-level dirs where any recursive delete is blocked.
PROTECTED_POSIX_DIRS = {
    "bin", "boot", "dev", "etc", "lib", "lib64", "opt", "proc", "root", "sbin", "sys", "usr", "var",
}
# Top-level dirs that hold user homes: the dir, a home and a home's direct child are blocked.
USER_HOME_ROOTS = {"home", "users"}
PROTECTED_WIN_DIRS = {"windows", "program files", "program files (x86)", "programdata", "system32"}
HOME_PREFIXES = ("~", "$home", "${home}", "$env:userprofile", "${env:userprofile}", "$env:home", "%userprofile%")
WILDCARDS = {"*", "*.*"}

WIN_DELETE_CMDS = {"remove-item", "ri", "rd", "rmdir", "del", "erase"}
# Shells that take an inline script: the script is inspected recursively.
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "pwsh", "powershell", "cmd"}
SHELL_INLINE_FLAGS = {"-c", "-command", "/c", "-encodedcommand"}
# Commands that read a file: forbidden on secret files.
READER_CMDS = {
    "cat", "type", "less", "more", "head", "tail", "bat", "nl", "tac", "xxd", "strings",
    "get-content", "gc", "base64", "source", ".",
}
# First positional argument is a pattern/script, not a file.
PATTERN_CMDS = {"grep", "rg", "egrep", "fgrep", "select-string", "sls", "sed", "awk"}
# cp-like: every positional except the last is a source (read).
COPY_CMDS = {"cp", "copy", "mv", "move", "scp", "copy-item", "cpi", "move-item", "mi"}
OPENSSL_READ_FLAGS = {"-in", "-key", "-inkey", "-signkey", "-cakey", "-kfile", "-passin"}
SQL_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "mongo", "mongosh", "duckdb", "cockroach"}
DOWNLOADERS = {"curl", "wget", "irm", "iwr", "invoke-webrequest", "invoke-restmethod"}
EVALUATORS = SHELLS | {"iex", "invoke-expression", "python", "python3", "node", "perl", "ruby"}
# Prefixes that run the next word as the real command.
WRAPPERS = {"env", "nohup", "time", "command", "exec", "nice", "then", "do", "else", "!"}
XARGS_VALUE_FLAGS = {"-n", "-i", "-p", "-l", "-d", "-e", "-s", "-a"}
GIT_GLOBAL_VALUE_OPTS = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
MAX_SHELL_DEPTH = 3

BLOCK_SUFFIX = (" Do not retry with a variant or workaround: if it is really needed, "
                "ask the user to run it themselves.")


# --------------------------------------------------------------------------- output

def _utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


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
    print(f"BLOCKED: {message}{BLOCK_SUFFIX}", file=sys.stderr)
    sys.exit(2)


# --------------------------------------------------------------------------- secret files

def is_protected_file(path: str) -> bool:
    """Return True if path points to a secret/key/credential file (excluding .env templates)."""
    if not path:
        return False
    p = Path(path.strip().strip("\"'").replace("\\", "/"))
    name = p.name.lower()
    if not name or name.endswith(SAFE_ENV_SUFFIXES):
        return False
    if name == ".env" or name.startswith(".env."):
        return True
    if name.endswith(SECRET_SUFFIXES):
        return True
    if name.startswith(("id_rsa", "id_ed25519")):
        return True
    if name == "config.json" and p.parent.name.lower() == ".docker":
        return True
    return name in SECRET_NAMES


# --------------------------------------------------------------------------- parsing

def split_segments(command: str) -> list:
    """Split a command line on ; && || | & and newlines, ignoring separators inside quotes.

    Returns a list of (segment_text, piped) where piped is True when the segment
    receives the output of the previous one through `|`.
    """
    segments, buf, quote, piped_next = [], [], None, False
    i, n = 0, len(command)

    def flush(next_piped: bool) -> None:
        nonlocal buf, piped_next
        text = "".join(buf).strip()
        if text:
            segments.append((text, piped_next))
        buf, piped_next = [], next_piped

    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif command.startswith(("&&", "||"), i):
            flush(False)
            i += 1
        elif ch == "|":
            flush(True)
        elif ch in ";&\n":
            if ch == "&" and i > 0 and command[i - 1] in "<>":
                buf.append(ch)  # 2>&1 style redirection
            else:
                flush(False)
        else:
            buf.append(ch)
        i += 1
    flush(False)
    return segments


def tokenize(segment: str) -> list:
    """Whitespace split honouring quotes; quote chars are removed, backslashes are kept
    literally (so Windows paths survive) except for \\" inside double quotes."""
    tokens, buf, quote, has_token = [], [], None, False
    i, n = 0, len(segment)
    while i < n:
        ch = segment[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n and segment[i + 1] == '"':
                buf.append('"')
                i += 1
            elif ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "\"'":
            quote, has_token = ch, True
        elif ch.isspace():
            if buf or has_token:
                tokens.append("".join(buf))
            buf, has_token = [], False
        else:
            buf.append(ch)
        i += 1
    if buf or has_token:
        tokens.append("".join(buf))
    return tokens


def cmd_name(token: str) -> str:
    stripped = token.replace("\\", "/").lstrip("({&")
    name = Path(stripped).name.lower() or stripped.lower()
    return name[:-4] if name.endswith(".exe") else name


def strip_wrappers(tokens: list) -> tuple:
    """Drop env assignments and wrappers (env, nohup, xargs...). Returns (tokens, via_xargs)."""
    via_xargs = False
    toks = list(tokens)
    while toks:
        head = toks[0]
        name = cmd_name(head)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            toks = toks[1:]
        elif name in WRAPPERS:
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                toks = toks[1:]
        elif name == "xargs":
            via_xargs = True
            toks = toks[1:]
            while toks and toks[0].startswith("-"):
                flag = toks[0].lower()
                toks = toks[1:]
                if flag in XARGS_VALUE_FLAGS and toks:
                    toks = toks[1:]
        else:
            break
    return toks, via_xargs


def positionals(args: list) -> list:
    return [a for a in args if a and not a.startswith("-")]


def _inline_script(tokens: list) -> str | None:
    """For `bash -c "..."` / `pwsh -Command "..."` return the inline script, else None."""
    if not tokens or cmd_name(tokens[0]) not in SHELLS:
        return None
    for idx, tok in enumerate(tokens[1:], start=1):
        low = tok.lower()
        if idx + 1 >= len(tokens):
            break
        if low in SHELL_INLINE_FLAGS:
            return " ".join(tokens[idx + 1:])
        if low.startswith("-") and not low.startswith("--") and "c" in low[1:] and len(low) <= 4:
            return " ".join(tokens[idx + 1:])  # combined flags such as -lc
    return None


# --------------------------------------------------------------------------- deletion targets

def _project_root() -> str | None:
    raw = os.environ.get("CLAUDE_PROJECT_DIR")
    return normalize_path(raw) if raw else None


def normalize_path(raw: str) -> str:
    """Lower-cased, forward-slash path; homes become `~`, Git Bash `/c/x` becomes `c:/x`."""
    t = raw.strip().strip("\"'").rstrip(")").replace("\\", "/")
    low = t.lower()
    for prefix in HOME_PREFIXES:
        if low == prefix or low.startswith(prefix + "/"):
            low = "~" + low[len(prefix):]
            break
    m = re.match(r"^/(?:mnt/|cygdrive/)?([a-z])(/.*)?$", low)
    if m:
        low = f"{m.group(1)}:{m.group(2) or '/'}"
    low = re.sub(r"/{2,}", "/", low)
    if len(low) > 1 and low.endswith("/") and not re.fullmatch(r"[a-z]:/", low):
        low = low.rstrip("/")
    return low


def _split_root(norm: str) -> tuple:
    """Return (root, parts): root is '~', '/', 'c:' (drive) or '' (relative)."""
    if norm == "~" or norm.startswith("~/"):
        root, rest = "~", norm[1:]
    elif re.match(r"^[a-z]:", norm):
        root, rest = norm[:2], norm[2:]
    elif norm.startswith("/"):
        root, rest = "/", norm
    else:
        root, rest = "", norm
    parts = [p for p in rest.split("/") if p and p != "."]
    return root, parts


def _inside(path: str, parent: str) -> bool:
    return path != parent and path.startswith(parent.rstrip("/") + "/")


def is_dangerous_delete_target(raw: str, recursive: bool = True) -> bool:
    """True for roots, system dirs, homes (and their direct children), '.', '..', '*'.

    Non-recursive deletes are only blocked on system dirs and drive roots.
    Paths strictly inside $CLAUDE_PROJECT_DIR are always allowed.
    """
    norm = normalize_path(raw)
    if not norm:
        return False
    root, parts = _split_root(norm)
    while parts and parts[-1] in WILDCARDS:
        parts.pop()  # deleting every child of X is as bad as deleting X

    if root == "":
        return recursive and (not parts or all(p == ".." for p in parts))

    full = (root.rstrip("/") + "/" + "/".join(parts)) if root != "/" else "/" + "/".join(parts)
    project = _project_root()
    if project and root != "~":
        if full.rstrip("/") == project.rstrip("/"):
            return True
        if _inside(full, project):
            return False

    if not parts:
        return True  # '/', drive root, '~'
    top = parts[0]
    if root == "~":
        return recursive and len(parts) <= 1
    if root == "/":
        if top in PROTECTED_POSIX_DIRS:
            return True
        if top in USER_HOME_ROOTS:
            return recursive and len(parts) <= 3
        return recursive and top == "tmp" and len(parts) == 1
    # Windows drive
    if top in PROTECTED_WIN_DIRS:
        return True
    if top == "users":
        return recursive and len(parts) <= 3
    return False


# --------------------------------------------------------------------------- delete commands

def _is_ps_param(tok: str) -> bool:
    return bool(re.match(r"^-[A-Za-z]{2,}(:.*)?$", tok))


def _ps_param(tok: str) -> tuple:
    """'-Recurse:$true' -> ('recurse', '$true')."""
    name, _, value = tok[1:].partition(":")
    return name.lower(), value.lower()


def _ps_is_recurse(tok: str) -> bool:
    if not _is_ps_param(tok) and tok.lower() != "-r":
        return False
    name, value = _ps_param(tok)
    return "recurse".startswith(name) and len(name) >= 1 and value not in {"$false", "false", "0"}


def _parse_remove_item(args: list) -> tuple:
    """Return (recursive, targets) for Remove-Item style arguments."""
    recursive, targets, skip_next = False, [], None
    for tok in args:
        if skip_next is not None:
            if skip_next:
                targets.extend(tok.split(","))
            skip_next = None
            continue
        if tok.startswith("-"):
            name, value = _ps_param(tok)
            if _ps_is_recurse(tok):
                recursive = True
            elif name in {"path", "literalpath", "lp", "pspath"}:
                if value:
                    targets.extend(tok.split(":", 1)[1].split(","))
                else:
                    skip_next = True
            elif name in {"filter", "include", "exclude", "credential", "stream"} and not value:
                skip_next = False
            continue
        targets.extend(t for t in tok.split(",") if t)
    return recursive, targets


def _parse_posix_rm(args: list) -> tuple:
    if any(_is_ps_param(t) and not re.fullmatch(r"-[rRfivdI]+", t) for t in args):
        return _parse_remove_item(args)  # PowerShell `rm` alias
    recursive, targets, after_dd = False, [], False
    for tok in args:
        if not after_dd and tok == "--":
            after_dd = True
            continue
        if not after_dd and tok.startswith("-"):
            if tok == "--recursive" or (not tok.startswith("--") and any(c in tok[1:] for c in "rR")):
                recursive = True
            continue
        targets.append(tok)
    return recursive, targets


def check_delete(tokens: list, piped: bool, via_xargs: bool) -> str | None:
    cmd, args = cmd_name(tokens[0]), tokens[1:]
    if cmd == "rm":
        recursive, targets = _parse_posix_rm(args)
    elif cmd in {"remove-item", "ri"}:
        recursive, targets = _parse_remove_item(args)
    elif cmd in {"rd", "rmdir"}:
        recursive = any(t.lower() in {"/s", "-recurse", "-r"} for t in args)
        targets = [t for t in args if not t.startswith("-") and not re.fullmatch(r"/[a-zA-Z]", t)]
    elif cmd in {"del", "erase"}:
        recursive = any(t.lower() == "/s" for t in args)
        targets = [t for t in args if not t.startswith("-") and not re.fullmatch(r"/[a-zA-Z]", t)]
    else:
        return None

    if recursive and not targets and (piped or via_xargs):
        return f"recursive {tokens[0]} fed by a pipeline/xargs deletes an unknown set of paths."
    for target in targets:
        if is_dangerous_delete_target(target, recursive):
            return (f"dangerous deletion ({tokens[0]} {target}): root, system dir, home, "
                    "project root, '.', '..' or '*'.")
    return None


# --------------------------------------------------------------------------- other checks

def check_secret_access(tokens: list) -> str | None:
    cmd, args = cmd_name(tokens[0]), tokens[1:]
    reads: list = []
    if cmd in READER_CMDS:
        reads = positionals(args)
    elif cmd in PATTERN_CMDS:
        pos = positionals(args)
        explicit_pattern = any(a in {"-e", "-f", "--regexp", "-pattern"} for a in (x.lower() for x in args))
        reads = pos if explicit_pattern else pos[1:]
    elif cmd in COPY_CMDS:
        named = [args[i + 1] for i, a in enumerate(args[:-1]) if a.lower() in {"-path", "-literalpath"}]
        if named:
            reads = named
        else:
            pos = [a for i, a in enumerate(args) if not a.startswith("-")
                   and not (i > 0 and args[i - 1].lower() == "-destination")]
            reads = pos[:-1] if len(pos) > 1 else pos
    elif cmd == "openssl":
        reads = [args[i + 1] for i, a in enumerate(args[:-1]) if a.lower() in OPENSSL_READ_FLAGS]
        reads = [r.split(":", 1)[1] if r.startswith("file:") else r for r in reads]
    for path in reads:
        if is_protected_file(path):
            return f"reading/copying a protected file ({path}). Use the provider's environment variables instead."

    for i, tok in enumerate(tokens):
        m = re.match(r"^\d?(>>?|<)(.*)$", tok)
        if not m:
            continue
        target = m.group(2) or (tokens[i + 1] if i + 1 < len(tokens) else "")
        if target.startswith("&"):
            continue
        if is_protected_file(target):
            verb = "reading" if m.group(1) == "<" else "redirecting output into"
            return f"{verb} a protected file ({target})."
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


def check_supply_chain(tokens: list) -> str | None:
    cmd = cmd_name(tokens[0])
    if cmd in {"pip", "pip3"} and len(tokens) > 1 and tokens[1].lower() == "install":
        return "raw pip install executes arbitrary setup.py scripts. Use 'uv add' / 'uv sync' instead."
    if cmd in {"python", "python3", "py"} and len(tokens) >= 4:
        if tokens[1] == "-m" and tokens[2].lower() == "pip" and tokens[3].lower() == "install":
            return "raw python -m pip install executes arbitrary setup.py scripts. Use 'uv add' / 'uv sync' instead."
    if cmd == "npm" and len(tokens) >= 2 and tokens[1].lower() in {"install", "i"}:
        args = [t for t in tokens[2:] if not t.startswith("-")]
        has_flag = any(t == "--ignore-scripts" for t in tokens[2:])
        if args and not has_flag and not _npmrc_has_ignore_scripts():
            return ("npm install <pkg> without ignore-scripts can run malicious postinstall scripts. "
                    "Add 'ignore-scripts=true' to ~/.npmrc or pass '--ignore-scripts'.")
    return None


def git_subcommand(tokens: list) -> tuple:
    """Skip git global options (-C dir, -c k=v, --git-dir=...) -> (subcommand, args)."""
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in GIT_GLOBAL_VALUE_OPTS:
            i += 2
        elif tok.startswith("-"):
            i += 1
        else:
            return tok.lower(), tokens[i + 1:]
    return "", []


def _short_flags(args: list) -> str:
    return "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))


def check_git(tokens: list) -> str | None:
    if cmd_name(tokens[0]) != "git":
        return None
    sub, args = git_subcommand(tokens)
    flags = _short_flags(args)
    longs = {a.split("=", 1)[0] for a in args if a.startswith("--")}
    pos = positionals(args)

    if sub == "reset" and "--hard" in longs:
        return "git reset --hard destroys uncommitted changes."
    if sub == "clean" and ("f" in flags or "--force" in longs):
        return "git clean -f deletes untracked files."
    if sub == "push":
        if "f" in flags or longs & {"--force", "--force-with-lease"}:
            return "git push --force / --force-with-lease rewrites remote history."
        if any(p.startswith("+") for p in pos):
            return "git push with a '+' force refspec rewrites remote history."
        if "d" in flags or "--delete" in longs or any(p.startswith(":") for p in pos):
            return "git push deleting a remote branch/tag."
    deleting = "d" in flags or "--delete" in longs
    if sub == "branch" and ("D" in flags or (deleting and ("f" in flags or "--force" in longs))):
        return "git branch -D deletes an unmerged branch irrecoverably."
    paths_after_dd = "--" in args and args.index("--") < len(args) - 1
    if sub == "checkout" and (paths_after_dd or any(p in {".", "*", ":/"} for p in pos)):
        return "git checkout of paths discards working-tree changes."
    if sub == "restore":
        staged = "S" in flags or "--staged" in longs
        worktree = "W" in flags or "--worktree" in longs
        if worktree or not staged:
            return "git restore discards working-tree changes."
    if sub == "stash" and pos[:1] and pos[0].lower() in {"drop", "clear"}:
        return "git stash drop/clear deletes stashed work irrecoverably."
    return None


def check_find(tokens: list) -> str | None:
    if cmd_name(tokens[0]) != "find":
        return None
    if "-delete" in tokens:
        return "find ... -delete deletes files in bulk."
    if any(t in {"-exec", "-execdir", "-ok"} for t in tokens) and any(cmd_name(t) in {"rm", "rmdir", "del"} for t in tokens):
        return "find ... -exec rm deletes files in bulk."
    return None


def check_sql(tokens: list, pipeline_has_sql: bool) -> str | None:
    cmd = cmd_name(tokens[0])
    if not (cmd in SQL_CLIENTS or tokens[0].lower() == "drop" or pipeline_has_sql):
        return None
    text = " ".join(tokens)
    if re.search(r"(?i)\bdrop\s+(?:database|table|schema)\b", text):
        return "DROP on a database. Use a manually reviewed migration instead."
    return None


def check_remote_exec(tokens: list, piped_from_download: bool) -> str | None:
    cmd = cmd_name(tokens[0])
    if piped_from_download:
        reads_stdin = cmd in SHELLS or cmd in {"iex", "invoke-expression"} or tokens[1:] in ([], ["-"])
        if cmd in EVALUATORS and reads_stdin:
            return "executing a downloaded script (curl | sh, irm | iex)."
    if cmd in {"iex", "invoke-expression"} and any(cmd_name(t) in DOWNLOADERS for t in tokens[1:]):
        return "executing a downloaded script (Invoke-Expression (Invoke-WebRequest ...))."
    return None


# --------------------------------------------------------------------------- entry points

def check_bash_command(command: str, _depth: int = 0) -> str | None:
    """Return a block reason if a Bash/PowerShell command matches a destructive pattern, else None."""
    # First pass: tokenize and group segments into pipelines (a | b | c).
    pipelines: list = []
    for seg, piped in split_segments(command):
        tokens, via_xargs = strip_wrappers(tokenize(seg))
        if not piped or not pipelines:
            pipelines.append([])
        pipelines[-1].append((tokens, piped, via_xargs))

    parsed = []
    for pipeline in pipelines:
        has_sql = any(t and cmd_name(t[0]) in SQL_CLIENTS for t, _, _ in pipeline)
        downloaded = False
        for tokens, piped, via_xargs in pipeline:
            parsed.append((tokens, piped, via_xargs, downloaded, has_sql))
            if tokens and cmd_name(tokens[0]) in DOWNLOADERS:
                downloaded = True

    for tokens, piped, via_xargs, from_download, pipeline_has_sql in parsed:
        if not tokens:
            continue
        if cmd_name(tokens[0]) in {"sudo", "doas"}:
            return "sudo is not allowed."
        if _depth < MAX_SHELL_DEPTH:
            inline = _inline_script(tokens)
            if inline:
                nested = check_bash_command(inline, _depth + 1)
                if nested:
                    return nested
        reason = (check_remote_exec(tokens, piped and from_download)
                  or check_sql(tokens, pipeline_has_sql)
                  or check_git(tokens)
                  or check_find(tokens)
                  or check_secret_access(tokens)
                  or check_supply_chain(tokens)
                  or check_delete(tokens, piped, via_xargs))
        if reason:
            return reason
    return None


def main() -> None:
    _utf8_stdio()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # unreadable input: do not block

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if is_protected_file(path):
            block(f"writing to a protected file ({path}). Use the provider's environment variables instead.",
                  payload, tool, path)

    if tool == "Read":
        path = tool_input.get("file_path", "") or ""
        if is_protected_file(path):
            block(f"reading a protected secret file ({path}).", payload, tool, path)

    if tool in ("Bash", "PowerShell"):
        cmd = tool_input.get("command", "") or ""
        reason = check_bash_command(cmd)
        if reason:
            block(reason, payload, tool, cmd)

    sys.exit(0)


if __name__ == "__main__":
    main()
