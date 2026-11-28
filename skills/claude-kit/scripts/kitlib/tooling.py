"""Existing-tooling analysis: conflicts between project tools and profile tools, and decisions."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .core import COMMAND_KEYS_NEEDING_VERIFY, DECISION_CHOICES, MAX_MARKER_BYTES, read_json
from .detect import collect_project_files, file_matches
from .settings import _kit_hook_tag


def _word_in(text: str, term: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", text, re.IGNORECASE) is not None


def marker_evidence(project: Path, rel_files: list, marker: dict) -> list:
    """Files matching a marker (and containing its optional text); returns human-readable evidence."""
    needle = marker.get("contains")
    found = []
    for rp in rel_files:
        if not file_matches(rp, marker["file"]):
            continue
        if not needle:
            found.append(rp)
            continue
        try:
            text = (project / rp).read_text(encoding="utf-8", errors="ignore")[:MAX_MARKER_BYTES]
        except OSError:
            continue
        if needle.lower() in text.lower():
            found.append(f"{rp} contains '{needle}'")
        if len(found) >= 3:
            break
    return found[:3]


def foreign_hooks(project: Path) -> list:
    """Hooks declared in the project's settings that were not installed by the kit."""
    found = []
    for name in ("settings.json", "settings.local.json"):
        f = project / ".claude" / name
        if not f.is_file():
            continue
        try:
            data = read_json(f, name, expect=None)
        except SystemExit:
            continue  # unreadable settings are reported by the preflight, not here
        hooks = (data.get("hooks") if isinstance(data, dict) else None) or {}
        for event, groups in hooks.items() if isinstance(hooks, dict) else []:
            for group in groups if isinstance(groups, list) else []:
                group_hooks = group.get("hooks") if isinstance(group, dict) else None
                for hook in group_hooks if isinstance(group_hooks, list) else []:
                    cmd = hook.get("command", "") if isinstance(hook, dict) else ""
                    if isinstance(cmd, str) and cmd and _kit_hook_tag(cmd) is None:
                        found.append({"file": name, "event": event, "command": cmd})
    return found


def normalize_decision(value) -> dict:
    decision = {"choice": value} if isinstance(value, str) else dict(value or {})
    if decision.get("choice") not in DECISION_CHOICES:
        raise SystemExit(f"Invalid decision {value!r}: expected one of {', '.join(DECISION_CHOICES)}")
    return decision


def analyze_tooling(project: Path, profiles: list, decisions: dict) -> list:
    """One entry per tooling concern: what the kit prefers, what the project already uses, and the outcome.

    status: none (kit active/configured) | missing (no tool or config detected, preset available)
            | pending (competing tool, no decision yet: the kit holds back)
            | resolved (user decided) | migration_pending (kit adopted but traces of the old tool remain)
    effective: what the kit actually applies (adopt_kit | keep_existing | keep_both | skip).
    A "missing" concern is withheld (effective skip) until adopt_kit is recorded: the kit never
    puts a command in the lint/verify chain for a tool the project does not have.
    """
    rel_files = collect_project_files(project)
    hooks = foreign_hooks(project)
    results = []
    for p in profiles:
        for item in p.get("tooling", []):
            concern, kit = item["concern"], item["kit"]
            kit_evidence = [e for m in kit.get("markers", []) for e in marker_evidence(project, rel_files, m)]
            has_preset = bool(kit.get("preset_files") or kit.get("install_packages") or kit.get("scripts"))
            only_installed = bool(kit.get("only_when_installed", False))
            existing = []
            for alt in item.get("alternatives", []):
                evidence = [e for m in alt.get("markers", []) for e in marker_evidence(project, rel_files, m)]
                evidence += [f"hook: {h['command']}" for h in hooks
                             if any(_word_in(h["command"], term) for term in alt.get("hooks", []))]
                if evidence:
                    existing.append({"name": alt["name"], "evidence": evidence[:4]})
            recorded = (decisions.get(p["stack"]) or {}).get(concern)
            if not existing:
                if recorded and recorded["choice"] == "skip":
                    status, effective = "resolved", "skip"
                elif not kit_evidence and has_preset:
                    status = "missing"
                    adopted = bool(recorded) and recorded["choice"] in ("adopt_kit", "keep_both")
                    effective = "adopt_kit" if adopted else "skip"
                elif only_installed and not kit_evidence:
                    status, effective = "none", "skip"
                else:
                    status, effective = "none", "adopt_kit"
            elif recorded:
                effective = recorded["choice"]
                status = "migration_pending" if effective == "adopt_kit" else "resolved"
            else:
                status, effective = "pending", "keep_existing"
            results.append({
                "stack": p["stack"], "concern": concern,
                "kit": {"name": kit["name"], "evidence": kit_evidence[:3]},
                "existing": existing, "decision": recorded, "status": status, "effective": effective,
            })
    return results


RUNNER_PLACEHOLDER = "{run}"
_RUNNER_KEYS = ("commands", "verify_steps", "permissions_allow", "format_rules", "lint_rules")


def substitute_runner(obj, runner: str | None):
    """Replace the {run} placeholder in strings (and as a whole argv token) with the runner prefix.

    With no runner the placeholder and the space after it are dropped (bare tool invocation).
    """
    if isinstance(obj, str):
        if RUNNER_PLACEHOLDER not in obj:
            return obj
        return obj.replace(RUNNER_PLACEHOLDER, runner) if runner else re.sub(r"\{run\}\s*", "", obj)
    if isinstance(obj, list):
        out = []
        for x in obj:
            if x == RUNNER_PLACEHOLDER:
                out.extend((runner or "").split())  # argv list: the runner becomes leading tokens
            else:
                out.append(substitute_runner(x, runner))
        return out
    if isinstance(obj, dict):
        return {k: substitute_runner(v, runner) for k, v in obj.items()}
    return obj


def effective_runner(profile: dict, analysis: list) -> str | None:
    """Runner prefix of the package manager in effect (kit's, or the kept alternative's), if any."""
    item = next((i for i in profile.get("tooling", []) if i["concern"] == "package-manager"), None)
    if not item:
        return None
    a = next((x for x in analysis if x["stack"] == profile["stack"] and x["concern"] == "package-manager"), None)
    if a and a["effective"] == "keep_existing" and a["existing"]:
        alt = next((x for x in item.get("alternatives", []) if x["name"] == a["existing"][0]["name"]), None)
        return (alt or {}).get("runner")
    return item["kit"].get("runner")


def effective_profile(profile: dict, analysis: list) -> dict:
    """Profile as it must be applied: tooling decisions taken into account, then {run} resolved."""
    eff = _apply_decisions(profile, analysis)
    if RUNNER_PLACEHOLDER not in json.dumps({k: eff.get(k) for k in _RUNNER_KEYS}):
        return eff
    runner = effective_runner(profile, analysis)
    out = dict(eff)
    for k in _RUNNER_KEYS:
        if k in out:
            out[k] = substitute_runner(out[k], runner)
    return out


def _apply_decisions(profile: dict, analysis: list) -> dict:
    """Profile as it must be applied once tooling decisions are taken into account.

    For every concern kept as-is or skipped: the kit's overlapping commands, formatting rule,
    permissions and practice lines are withheld, and kept tools' known equivalents take their place.
    """
    mine = [a for a in analysis if a["stack"] == profile["stack"]]
    kept = [a for a in mine if a["effective"] == "keep_existing"]
    skipped = [a for a in mine if a["effective"] == "skip"]
    has_lint_checks = any(
        i.get("kit", {}).get("post_edit_check") or any(alt.get("post_edit_check") for alt in i.get("alternatives", []))
        for i in profile.get("tooling", [])
    )
    if not kept and not skipped and not has_lint_checks:
        return profile
    eff = json.loads(json.dumps(profile))
    items = {i["concern"]: i for i in profile.get("tooling", [])}
    eff_map = {a["concern"]: a for a in mine}
    lint_rules = []
    for item in profile.get("tooling", []):
        a = eff_map.get(item["concern"])
        choice = a["effective"] if a else "adopt_kit"
        if choice == "skip":
            continue
        if choice == "keep_existing":
            alt_name = a["existing"][0]["name"] if a and a.get("existing") else None
            alt = next((x for x in item.get("alternatives", []) if x["name"] == alt_name), None)
            if alt and alt.get("post_edit_check"):
                lint_rules.append(alt["post_edit_check"])
        else:
            if item["kit"].get("post_edit_check"):
                lint_rules.append(item["kit"]["post_edit_check"])
    eff["lint_rules"] = lint_rules
    if not kept and not skipped:
        return eff
    withheld_concerns = {a["concern"] for a in kept + skipped}

    owners = {}
    for a in mine:
        for rule in items[a["concern"]]["kit"].get("permissions", []):
            owners.setdefault(rule, set()).add(a["concern"])
    withheld = {rule for rule, who in owners.items() if who <= withheld_concerns}
    eff["permissions_allow"] = [r for r in eff.get("permissions_allow", []) if r not in withheld]

    commands, practices = eff["commands"], eff.get("_practices", "")
    # Process package-manager first so kept formatter/linter rules take precedence over its defaults.
    ordered_kept = sorted(kept, key=lambda a: 0 if a["concern"] == "package-manager" else 1)
    pm_verify_override = False
    keep_notes = []  # appended after the skipped concerns strip their terms, so the notes survive
    for a in ordered_kept:
        item = items[a["concern"]]
        kit = item["kit"]
        alt = next(x for x in item["alternatives"] if x["name"] == a["existing"][0]["name"])
        keys = kit.get("commands", [])
        for key in keys:
            commands[key] = alt.get("commands", {}).get(key)
        if a["concern"] == "package-manager" and alt.get("commands", {}).get("verify"):
            pm_verify_override = True
        if "verify" not in keys and COMMAND_KEYS_NEEDING_VERIFY & set(keys):
            commands["verify"] = None
        if kit.get("format_rules"):
            eff["format_rules"] = [alt["format_rule"]] if alt.get("format_rule") else []
        for rule in alt.get("permissions_allow", []):
            if rule not in eff["permissions_allow"]:
                eff["permissions_allow"].append(rule)
        terms = kit.get("practice_terms", [])
        practices = "\n".join(line for line in practices.splitlines()
                              if not any(_word_in(line, t) for t in terms))
        names = ", ".join(e["name"] for e in a["existing"])
        keep_notes.append(f"- Keep the project's own {a['concern']} ({names}); do not introduce {kit['name']}.")

    for a in skipped:
        item = items[a["concern"]]
        kit = item["kit"]
        keys = kit.get("commands", [])
        for key in keys:
            commands[key] = None
        if "verify" not in keys and COMMAND_KEYS_NEEDING_VERIFY & set(keys):
            commands["verify"] = None
        if kit.get("format_rules"):
            eff["format_rules"] = []
        terms = kit.get("practice_terms", [])
        if terms:
            practices = "\n".join(line for line in practices.splitlines()
                                  if not any(_word_in(line, t) for t in terms))

    practices = "\n".join([practices, *keep_notes]) if keep_notes else practices

    if eff.get("verify_steps"):
        kept_map = {a["concern"]: a for a in ordered_kept}
        step_cmds = []
        for step in eff["verify_steps"]:
            c = step.get("concern")
            cmd_key = step.get("command_key")
            if c is None or c not in withheld_concerns:
                val = commands.get(cmd_key) if cmd_key else step["cmd"]
                if val:
                    step_cmds.append(val)
            elif c in kept_map:
                if cmd_key:
                    val = commands.get(cmd_key)
                else:
                    alt = next(x for x in items[c]["alternatives"] if x["name"] == kept_map[c]["existing"][0]["name"])
                    val = alt.get("commands", {}).get("lint" if c == "linter" else c)
                if val:
                    step_cmds.append(val)
        commands["verify"] = " && ".join(dict.fromkeys(step_cmds)) if step_cmds else None

    eff["_practices"] = practices.strip()
    return eff


def record_decisions(decisions: dict, incoming: dict, analysis: list, report: list) -> None:
    """Merge decisions given by the caller into the stored ones, stamping what was detected at the time."""
    valid = {(a["stack"], a["concern"]): a for a in analysis}
    for stack, concerns in (incoming or {}).items():
        for concern, value in (concerns or {}).items():
            found = valid.get((stack, concern))
            if not found:
                report.append(f"! decision ignored: no tooling concern '{concern}' in profile '{stack}'")
                continue
            decision = normalize_decision(value)
            decision.setdefault("existing", [e["name"] for e in found["existing"]])
            decision.setdefault("date", date.today().isoformat())
            decisions.setdefault(stack, {})[concern] = decision


def tooling_report(analysis: list) -> list:
    lines = []
    for a in analysis:
        label = f"{a['stack']}/{a['concern']}"
        names = ", ".join(e["name"] for e in a["existing"])
        if a["status"] == "pending":
            lines.append(f"! CONFLICT {label}: project uses {names}, the kit prefers {a['kit']['name']}. "
                         f"Kit rules for it are withheld until you decide (keep_existing | adopt_kit | keep_both)")
        elif a["status"] == "migration_pending":
            lines.append(f"! {label}: kit adopted but traces of {names} remain: "
                         + "; ".join(ev for e in a["existing"] for ev in e["evidence"]))
        elif a["status"] == "resolved":
            detail = f" ({names})" if names else ""
            lines.append(f"tooling   {label}: {a['effective']}{detail}, decided {a['decision'].get('date', '?')}")
    return lines
