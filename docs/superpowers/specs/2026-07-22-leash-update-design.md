# `/leash-update` — Automatic Update Detection, One-Command Apply

**Status:** approved (brainstorm complete)
**Date:** 2026-07-22
**Project:** dev-on-leash

## Problem

A bootstrapped project carries a *copy* of the project-agnostic layer
(`scripts/harness/`, `docs/task-schema.md`, `docs/plan-template.md`, the
opt-in pre-commit hook) plus hook wiring in `.claude/settings.json`. The
init scripts deliberately never clobber existing files, so none of this
updates when the plugin does. Skills and agents auto-update with the
plugin cache; the copied layer silently rots — e.g. no existing project
received the `session_root_guard` SessionStart hook. There is no version
marker in consumer projects, so they cannot even know they are stale.

## Decisions locked during brainstorm

1. **Warn + one command** (not fully automatic, not zero-copy). Detection
   is automatic at SessionStart; applying is a deliberate `/leash-update`.
   Nothing in the repo changes without the user seeing it.
2. **Detect local edits and refuse.** A hash manifest distinguishes
   "intact copy" from "locally edited"; edited files are refused with a
   diff, overridable per file with `--force`. `CLAUDE.md`/`AGENTS.md` are
   never touched.

## Section 1 — Version stamp + manifest: `.harness/leash.json`

Committed in the consumer project. Written by init and by every update:

```json
{
  "schema": 1,
  "version": "0.6.0",
  "files": { "scripts/harness/session_gate.py": "<sha256>", ... }
}
```

Hashes are of the files *as copied by the plugin*, so local edits remain
detectable forever. Refused (locally edited) files keep their old manifest
entry so the next run still flags them.

## Section 2 — Detection: plugin-level SessionStart hook

The check ships in the **plugin's own** `hooks/hooks.json` (plugins'
hooks run in every project where the plugin is enabled, with
`${CLAUDE_PLUGIN_ROOT}` available):

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/update_check.py"
```

`update_check.py` (stdlib-only, self-contained, fail-silent):

- Resolve the session cwd from the hook payload (BOM-tolerant JSON parse;
  fall back to `os.getcwd()`).
- No `.harness/` directory in cwd → exit silently (not a leashed repo).
- Cwd contains `.claude-plugin/plugin.json` → exit silently (it *is* the
  plugin repo; dogfood guard).
- Compare `.harness/leash.json` version with the plugin's
  `.claude-plugin/plugin.json` version. Different or missing manifest →
  print one warning line naming both versions and `/leash-update`.

This solves the chicken-and-egg: the detector arrives with the plugin
update, without touching any project first, and nudges pre-manifest
projects on their next session.

## Section 3 — Apply: `leash-update` skill + `scripts/leash_update.py`

One cross-platform Python implementation (invoked as
`python "${CLAUDE_PLUGIN_ROOT}/scripts/leash_update.py" <target>`)
instead of duplicated `update.ps1`/`update.sh` — hashing, diffing and
JSON merging in two shell dialects is where bugs live. Python is already
a hard requirement of the harness. The skill is a thin wrapper that runs
the script and relays its report.

**Managed set** (plugin path → target path):

- `scripts/harness/*` → `scripts/harness/*`
- `templates/task-schema.md` → `docs/task-schema.md`
- `templates/plan-template.md` → `docs/plan-template.md`
- `templates/hooks/pre-commit` → `.harness/hooks/pre-commit`

**Per-file decision:**

| target state | manifest entry | action |
|---|---|---|
| missing | any | copy → **added** |
| hash == manifest | present | copy new version → **updated** (or **unchanged** if identical) |
| hash != manifest | present | **refused** + unified diff; `--force <relpath>` overwrites |
| — | absent (pre-manifest project) | identical to plugin's current file → **unchanged**; else **refused** (conservative) |

**`.claude/settings.json` merge — additive only.** The updater owns a
`REQUIRED_HOOKS` list of `(event, matcher, command)` tuples — the single
source of truth for hook wiring; a test asserts `settings.json.tmpl`
agrees with it. For each required hook missing from the project's
settings (matched by command string), append it. Never remove, reorder,
or rewrite user entries or permissions.

**Never touched:** `CLAUDE.md`, `AGENTS.md`, `.harness/gates`,
`docs/plans/`. The final report points at the plugin CHANGELOG entries
between the two versions for anything worth porting by hand.

**Finish:** write the new `leash.json` (refused files keep old hashes),
print a summary: updated / added / unchanged / refused / hooks added.

**`--init-manifest` mode:** writes `leash.json` for an already-copied
tree without changing any file. The init scripts (`init.ps1`/`init.sh`)
call it as their final step so fresh bootstraps are born stamped.

## Section 4 — Testing, dogfood, docs

- **Unit tests (TDD):** decision matrix of Section 3 (added / updated /
  refused / unchanged / no-manifest cases), settings merge (missing hook
  added; existing entries untouched; idempotent), manifest read/write,
  `update_check` (silent on non-leashed cwd, silent on plugin repo, warns
  on version mismatch and on missing manifest), template↔`REQUIRED_HOOKS`
  agreement.
- **Dogfood (load-bearing):** `scripts/dogfood_leash_update.py` builds a
  temp fixture project (old harness copy + manifest), plants one local
  edit, runs the real updater: asserts the edited file is refused with a
  diff, everything else updates, the missing SessionStart hook is merged
  into settings.json, and a second run reports all-unchanged. Wired into
  `scripts/smoke_e2e.py`.
- **Docs:** README gains an "Updating" section; CHANGELOG entry;
  bootstrap skill documents the manifest step.

## Non-goals

- Auto-applying updates (decision 1).
- Updating `CLAUDE.md`/`AGENTS.md` content (report-only).
- Three-way merges of locally edited harness files (`--force` or manual).
- Version-range migrations (each update jumps straight to the installed
  plugin version; the CHANGELOG pointer covers behavioral notes).
