---
name: claude-kit-refresh
description: Updates one or more stack profiles in claude-kit by re-reading their official sources and checking for recent changes (new versions, deprecated tools, modified commands). Use when the user types /claude-kit-refresh, or when a profile is flagged as stale.
disable-model-invocation: true
argument-hint: "[stack | all]"
---

# /claude-kit-refresh: keep profiles up to date

Argument: `$ARGUMENTS` = a stack name (e.g., `python`) or `all`. If empty, run `APPLY list` and ask which stack to refresh.

## Step 0: locate the kit

Do Step 0 of `/claude-kit`: `Read` `~/.claude/claude-kit.json` to get `kit_path` (`KIT`) and `python` (`PY`, or a working `python3`/`python`/`py -3`). Then `APPLY` = `PY "KIT/skills/claude-kit/scripts/apply.py"`. Run `APPLY list` to see profiles and their age.

## Step 1: target

- A specific stack: process it.
- `all`: process profiles marked `stale: true` first, then ask about the rest.

## Step 2: check what changed

For each targeted profile:

1. Read `KIT/profiles/<stack>/profile.json`, `practices.md`, and any `versions/*.md` files.
2. Open each URL in `sources` with `WebFetch` and run at least one targeted `WebSearch` for recent changes: new major version, deprecated or replaced tool, changed command or flag, or new practice recommended by official documentation.
3. Compare against the profile. Only keep **sourced** findings: if you cannot find reliable confirmation, do not change anything.

## Step 3: validate, propose, never force

Present a clear line-by-line summary to the user:

- **Added / changed / removed**
- **Why** (in one sentence)
- **Source** (URL)

If nothing changed, say so: the only update is the verification date.

Wait for approval (the user may accept only part of the changes). Then apply the changes to `profile.json` and `practices.md`, set `last_verified` to today's date, add any new sources, and run `APPLY validate --profiles <stack>` to confirm schema and line-limit compliance.

## Step 4: wrap up

- Remind the user to commit the change in the kit repository.
- Clarify that **already-configured projects are not modified automatically**: `/claude-kit sync` refreshes a project's permissions and hooks (backing up existing settings to `.bak`), and re-running `/claude-kit` writes a proposed `CLAUDE.md.proposed` if the generated content changed (never overwriting existing content). `/claude-kit doctor` lists the projects' drift.

## Rules

- Official sources first; a blog post alone is not enough to change a rule.
- `practices.md` stays at 15 lines maximum (and each `versions/*.md` at 8 lines maximum): if you add lines, propose which ones to remove.
- Do not touch profiles other than the targeted ones.
