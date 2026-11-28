"""CI preset: GitHub Actions workflow rendering."""

from __future__ import annotations

import re
from pathlib import Path

from .core import load_kit_json, load_profile, PROFILES
from .detect import detect_matched
from .tooling import analyze_tooling, effective_profile


def _ci_setup_steps(stack: str, install_cmd: str) -> list:
    if stack == "python":
        steps = [
            "      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'",
        ]
        if "uv " in install_cmd:
            steps.append("      - uses: astral-sh/setup-uv@v5")
        return steps
    if stack in ("typescript", "nextjs", "angular"):
        steps = []
        if "pnpm " in install_cmd:
            steps.append("      - uses: pnpm/action-setup@v4\n        with:\n          version: 9")
        steps.append("      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'")
        return steps
    if stack == "csharp-dotnet":
        return ["      - uses: actions/setup-dotnet@v4\n        with:\n          dotnet-version: '9.0.x'"]
    if stack == "rust":
        return ["      - uses: dtolnay/rust-toolchain@stable\n        with:\n          components: clippy, rustfmt"]
    return []


def render_ci_workflow(project: Path) -> str:
    kit_json = load_kit_json(project)
    names = sorted(set(detect_matched(project)) | set(kit_json.get("profiles", {})))
    names = [n for n in names if (PROFILES / n / "profile.json").is_file()]
    raw = [load_profile(n) for n in names]
    analysis = analyze_tooling(project, raw, kit_json.get("decisions", {}))
    effs = [effective_profile(p, analysis) for p in raw]

    lines = [
        "name: CI",
        "",
        "on:",
        "  push:",
        "    branches: [main, master]",
        "  pull_request:",
        "",
        "jobs:",
    ]
    if not effs:
        lines.extend([
            "  verify:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "      - run: echo \"Configure verify command\"",
        ])
        return "\n".join(lines) + "\n"

    for p in effs:
        stack = p["stack"]
        job_id = re.sub(r"[^a-zA-Z0-9_-]", "-", stack)
        cmds = p.get("commands", {})
        install_cmd = cmds.get("install") or ""
        verify_cmd = cmds.get("verify") or cmds.get("lint") or cmds.get("test") or ""
        lines.extend([
            f"  {job_id}:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            *_ci_setup_steps(stack, install_cmd),
        ])
        if install_cmd:
            lines.append(f"      - run: {install_cmd}")
        if verify_cmd:
            lines.append(f"      - run: {verify_cmd}")
    return "\n".join(lines) + "\n"
