# Design: harness-hardening

Date: 2026-05-22
Status: approved (brainstorming)

## Problem

A fresh review of `dev-on-leash` surfaced three classes of issue:

1. **Parser inconsistency / fragility.** `schema.py` matches task headings as
   `^###\s+Task` while `run_task.py` matches `^##+\s+Task`, yet the schema doc
   (`templates/task-schema.md`) says both `## Task` and `### Task` are valid.
   Consequence: for an H2-headed task the "missing task-meta" guard in
   `parse_plan` is effectively dead code (`len(blocks) < 0` never trips).
   Heading↔block association is implicit (separate `findall`s, paired only by
   a count check), and `run_task` locates a task by scanning for the literal
   substring `id: T01`, which can false-match prose.

2. **The discipline is advisory, not enforced.** The pitch is "keeps AI-driven
   development on guardrails," but nothing prevents an agent or human from
   editing a plan to tick `- [ ]` → `- [x]` directly, bypassing `run_task.py`
   and its verify gate. The guardrail is a polite request in a skill file.

3. **Framing oversells the artifact.** README language ("proven internal
   harness", "keeps AI-driven development on guardrails") promises a control
   system; the tool is a competent plan-runner. `plugin.json` says version
   `0.2.0`, `pyproject.toml` says `0.1.0`.

## Goal

Make the discipline enforceable, fix the parser inconsistencies with a single
coherent model, and make the documentation describe what the tool actually
does. Deliver the work as a `dev-on-leash` plan — dogfooding the harness.

## Non-goals

- **`touches`-integrity checking is deferred.** Verifying that a task only
  modified its declared `touches` files, without false positives from
  concurrent work in the git diff, needs its own design. It is logged here as
  a known limitation and a follow-up, not built in this effort.
- No change to the `task-meta` schema fields.
- `--force` on `cycle_done` is kept as-is (emergency bypass with audit log);
  it is documented, not removed.

## Design

### 1. Region-based plan model

Replace the implicit heading/block pairing with one explicit model used by
every consumer.

A single function walks the plan once (after `_strip_fenced_blocks`) and
produces a list of **regions**. A region begins at a `## ` or `### Task`
heading and runs until the next such heading (or EOF). Each region carries:
its heading line index, its end line index, and the `TaskMeta` parsed from the
**exactly one** `task-meta` block inside it.

Validation rules:
- A region with **two or more** `task-meta` blocks is a `SchemaError`.
- A region with **zero** blocks is a valid **human-run task** — allowed,
  returned with `meta = None`, consistent with `task-schema.md` ("a task
  without one is human-run and ignored by the harness"). This also corrects
  an existing contradiction: `parse_plan`'s H3-only regex makes a bare H3
  task heading error, while `validate_plan` only *warns* for the same case.
  The test `test_rejects_task_without_meta` is updated to assert the
  documented lenient behavior.
- A `task-meta` block that sits outside every region is a `SchemaError`.
- Existing rules (id format, non-empty `touches`, unknown `depends`, duplicate
  ids, dependency cycles) are preserved.

Consumers:
- `parse_plan` returns `list[TaskMeta]` as before (back-compatible) but is now
  built on the region walker.
- `run_task.py` ticks the first `- [ ]` checkbox **inside the region bound to
  the requested id** — no substring `id: T01` scan, no false matches.
- `recheck_plan.py` (below) reuses the same regions to find ticked tasks.

Heading recognition is unified to `^##+\s+Task\b` (H2 or H3) everywhere,
matching the schema doc.

### 2. Enforcement — `recheck_plan.py`

A new harness script: `scripts/harness/recheck_plan.py <plan.md>`.

For every region whose **first checkbox is `- [x]`** (i.e. the task is marked
done), re-run that task's `verify` command from the repo root. Report each
result. Exit `0` only if every ticked task re-verifies; exit `1` if any ticked
task's verify fails; exit `2` on usage error.

Why this works as enforcement: a box ticked without the work actually done
fails its own `verify`. There is no marker to forge and no local state to
trust — the plan file plus the source tree are the only inputs. A box ticked
*and* legitimately done re-verifies fine, so honest manual ticks are not
punished; only dishonest ones are caught.

### 3. Wiring

**CI (plugin's own repo).** `scripts/smoke_e2e.py` gains a step: after the
normal green run, it hand-ticks a not-done task's checkbox directly in the
plan text and asserts `recheck_plan.py` **rejects** it (exit 1). This proves
the enforcement on every push, in the plugin's own CI, without needing real
plans in the plugin repo.

**CI (adopting projects).** A documented snippet (in README / bootstrap
output) shows adopters how to add `python scripts/harness/recheck_plan.py
docs/plans/*.md` to their own CI.

**Opt-in pre-commit hook.** `templates/hooks/pre-commit` runs `recheck_plan.py`
on staged plan files and blocks the commit on failure. `init.sh` / `init.ps1`
**copy** the hook file into the target repo (into a tracked location such as
`.harness/hooks/`) but do **not** activate it. The `bootstrap-dev-leash` skill
asks the user whether to install it into `.git/hooks/`; "opt-in" means no hook
runs unless the user said yes.

### 4. Honest framing

- **README:** remove "proven internal harness" and "keeps AI-driven
  development on guardrails". Add a **Trust model** section stating plainly:
  - *Enforced:* every ticked task is independently re-verifiable
    (`recheck_plan.py`, run in CI and/or the pre-commit hook).
  - *By convention only:* `touches` is self-reported and unverified (parallel
    safety depends on it being accurate — follow-up planned); `cycle_done
    --force` bypasses failing gates and logs an audit entry.
- **`plugin.json`:** description synced to the same honest wording.
- **`pyproject.toml`:** version bumped `0.1.0` → `0.2.0` to match
  `plugin.json`. A test asserts the two versions stay in sync.
- The deferred `touches`-integrity work is recorded as a known limitation in
  the README trust model and as a follow-up note (e.g. `docs/` backlog entry).

### 5. Discipline

- The implementation plan lives in `docs/plans/` with `## Task` headings and a
  `task-meta` block per task.
- Every new script is built test-first (TDD): `recheck_plan.py` has
  `tests/harness/test_recheck_plan.py`; the parser refactor extends
  `test_schema.py` and `test_run_task.py`.
- Each task's `verify` is a fast, targeted pytest nodeid.

## Task breakdown (indicative — finalized by writing-plans)

1. **Version sync** — `pyproject.toml` → `0.2.0`; add a version-consistency
   test. Independent / entrypoint.
2. **Region-based plan model** — refactor `schema.py` (region walker, unified
   heading regex, zero/two-block errors); update `run_task.py` to tick by
   bound region; extend `test_schema.py` and `test_run_task.py`.
3. **`recheck_plan.py`** — new script + `test_recheck_plan.py`. Depends on (2).
4. **Pre-commit hook** — `templates/hooks/pre-commit`; `init.sh` / `init.ps1`
   copy it. Depends on (3).
5. **smoke_e2e bypass step** — extend `smoke_e2e.py` to assert `recheck_plan`
   rejects a hand-ticked task. Depends on (3).
6. **CI + bootstrap wiring** — `ci.yml` and `bootstrap-dev-leash` skill: hook
   install prompt + CI snippet doc. Depends on (4), (5).
7. **Honest framing** — README trust model, `plugin.json` description,
   `CHANGELOG.md`, deferred-limitation note. Independent / entrypoint.

Tasks 1, 2, and 7 are entrypoints (no dependencies) and parallelizable.

## Success criteria

- `parse_plan` errors on a region with multiple `task-meta` blocks and on a
  block outside any heading; a heading with no block is accepted as a
  human-run task. Behaviour is identical for H2 and H3 headings.
- `run_task.py` ticks the correct task even when prose elsewhere contains a
  string like `id: T0x`.
- `recheck_plan.py` exits `1` for a plan with a ticked-but-not-done task and
  `0` when every ticked task re-verifies.
- `smoke_e2e.py` includes and passes the bypass-detection step in CI.
- README has a Trust model section; `plugin.json` and `pyproject.toml` agree
  on version; the version-sync test passes.
- The whole effort ships as a plan under `docs/plans/`, executed task-by-task
  through the harness.
