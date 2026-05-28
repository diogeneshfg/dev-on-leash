# Follow-ups

Known limitations and deferred work, kept here so they are not forgotten.

## touches-integrity checking

`task-meta`'s `touches` list is self-reported. The harness does not verify
that a task modified *only* its declared files, so `plan_schedule.py`'s
parallel-safety guarantee depends on `touches` being accurate.

A check would compare `git diff --name-only` after a task against its declared
`touches`. Doing that without false positives from unrelated concurrent work
in the diff needs its own design. Deferred from the 2026-05-22
harness-hardening effort (see `docs/plans/harness-hardening.md`).

## session-leash per-session bypass

The session-leash spec (`docs/superpowers/specs/2026-05-28-session-leash-design.md`
Section 6) calls for a `bypass: true` lockfile field, settable by passing
`--force` to `python -m scripts.harness.session_start`, with an audit line
appended to `.harness/exceptions.log` — mirroring the `cycle_done --force`
escape hatch.

v1 ships without this. A user who really needs to bypass the gate must
remove the `SessionStart` / `PreToolUse` entries from
`.claude/settings.json`, which is a visible git change. Adding the
`--force` path is a small additive change post-v1; do it the first time
someone reports a legitimate need for a one-off bypass.

## architecture-leash drift detection in cycle_done

Spec for architecture-leash flagged "drift detection in `cycle_done`
(assert generated files still match the YAML)" as a v1 non-goal. Still
worth doing — would catch a hand-edited `.harness/checks/*.py` or
`importlinter.ini` that no longer matches the declared architecture.
