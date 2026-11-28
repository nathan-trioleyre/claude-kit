#!/usr/bin/env python3
"""Stop hook: runs the project's verify command before Claude finishes a turn.
# claude-devkit-hook-version: 5

Active by default whenever `.claude/kit.json` defines a non-empty `"verify_command"`
and `"stop_verify"` is not explicitly `false` (opt-out). Exits immediately (0) otherwise.

Safety guards:
- Checks `stop_hook_active` in stdin JSON to prevent infinite retry loops.
- Skips when the git working tree has no uncommitted changes.
- Records session token/cost metrics from `transcript_path` into `.claude/logs/sessions.jsonl`.
- On failure, truncates output to the last 50 lines, logs to `.claude/logs/harness.log`,
  and exits 2 so Claude fixes it.
"""
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
from pathlib import Path


def log_block(project: Path, verify_cmd: str, reason: str) -> None:
    try:
        claude_dir = project / ".claude"
        if not claude_dir.is_dir():
            return
        log_dir = claude_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "hook": "verify-stop",
            "tool": "Stop",
            "target": verify_cmd[:200],
            "reason": reason,
        }
        with (log_dir / "harness.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def record_session_usage(project: Path, payload: dict) -> None:
    """Summarize token/cost usage from Claude Code's transcript_path into .claude/logs/sessions.jsonl."""
    try:
        claude_dir = project / ".claude"
        transcript_raw = payload.get("transcript_path")
        if not claude_dir.is_dir() or not transcript_raw:
            return
        transcript = Path(transcript_raw)
        if not transcript.is_file():
            return
        totals = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        cost_usd = 0.0
        for line in transcript.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if isinstance(usage, dict):
                for key in totals:
                    val = usage.get(key)
                    if isinstance(val, (int, float)):
                        totals[key] += int(val)
            for ckey in ("costUSD", "total_cost_usd"):
                cval = rec.get(ckey)
                if isinstance(cval, (int, float)):
                    cost_usd += float(cval)
        if not any(totals.values()) and cost_usd == 0.0:
            return
        log_dir = claude_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        session_id = str(payload.get("session_id") or transcript.stem)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            **totals,
            "cost_usd": round(cost_usd, 6),
        }
        sessions_file = log_dir / "sessions.jsonl"
        existing = []
        if sessions_file.is_file():
            for raw_l in sessions_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not raw_l.strip():
                    continue
                try:
                    prev = json.loads(raw_l)
                    if prev.get("session_id") != session_id:
                        existing.append(raw_l)
                except json.JSONDecodeError:
                    continue
        existing.append(json.dumps(entry, ensure_ascii=False))
        sessions_file.write_text("\n".join(existing) + "\n", encoding="utf-8")
    except Exception:
        pass


def has_git_changes(project: Path) -> bool:
    """Return True if git reports modified/untracked files, or if git is unavailable."""
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        if res.returncode == 0:
            return bool(res.stdout.strip())
    except Exception:
        pass
    return True


def _utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> int:
    _utf8_stdio()
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("stop_hook_active"):
        return 0

    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ".")
    record_session_usage(project, payload)
    kit_file = project / ".claude" / "kit.json"
    if not kit_file.is_file():
        return 0

    try:
        kit_data = json.loads(kit_file.read_text(encoding="utf-8"))
    except Exception:
        return 0

    if kit_data.get("stop_verify") is False:
        return 0  # explicit opt-out

    verify_cmd = (kit_data.get("verify_command") or "").strip()
    if not verify_cmd:
        return 0

    if not has_git_changes(project):
        return 0

    try:
        res = subprocess.run(
            verify_cmd,
            shell=True,
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=110,
        )
    except subprocess.TimeoutExpired:
        log_block(project, verify_cmd, "timeout")
        print(f"BLOCKED: verify command timed out: {verify_cmd}", file=sys.stderr)
        return 2

    if res.returncode != 0:
        output = "\n".join(line for line in ((res.stdout or "") + "\n" + (res.stderr or "")).splitlines()[-50:])
        log_block(project, verify_cmd, f"exit {res.returncode}")
        print(f"BLOCKED: '{verify_cmd}' failed (exit {res.returncode}). Fix before concluding:\n{output}",
              file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
