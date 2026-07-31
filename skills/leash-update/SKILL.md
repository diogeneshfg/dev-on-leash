---
name: leash-update
description: Use to update the dev-on-leash layer of an already-bootstrapped project — "update the harness", "leash update", or after the SessionStart warning that the harness is stale. Overwrites intact copies, refuses locally edited files with a diff, and additively merges missing hook wiring into .claude/settings.json.
---

# leash-update

## When to use

A SessionStart warning said this project's harness is older than the
installed plugin, or you know the plugin was updated. Runs inside a
bootstrapped target project (it needs `.harness/`).

## How

1. Run, from the project root:

   ```
   python "${CLAUDE_PLUGIN_ROOT}/scripts/leash_update.py" .
   ```

2. Read the report to the user: which files were `updated`/`added`,
   which were `refused` (locally edited — show the diff), and which hook
   entries were merged into `.claude/settings.json`.

3. For each refused file, let the user decide: keep the local edit, or
   rerun with `--force <relpath>` to overwrite that one file.

4. Point at the plugin CHANGELOG entries between the old and new version
   for guidance worth porting into `CLAUDE.md`/`AGENTS.md` by hand —
   the updater never touches those two files.

5. Remind the user to review `git diff` and commit the update.

## Constraints

- Additive only on `.claude/settings.json`; never removes or reorders
  user entries. Unparseable settings are left alone.
- Never touches `CLAUDE.md`, `AGENTS.md`, `.harness/gates`, `docs/plans/`.
- Refusal is the default for any divergent file; `--force` is per-file
  and deliberate. (`--init-manifest` exists for the init scripts, not
  for this flow.)

## 0.7.0 notes

This release delivers `scripts/harness/repo_resolve.py` (picked up by the
existing `scripts/harness/*.py` glob) and the rewritten `session_gate.py` with
multi-repo and branch-mode support. The `workflow: branch` config key requires
the updated harness — run `/leash-update` BEFORE adding `workflow:` to
`.harness/branches.yaml`.
