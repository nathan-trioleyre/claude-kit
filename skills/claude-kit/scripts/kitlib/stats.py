"""`stats`: session token/cost usage and harness block summaries from .claude/logs/."""

import json
from pathlib import Path

from .core import HARNESS_RECURRING_THRESHOLD


def _read_harness_stats(project: Path) -> dict:
    harness_log = project / ".claude" / "logs" / "harness.log"
    counts: dict[str, int] = {}
    by_hook: dict[str, int] = {}
    total_blocks = 0
    if harness_log.is_file():
        for line in harness_log.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            total_blocks += 1
            hook = entry.get("hook", "hook")
            by_hook[hook] = by_hook.get(hook, 0) + 1
            key = f"{hook}: {entry.get('target', '')}" if hook == "verify-stop" else f"{hook}: {entry.get('reason', '')}"
            counts[key] = counts.get(key, 0) + 1
    top_blocks = [{"key": k, "count": c} for k, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    recurring = [r for r in top_blocks if r["count"] >= HARNESS_RECURRING_THRESHOLD]
    return {"total_blocks": total_blocks, "by_hook": by_hook, "top_blocks": top_blocks[:10], "recurring": recurring}


def _read_session_stats(project: Path) -> dict:
    sessions_log = project / ".claude" / "logs" / "sessions.jsonl"
    out = {"count": 0, "input_tokens": 0, "output_tokens": 0,
           "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "cost_usd": 0.0}
    if sessions_log.is_file():
        for line in sessions_log.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out["count"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                out[k] += int(rec.get(k, 0) or 0)
            out["cost_usd"] += float(rec.get("cost_usd", 0.0) or 0.0)
    out["cost_usd"] = round(out["cost_usd"], 6)
    return out


def cmd_stats(args) -> None:
    project = Path(args.project).resolve()
    sessions = _read_session_stats(project)
    harness = _read_harness_stats(project)
    data = {"sessions": sessions, "harness": harness}
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if sessions["count"] == 0 and harness["total_blocks"] == 0:
        print("No session or harness logs recorded yet.")
        return
    lines = [
        f"Sessions : {sessions['count']} | input={sessions['input_tokens']} | output={sessions['output_tokens']} | cost=${sessions['cost_usd']:.4f}",
        f"Harness  : {harness['total_blocks']} block(s) ({', '.join(f'{k}={v}' for k, v in sorted(harness['by_hook'].items())) or 'none'})",
    ]
    for b in harness["top_blocks"][:5]:
        flag = " [RECURRING]" if b["count"] >= HARNESS_RECURRING_THRESHOLD else ""
        lines.append(f"  - {b['count']}x {b['key']}{flag}")
    print("\n".join(lines))
