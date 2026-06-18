# Changelog

All notable changes to dev-on-leash are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/). `scripts/harness/cycle_done.py`
appends entries under `[Unreleased]` when a cycle closes green; edit them by
hand to add detail. At release time the `[Unreleased]` block is cut into a
versioned `## [X.Y.Z] — <date>` heading (see `docs/RELEASING.md`), so
`[Unreleased]` only ever holds work that has not shipped in a release.

## [Unreleased]
### 2026-06-17 — changelog-versioned-headings
- Recut already-released entries into versioned `## [X.Y.Z] — <date>` headings
  (0.3.0, 0.4.0) instead of letting them accumulate under `[Unreleased]`, so
  the CHANGELOG answers "what shipped in version X?" without `git log`.
  `docs/RELEASING.md` now documents cutting the heading at release time.

## [0.4.0] — 2026-06-17
### 2026-06-17 — session-new-base-main
- `/leash-session-new` now cuts the `session/<id>` worktree branch from the
  trunk (`main`/`master`) instead of the primary checkout's `HEAD`, falling
  back to `HEAD` only when the repo has neither. A concurrent session does
  *distinct* work, so basing off `HEAD` grafted the primary branch's commits
  onto `session/<id>` — making it non-mergeable to `main` on its own and
  stranding it if that branch was later rebased or abandoned. New
  `tests/test_session_new.py` covers main / master / no-trunk bases (the
  module had no test before).
- Document the release process in `docs/RELEASING.md`: lockstep version bump
  (`pyproject.toml` + `.claude-plugin/plugin.json`), CHANGELOG convention, and
  the merge + cleanup flow.

## [0.3.0] — 2026-06-09
### 2026-06-08 — worktree-aware-discipline
- Make git worktrees a first-class, opt-in part of the branch-discipline
  workflow. `cycle_done` now prints an advisory reminder to `git worktree
  remove` for merged proactive worktrees under `.worktrees/` (advisory only —
  never auto-removes, since feature branches may have an open PR; scoped to
  `.worktrees/` so the primary checkout is never flagged). Bootstrap gains an
  opt-in interview item that adds `.worktrees/` to the target `.gitignore`
  under the `# dev-on-leash` heading. New voluntary `/leash-start-work` skill
  creates `.worktrees/<slug>` on a `<type>/<slug>` branch off `main`,
  delegating the worktree mechanism to `EnterWorktree` /
  `superpowers:using-git-worktrees` with a documented `git worktree add`
  fallback. `AGENTS.md`/`CLAUDE.md` templates and the README document the
  proactive path, distinct from the reactive session leash. Dogfooded on this
  repo (`.worktrees/` ignored; advisory verified live).

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
