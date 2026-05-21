# dev-on-leash

A disciplined agentic-development harness, packaged as a portable **Claude Code plugin**.

`dev-on-leash` keeps AI-driven development on guardrails: a verify-gated task
schema, a parallel-execution scheduler, a doc-freshness check, an auto-appended
changelog, custom review agents, and a bootstrap skill that scaffolds the whole
discipline into any project. It was extracted from a proven internal harness
that runs in CI and git hooks.

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
