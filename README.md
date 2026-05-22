# dev-on-leash

A verify-gated task harness for AI-assisted development, packaged as a
portable **Claude Code plugin**.

`dev-on-leash` turns a Markdown plan into a machine-checked workflow: a
harness task declares a `verify` command, its checkbox is ticked only when
that command passes, and every ticked harness task can be independently
re-verified so a hand-flipped checkbox cannot survive CI or a pre-commit hook.
It ships a
parallel-execution scheduler, a doc-freshness check, an auto-appended
changelog, custom review agents, and a bootstrap skill that scaffolds the
whole setup into any project.

## What's in the box

- **Harness scripts** (`scripts/harness/`) — `validate_plan`, `run_task`,
  `cycle_done`, `plan_schedule` (parallel scheduler), `check_freshness`,
  baseline/regression tooling. CI-executable, no Claude Code required.
- **Skills** (`skills/`) — `bootstrap-dev-leash` (interviews a project and
  generates a tailored `CLAUDE.md` + `AGENTS.md`) and `execute-plan-task`.
- **Agents** (`agents/`) — `plan-reviewer`, `tdd-evidence-checker`,
  `isolation-reviewer`, `verification-gate`.
- **Templates** (`templates/`) — `CLAUDE.md`/`AGENTS.md` skeletons,
  task-schema, plan-template, `settings.json`.
- **Init scripts** (`scripts/init.*`) — copy the project-agnostic layer into a
  target repo without an interview.

## Install

```
/plugin marketplace add diogeneshfg/dev-on-leash
/plugin install dev-on-leash@dev-on-leash
/bootstrap-dev-leash          # interview + generate CLAUDE.md / AGENTS.md
```

## How it works

A **plan** is a Markdown file with `## Task N` headings. Augment any task with
a `task-meta` block — `id`, `touches`, `depends`, `verify` — to make it
machine-verified. `task-meta` is an augmentation, not a separate plan format;
tasks without one are human-run and ignored by the harness. The harness then
drives the loop:

1. **`validate_plan.py <plan>`** — checks the task-meta schema, dependency
   graph, and write-collisions; warns about task headings with no `task-meta`.
2. **`plan_schedule.py <plan>`** — shows which tasks can run in parallel.
3. **`run_task.py <plan> <id>`** — runs the task's `verify` command and ticks
   its checkbox **only if it exits 0**. A failing verify leaves the box unticked.
4. **`cycle_done.py --plan <plan>`** — once every task is checked off, runs the
   project's `.harness/gates` commands and appends a `CHANGELOG.md` entry.

The harness is plain Python operating on Markdown — no Claude Code required to
run it, and no dependency on any other plugin.

## Trust model

Be precise about what the harness enforces and what it only assists:

- **Enforced.** A harness task's checkbox is ticked only by `run_task.py`
  after its `verify` command exits 0. `recheck_plan.py` re-runs the `verify`
  of every ticked harness task — run it in CI (see
  [templates/ci-snippet.md](templates/ci-snippet.md)) and/or as the opt-in
  pre-commit hook, and a checkbox flipped by hand without the work done is
  rejected. A task heading with no `task-meta` block is human-run and not
  machine-checked.
- **By convention only.** `touches` is self-reported: the harness does not yet
  check that a task modified *only* its declared files, so the parallel-safety
  of `plan_schedule.py` depends on `touches` being accurate. Verifying it
  without false positives needs its own design — tracked as a follow-up.
- **Escape hatch.** `cycle_done.py --force -m <reason>` closes a cycle past
  failing gates and appends an audit line to `.harness/exceptions.log`. It
  bypasses `cycle_done`'s own gate check only — it does not disable
  `recheck_plan` running in CI or the pre-commit hook.

## Validate the harness

```
python scripts/smoke_e2e.py
```

Builds a throwaway repo and drives the whole loop end to end in ~5s. Runs in CI
on every push.
