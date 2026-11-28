#!/usr/bin/env python3
"""apply.py: the MECHANICAL part of /claude-kit (what must stay deterministic).

Subcommands:
  list      lists known stack profiles in the kit, along with their age
  detect    detects which known profiles match a project
  apply     generates/merges Claude config into a project (first setup or full re-run)
  sync      re-applies only the kit-managed parts (settings, hooks, kit.json, org extras)
            to an already configured project, using the profiles recorded in kit.json
  doctor    reports drift between a project and the current kit (exit 1 if issues)
  audit     inventories what a project already has (CLAUDE.md, hooks, tooling) and lists
            conflicts between the project's tools and the kit's (JSON on stdout, read-only)
  decide    records how a tooling conflict is resolved (keep_existing | adopt_kit | keep_both | skip)
  uninstall removes what the kit added (unmodified managed files, kit hooks/permissions, ignore
            lines, kit.json); never deletes CLAUDE.md / rules files (--dry-run to preview)
  validate  validates profile.json schema and practices.md constraints
  scaffold-tooling  scaffolds missing linter/formatter preset files non-destructively
  codemap   generates a compact project codemap
  stats     summarizes session tokens/costs and harness blocks

This file is only the CLI entry point; the logic lives in the sibling `kitlib/` package
(core, validate, detect, settings, preflight, ignore, tooling, render, codemap, stats, ci,
scaffold, project, doctor, audit, uninstall).

Layers (later layers add to earlier ones, never remove): base -> org -> stack profiles -> project.

Safety rules:
  - an existing CLAUDE.md or .claude/rules/<stack>.md is never overwritten (.proposed)
  - existing settings.json: additive merge (legacy kit hooks upgraded safely), previous version
    saved as settings.json.bak; every JSON input is validated before anything is written
  - tooling the project lacks (no ruff in a Python project...) is withheld from commands and the
    Stop-hook verify chain until adopt_kit is recorded
  - a hook file is upgraded only if it is unmodified since the kit installed it
  - a tool the project already uses (e.g. black vs the kit's ruff) is never overridden silently:
    until a decision is recorded, the kit withholds its overlapping rules
  - --dry-run writes nothing

No external dependencies: Python 3.9+ is sufficient.
"""

from __future__ import annotations

import argparse
import sys

from kitlib.core import DECISION_CHOICES
from kitlib.validate import cmd_list, cmd_validate
from kitlib.detect import cmd_detect
from kitlib.codemap import cmd_codemap
from kitlib.stats import cmd_stats
from kitlib.scaffold import cmd_scaffold_tooling
from kitlib.project import cmd_apply, cmd_decide, cmd_sync
from kitlib.doctor import cmd_doctor
from kitlib.audit import cmd_audit
from kitlib.uninstall import cmd_uninstall


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list kit profiles").set_defaults(func=cmd_list)

    p_detect = sub.add_parser("detect", help="detect known profiles in a project")
    p_detect.add_argument("--project", default=".")
    p_detect.set_defaults(func=cmd_detect)

    p_validate = sub.add_parser("validate", help="validate profile schemas and practices.md")
    p_validate.add_argument("--profiles", nargs="*", default=[], help="specific stacks to validate (default: all)")
    p_validate.set_defaults(func=cmd_validate)

    for name, func, help_text in (("apply", cmd_apply, "generate config in a project"),
                                  ("sync", cmd_sync, "refresh kit-managed files of a configured project")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--project", default=".")
        sp.add_argument("--profiles", nargs="*", default=[], help="stack names (e.g., python angular)")
        sp.add_argument("--dry-run", action="store_true")
        sp.add_argument("--force-hooks", action="store_true", help="overwrite hooks even if modified locally")
        sp.add_argument("--no-org", action="store_true", help="ignore the optional org/ layer")
        sp.add_argument("--local", action="store_true", help="local/stealth mode: CLAUDE.local.md, settings.local.json, .git/info/exclude (never touches .gitignore or team CLAUDE.md)")
        if name == "apply":
            sp.add_argument("--context", help="JSON path or '-' for stdin: name, description, architecture, gotchas, commands_override, rule_paths")
        sp.set_defaults(func=func)

    p_doctor = sub.add_parser("doctor", help="report drift between a project and the kit")
    p_doctor.add_argument("--project", default=".")
    p_doctor.add_argument("--no-org", action="store_true")
    p_doctor.set_defaults(func=cmd_doctor)

    p_audit = sub.add_parser("audit", help="inventory existing project config and tooling conflicts (JSON)")
    p_audit.add_argument("--project", default=".")
    p_audit.add_argument("--profiles", nargs="*", default=[], help="stacks to audit (default: detected + configured)")
    p_audit.add_argument("--no-org", action="store_true")
    p_audit.set_defaults(func=cmd_audit)

    p_decide = sub.add_parser("decide", help="record how a tooling conflict is resolved")
    p_decide.add_argument("--project", default=".")
    p_decide.add_argument("--profile", required=True)
    p_decide.add_argument("--concern", required=True)
    p_decide.add_argument("--choice", required=True, choices=DECISION_CHOICES)
    p_decide.add_argument("--dry-run", action="store_true")
    p_decide.set_defaults(func=cmd_decide)

    p_uninstall = sub.add_parser("uninstall", help="remove what the kit added to a project (keeps CLAUDE.md and modified files)")
    p_uninstall.add_argument("--project", default=".")
    p_uninstall.add_argument("--dry-run", action="store_true")
    p_uninstall.set_defaults(func=cmd_uninstall)

    p_scaffold = sub.add_parser("scaffold-tooling", help="scaffold missing linter/formatter preset files non-destructively")
    p_scaffold.add_argument("--project", default=".")
    p_scaffold.add_argument("--profile")
    p_scaffold.add_argument("--concern")
    p_scaffold.add_argument("--base-preset", choices=["editorconfig", "pre-commit", "ci"])
    p_scaffold.add_argument("--dry-run", action="store_true")
    p_scaffold.add_argument("--local", action="store_true")
    p_scaffold.set_defaults(func=cmd_scaffold_tooling)

    p_codemap = sub.add_parser("codemap", help="generate a compact project codemap")
    p_codemap.add_argument("--project", default=".")
    p_codemap.add_argument("--write", action="store_true", help="write .claude/codemap.md")
    p_codemap.add_argument("--dry-run", action="store_true")
    p_codemap.set_defaults(func=cmd_codemap)

    p_stats = sub.add_parser("stats", help="summarize session tokens/costs and harness blocks")
    p_stats.add_argument("--project", default=".")
    p_stats.add_argument("--json", action="store_true")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
