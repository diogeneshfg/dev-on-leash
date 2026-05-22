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
