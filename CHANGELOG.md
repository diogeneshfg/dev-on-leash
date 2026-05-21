# Changelog

All notable changes to dev-on-leash are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/). Entries under `[Unreleased]`
are appended automatically by `scripts/harness/cycle_done.py` when a Cycle
closes green; edit them by hand only to add detail.

## [Unreleased]
### 2026-05-21 — 2026-05-21-dev-on-leash-bootstrap
- Cycle closed: dev-on-leash Bootstrap — Implementation Plan


Bootstrap of the 0.1.0 release: portable Claude Code plugin packaging the
disciplined agentic-development harness (Cycle lifecycle, skills, hooks,
CHANGELOG automation).

### Task 15 — install smoke test

- **Local bootstrap smoke test: PASS.** Against a throwaway `git init` repo,
  `scripts/init.*` copied the agnostic layer cleanly (`scripts/harness/` with
  no `__pycache__`, `docs/task-schema.md`, `docs/plan-template.md`, empty
  `docs/plans/`; no `CLAUDE.md`/`AGENTS.md`). The template render produced
  placeholder-free `CLAUDE.md`/`AGENTS.md`/`.claude/settings.json` with one
  optional block kept and one dropped, valid JSON settings, and the vendored
  harness ran inside the target (`validate_plan.py` → exit 0). dev-on-leash's
  own harness suite: 32 passed.
- **GitHub install step: pending user action.** The `/plugin marketplace add
  diogeneshfg/dev-on-leash` + `/plugin install dev-on-leash@dev-on-leash` flow
  and the in-session check that the skills/agents appear must be run
  interactively in a Claude Code session after this branch is pushed; it
  cannot be performed by the plan executor.
