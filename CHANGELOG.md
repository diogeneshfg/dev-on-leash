# Changelog

All notable changes to dev-on-leash are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/). Entries under `[Unreleased]`
are appended automatically by `scripts/harness/cycle_done.py` when a cycle
closes green; edit them by hand to add detail.

## [Unreleased]
### 2026-05-28 — session-leash
- Per-session git worktree guard-rail against concurrent Claude Code sessions
  clobbering each other's WIP. Detection via `.harness/sessions/<pid>.json`
  lockfile + two-phase write at `SessionStart`; enforcement via a
  `PreToolUse` gate on `Edit|Write|MultiEdit`; auto-resolution by routing
  the blocked session into a sibling `git worktree` via the new
  `/leash-session-new` skill. Cleanup via `/leash-session-end` and a
  conservative sweep in `cycle_done` (merged + clean + dead-PID + matching
  lockfile). Bootstrap skill now patches the target project's `.gitignore`
  to ignore `.harness/sessions/`. Load-bearing dogfood at
  `scripts/dogfood_session.py`, smoke_e2e step 9.

### 2026-05-25 — architecture-leash
- Declared-then-enforced architecture leash: `compose-architecture-leash`
  skill interviews the user in prose, extracts a structured
  `.harness/architecture.yaml`, and compiles it into mechanical gates
  (Python `import-linter`, JS/TS `dependency-cruiser`, generic Python checks)
  + a project-local `architecture-reviewer` agent.

### 2026-05-22 — harness-hardening
- Cycle closed: Harness Hardening Implementation Plan


## [0.2.0] — 2026-05-21

Initial public release.

### Added
- Portable Claude Code plugin packaging the agentic-development harness:
  `validate_plan`, `run_task`, `cycle_done`, `plan_schedule`, `check_freshness`,
  and baseline/regression tooling. Plain Python — no Claude Code required to run.
- Skills — `bootstrap-dev-leash` (interview + scaffold a project) and
  `execute-plan-task`.
- Review agents — `plan-reviewer`, `tdd-evidence-checker`, `isolation-reviewer`,
  `verification-gate`.
- `task-meta` augmentation model: annotate any plan's tasks to make them
  machine-verified; `validate_plan` reports task headings that lack `task-meta`.
- Project-configurable cycle gates via `.harness/gates`.
- `scripts/init.{sh,ps1}` install the agnostic layer into any repo;
  `scripts/smoke_e2e.py` drives the whole harness loop end to end; the self-CI
  workflow runs both the unit suite and the smoke test on every push.
