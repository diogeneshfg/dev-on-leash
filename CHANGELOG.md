# Changelog

All notable changes to dev-on-leash are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/). Entries under `[Unreleased]`
are appended automatically by `scripts/harness/cycle_done.py` when a cycle
closes green; edit them by hand to add detail.

## [Unreleased]
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
