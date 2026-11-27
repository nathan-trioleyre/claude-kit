#!/bin/sh
# Portable Python 3 hook launcher for Claude Code (Linux, macOS, Windows Git Bash).
# Invoked via: HOOK_SCRIPT=guard.py; . "$CLAUDE_PROJECT_DIR/.claude/hooks/run-hook.sh"

_hook_script="${HOOK_SCRIPT:-$1}"
_hook_target="$CLAUDE_PROJECT_DIR/.claude/hooks/$_hook_script"

_can_run_python() {
    [ -n "$1" ] && [ -x "$1" ] && "$1" -c "import sys" >/dev/null 2>&1
}

_find_python() {
    # Scan every PATH directory so broken WindowsApps store stubs are skipped
    _old_ifs="$IFS"
    IFS=":"
    for _dir in $PATH; do
        [ -n "$_dir" ] || continue
        for _name in python3 python python3.exe python.exe; do
            _cand="$_dir/$_name"
            if _can_run_python "$_cand"; then
                IFS="$_old_ifs"
                printf '%s' "$_cand"
                return 0
            fi
        done
    done
    IFS="$_old_ifs"

    # Fall back to the Python executable recorded by install.py
    for _cfg in "$HOME/.claude/claude-kit.json" "$HOME/.claude/claude-bootstrap.json"; do
        if [ -f "$_cfg" ]; then
            _saved=$(sed -n 's/.*"python"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$_cfg" | head -n 1 | sed 's/\\\\/\\/g')
            if [ -n "$_saved" ] && command -v cygpath >/dev/null 2>&1; then
                _saved=$(cygpath -u "$_saved" 2>/dev/null || printf '%s' "$_saved")
            fi
            if [ -n "$_saved" ] && "$_saved" -c "import sys" >/dev/null 2>&1; then
                printf '%s' "$_saved"
                return 0
            fi
        fi
    done
    return 1
}

if _py_bin=$(_find_python); then
    exec "$_py_bin" "$_hook_target"
fi

if command -v py >/dev/null 2>&1 && py -3 -c "import sys" >/dev/null 2>&1; then
    exec py -3 "$_hook_target"
fi

if [ "$_hook_script" = "guard.py" ]; then
    echo "BLOCKED: Python 3.9+ not found; guard.py could not run." >&2
    exit 2
fi
exit 0
