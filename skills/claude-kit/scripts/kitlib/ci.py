"""CI preset: GitHub Actions or GitLab CI rendering."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .core import load_kit_json, load_profile, PROFILES
from .detect import detect_matched
from .tooling import analyze_tooling, effective_profile

CI_PROVIDERS = ("github", "gitlab")
CI_DESTS = {"github": ".github/workflows/ci.yml", "gitlab": ".gitlab-ci.yml"}
NODE_STACKS = ("typescript", "nextjs", "angular", "react-vite", "vue")
# Pinned as golangci-lint recommends; the Docker image of this tag ships the Go toolchain.
GOLANGCI_LINT_VERSION = "v2.15.0"


def _origin_url(project: Path) -> str:
    try:
        res = subprocess.run(["git", "-C", str(project), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


def detect_ci_provider(project: Path) -> str:
    """Existing CI config wins, then the origin remote host; GitHub by default."""
    if (project / ".gitlab-ci.yml").exists():
        return "gitlab"
    if (project / ".github" / "workflows").is_dir():
        return "github"
    return "gitlab" if "gitlab" in _origin_url(project).lower() else "github"


def _active_profiles(project: Path) -> list:
    kit_json = load_kit_json(project)
    names = sorted(set(detect_matched(project)) | set(kit_json.get("profiles", {})))
    names = [n for n in names if (PROFILES / n / "profile.json").is_file()]
    raw = [load_profile(n) for n in names]
    analysis = analyze_tooling(project, raw, kit_json.get("decisions", {}))
    return [effective_profile(p, analysis) for p in raw]


def _job_commands(p: dict) -> tuple:
    cmds = p.get("commands", {})
    install_cmd = cmds.get("install") or ""
    verify_cmd = cmds.get("verify") or cmds.get("lint") or cmds.get("test") or ""
    return install_cmd, verify_cmd


def _job_id(stack: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", stack)


def render_ci(project: Path, provider: str) -> str:
    if provider == "gitlab":
        return render_gitlab_ci(project)
    return render_ci_workflow(project)


# --- GitHub Actions ---------------------------------------------------------

def _ci_setup_steps(stack: str, install_cmd: str, verify_cmd: str = "") -> list:
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
    if stack == "go":
        steps = ["      - uses: actions/setup-go@v5\n        with:\n          go-version-file: go.mod"]
        if "golangci-lint" in verify_cmd:
            steps.append(
                "      - uses: golangci/golangci-lint-action@v9\n        with:\n"
                f"          version: {GOLANGCI_LINT_VERSION}\n          install-only: true"
            )
        return steps
    return []


def render_ci_workflow(project: Path) -> str:
    effs = _active_profiles(project)
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
        install_cmd, verify_cmd = _job_commands(p)
        lines.extend([
            f"  {_job_id(stack)}:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: actions/checkout@v4",
            *_ci_setup_steps(stack, install_cmd, verify_cmd),
        ])
        if install_cmd:
            lines.append(f"      - run: {install_cmd}")
        if verify_cmd:
            lines.append(f"      - run: {verify_cmd}")
    return "\n".join(lines) + "\n"


# --- GitLab CI --------------------------------------------------------------

def _yaml_scalar(cmd: str) -> str:
    """Quote a shell command when plain YAML would misparse it."""
    if ": " in cmd or " #" in cmd or cmd[:1] in "!&*{}[]|>'\"%@`,?-#":
        return "'" + cmd.replace("'", "''") + "'"
    return cmd


def _gitlab_image_and_setup(stack: str, install_cmd: str, verify_cmd: str = "") -> tuple:
    tool = install_cmd.split(" ", 1)[0]
    if stack == "python":
        setup = [f"pip install {tool}"] if tool in ("uv", "poetry", "pdm", "pipenv") else []
        return "python:3.12", setup
    if stack in NODE_STACKS:
        if tool in ("pnpm", "yarn"):
            return "node:22", ["corepack enable"]
        if tool == "bun":
            return "node:22", ["npm install -g bun"]
        return "node:22", []
    if stack == "csharp-dotnet":
        return "mcr.microsoft.com/dotnet/sdk:9.0", []
    if stack == "rust":
        return "rust:1", ["rustup component add clippy rustfmt"]
    if stack == "go":
        if "golangci-lint" in verify_cmd:
            return f"golangci/golangci-lint:{GOLANGCI_LINT_VERSION}", []
        return "golang:1", []
    if stack == "java-spring":
        return "eclipse-temurin:21", []
    if stack == "php":
        return "composer:2", []
    return "ubuntu:24.04", []


def render_gitlab_ci(project: Path) -> str:
    lines = [
        "workflow:",
        "  rules:",
        "    - if: $CI_PIPELINE_SOURCE == \"merge_request_event\"",
        "    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS",
        "      when: never",
        "    - if: $CI_COMMIT_BRANCH",
        "",
        "stages:",
        "  - verify",
    ]
    jobs = []
    for p in _active_profiles(project):
        install_cmd, verify_cmd = _job_commands(p)
        if not (install_cmd or verify_cmd):
            continue
        image, setup = _gitlab_image_and_setup(p["stack"], install_cmd, verify_cmd)
        script = setup + [c for c in (install_cmd, verify_cmd) if c]
        jobs.append((_job_id(p["stack"]), image, script))
    if not jobs:
        jobs.append(("verify", "ubuntu:24.04", ["echo \"Configure verify command\""]))

    for job_id, image, script in jobs:
        lines.extend(["", f"{job_id}:", "  stage: verify", f"  image: {image}", "  script:"])
        lines.extend(f"    - {_yaml_scalar(c)}" for c in script)
    return "\n".join(lines) + "\n"
