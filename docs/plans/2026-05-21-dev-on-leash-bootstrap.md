# dev-on-leash Bootstrap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to execute this plan task-by-task. Each task carries one `- [ ]` checkbox plus a `task-meta` block; once the harness is vendored (Wave 2), tick checkboxes only via `scripts/harness/run_task.py`.

**Goal:** Build `dev-on-leash` — a portable Claude Code plugin that packages the disciplined agentic-development harness, skills, and review agents proven in the `bluenode` repo, installable into any project from GitHub.

**Architecture:** Two layers. (A) *Project-agnostic, mechanically copyable* — the harness scripts, task-schema, plan-template, the `execute-plan-task` skill — vendored verbatim from bluenode. (B) *Project-specific, interview-generated* — `CLAUDE.md`/`AGENTS.md` are shipped as `.tmpl` skeletons with fixed process prose plus `{{placeholders}}`; the `bootstrap-dev-leash` skill interviews a target project and renders them. The plugin also ships review agents and a self-CI workflow.

**Tech Stack:** Claude Code plugin format (`.claude-plugin/`), Python 3.12 harness (`pyyaml`, `pytest`), PowerShell + bash init scripts, GitHub Actions.

**Source of truth:** the proven harness lives in the sibling `bluenode` repo at `../bluenode/`. "Copy from bluenode" tasks mean: copy the named file from that path verbatim unless an adjustment is specified.

---

## File Structure (target)

| Path | Responsibility |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest |
| `.claude-plugin/marketplace.json` | Makes the repo installable as its own marketplace |
| `scripts/harness/*` | Vendored harness (verbatim from `../bluenode/scripts/harness/`) |
| `tests/harness/test_*.py` | Vendored harness tests (depth-adjusted) |
| `pyproject.toml` | Minimal: pytest config + `pyyaml` dep so the harness runs |
| `templates/task-schema.md`, `plan-template.md` | Copied from bluenode |
| `templates/CLAUDE.md.tmpl`, `AGENTS.md.tmpl` | Skeletons: fixed process prose + `{{placeholders}}` |
| `templates/settings.json.tmpl` | Starter `.claude/settings.json` |
| `skills/execute-plan-task/SKILL.md` | Copied from bluenode, paths adjusted |
| `skills/bootstrap-dev-leash/SKILL.md` | NEW — interview + render `CLAUDE.md`/`AGENTS.md` |
| `agents/plan-reviewer.md` | Audits a plan against the task-schema |
| `agents/tdd-evidence-checker.md` | Flags `src/` changes lacking `tests/` changes |
| `agents/isolation-reviewer.md` | Multi-tenant / boundary leakage review |
| `agents/verification-gate.md` | Runs the suite + reports, no trust |
| `scripts/init.ps1`, `scripts/init.sh` | Copy the agnostic layer into a target repo |
| `.github/workflows/ci.yml` | Self-CI: validate manifests, lint skills, run harness tests |
| `CHANGELOG.md` | Keep a Changelog; harness-appended |

---

## Pre-flight

Repo `dev-on-leash` already exists (created + `git remote origin` set, branch `main`, with `README.md`, `.gitignore`, and this plan committed). Work directly on `main` for Wave 1; from Wave 2 on, the harness is present and normal branch discipline applies — but since this is a fresh solo repo, committing waves directly to `main` is acceptable. The sibling `../bluenode/` repo must be present on disk for the copy tasks.

---

## Wave 1 — Plugin skeleton

### Task 1: Plugin + marketplace manifests

**Files:** Create `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`.

**Step 1:** Before writing, confirm the current Claude Code plugin manifest schema — dispatch the `claude-code-guide` agent or query context7 for "Claude Code plugin.json and marketplace.json schema". Adjust field names below if the schema has changed.

**Step 2:** Create `.claude-plugin/plugin.json`:

```json
{
  "name": "dev-on-leash",
  "version": "0.1.0",
  "description": "Disciplined agentic-development harness, skills, and review agents — keeps AI-driven development on guardrails.",
  "author": { "name": "diogeneshfg" },
  "homepage": "https://github.com/diogeneshfg/dev-on-leash",
  "keywords": ["harness", "tdd", "planning", "agents", "workflow"]
}
```

**Step 3:** Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "dev-on-leash",
  "owner": { "name": "diogeneshfg" },
  "plugins": [
    {
      "name": "dev-on-leash",
      "source": "./",
      "description": "Disciplined agentic-development harness, skills, and review agents."
    }
  ]
}
```

**Step 4:** Validate both files parse as JSON: `python -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json')); print('OK')"`.

**Step 5:** Commit: `feat(plugin): add plugin + marketplace manifests`.

- [ ] **Task 1 complete**

<!-- task-meta
id: T01
touches:
  - .claude-plugin/plugin.json
  - .claude-plugin/marketplace.json
depends: []
verify: python -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json')); print('OK')"
acceptance: null
-->

---

## Wave 2 — Vendored harness

### Task 2: Copy the harness scripts verbatim

**Files:** Create `scripts/harness/` — copy every file from `../bluenode/scripts/harness/` EXCEPT `__pycache__/`:
`__init__.py`, `_common.py`, `schema.py`, `validate_plan.py`, `run_task.py`, `onda_done.py`, `plan_schedule.py`, `check_freshness.py`, `baseline.py`, `check_regression.py`, `check_regression.ps1`, `check_regression.sh`, `accept_baseline.py`, `snapshot_baseline.py`.

**Important:** keep the `scripts/harness/` path exactly — the scripts do `sys.path.insert(0, parents[2])` then `from scripts.harness.X import ...`; the layout must match for imports to resolve. Add an empty `scripts/__init__.py` if bluenode has one (it does).

**Step 1:** Copy the files. **Step 2:** Confirm `python scripts/harness/validate_plan.py docs/plans/2026-05-21-dev-on-leash-bootstrap.md` runs (it will report task count once `pyyaml` is installed in Task 3 — for now just confirm no `ImportError` other than yaml). **Step 3:** Commit: `feat(harness): vendor proven harness scripts from bluenode`.

- [ ] **Task 2 complete**

<!-- task-meta
id: T02
touches:
  - scripts/__init__.py
  - scripts/harness/__init__.py
  - scripts/harness/schema.py
  - scripts/harness/_common.py
  - scripts/harness/validate_plan.py
  - scripts/harness/run_task.py
  - scripts/harness/onda_done.py
  - scripts/harness/plan_schedule.py
  - scripts/harness/check_freshness.py
  - scripts/harness/baseline.py
  - scripts/harness/check_regression.py
  - scripts/harness/accept_baseline.py
  - scripts/harness/snapshot_baseline.py
depends: [T01]
verify: python -c "import pathlib,sys; sys.exit(0 if pathlib.Path('scripts/harness/plan_schedule.py').exists() and pathlib.Path('scripts/harness/onda_done.py').exists() else 1)"
acceptance: null
-->

### Task 3: pyproject.toml + vendored harness tests

**Files:** Create `pyproject.toml`; create `tests/harness/test_*.py` (copy the six test files from `../bluenode/packages/api/tests/unit/harness/`).

**Step 1:** Create `pyproject.toml`:

```toml
[project]
name = "dev-on-leash"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
markers = ["unit: fast tests with no external dependencies"]
testpaths = ["tests"]
```

(No `--cov` addopts — keep the harness verify commands simple.)

**Step 2:** Copy `test_schema.py`, `test_validate_plan.py`, `test_run_task.py`, `test_onda_done.py`, `test_plan_schedule.py`, `test_check_freshness.py` from bluenode into `tests/harness/`. In EACH file, change `REPO_ROOT = Path(__file__).resolve().parents[5]` to `parents[2]` (in dev-on-leash the test sits at `tests/harness/test_x.py`, so the repo root is two parents up). Add an empty `tests/__init__.py` and `tests/harness/__init__.py` only if bluenode's layout used them — otherwise omit.

**Step 3:** Install and run: `python -m pip install pyyaml pytest` (or `uv`), then `python -m pytest tests/harness -q`. Expected: all harness tests green.

**Step 4:** Commit: `test(harness): vendor harness tests + minimal pyproject`.

- [ ] **Task 3 complete**

<!-- task-meta
id: T03
touches:
  - pyproject.toml
  - tests/harness/test_schema.py
  - tests/harness/test_validate_plan.py
  - tests/harness/test_run_task.py
  - tests/harness/test_onda_done.py
  - tests/harness/test_plan_schedule.py
  - tests/harness/test_check_freshness.py
depends: [T02]
verify: python -m pytest tests/harness -q
acceptance: null
-->

---

## Wave 3 — Templates

### Task 4: Copy task-schema and plan-template

**Files:** Create `templates/task-schema.md` and `templates/plan-template.md` — copy verbatim from `../bluenode/docs/superpowers/templates/`.

Commit: `feat(templates): add task-schema and plan-template`.

- [ ] **Task 4 complete**

<!-- task-meta
id: T04
touches:
  - templates/task-schema.md
  - templates/plan-template.md
depends: [T01]
verify: python -c "import pathlib,sys; sys.exit(0 if pathlib.Path('templates/task-schema.md').exists() and pathlib.Path('templates/plan-template.md').exists() else 1)"
acceptance: null
-->

### Task 5: CLAUDE.md / AGENTS.md template skeletons

**Files:** Create `templates/CLAUDE.md.tmpl`, `templates/AGENTS.md.tmpl`, `templates/settings.json.tmpl`.

The `.tmpl` files separate **fixed process prose** (copied as-is into every project) from **`{{placeholders}}`** the bootstrap skill fills via interview.

**Step 1:** `AGENTS.md.tmpl` — fixed sections (verbatim, no placeholders): branch discipline, TDD Red→Green→Refactor, the task-schema rules, "the gate is the integration suite", harness tooling (`plan_schedule`/`check_freshness`/`onda_done`). Placeholder sections: `{{PROJECT_NAME}}`, `{{STACK_DESCRIPTION}}`, `{{PACKAGE_LAYOUT}}`, `{{TEST_COMMANDS}}`, `{{COVERAGE_TARGETS}}`, `{{DOMAIN_RULES}}` (optional block, e.g. multi-tenancy), `{{UI_RULES}}` (optional block). Base the fixed prose on `../bluenode/AGENTS.md` but strip every bluenode-specific domain detail.

**Step 2:** `CLAUDE.md.tmpl` — fixed: the planning-trigger block, the "skip planning for" list, the pointer to `AGENTS.md`. Placeholders: `{{PROJECT_NAME}}`, `{{STACK_SUMMARY}}`, `{{COMMON_COMMANDS}}`. Base on `../bluenode/CLAUDE.md`.

**Step 3:** `settings.json.tmpl` — a minimal `.claude/settings.json` with a `permissions.allow` list of common safe commands (test/lint/typecheck/build) as `{{placeholders}}` the interview fills.

**Step 4:** Commit: `feat(templates): add CLAUDE/AGENTS/settings skeletons with placeholders`.

- [ ] **Task 5 complete**

<!-- task-meta
id: T05
touches:
  - templates/CLAUDE.md.tmpl
  - templates/AGENTS.md.tmpl
  - templates/settings.json.tmpl
depends: [T04]
verify: python -c "import pathlib,sys; req=['templates/CLAUDE.md.tmpl','templates/AGENTS.md.tmpl','templates/settings.json.tmpl']; sys.exit(0 if all(pathlib.Path(p).exists() for p in req) else 1)"
acceptance: null
-->

---

## Wave 4 — Skills

### Task 6: execute-plan-task skill

**Files:** Create `skills/execute-plan-task/SKILL.md` — copy from `../bluenode/.claude/skills/execute-plan-task/SKILL.md`. Adjust any bluenode-specific paths (e.g. `docs/superpowers/plans/` → `docs/plans/`) and remove the word "Bluenode" from the description. The verify-cannot-be-bypassed constraints stay verbatim.

Commit: `feat(skills): add execute-plan-task skill`.

- [ ] **Task 6 complete**

<!-- task-meta
id: T06
touches:
  - skills/execute-plan-task/SKILL.md
depends: [T01]
verify: python -c "import pathlib,sys; sys.exit(0 if pathlib.Path('skills/execute-plan-task/SKILL.md').exists() else 1)"
acceptance: null
-->

### Task 7: bootstrap-dev-leash skill (the interview)

**Files:** Create `skills/bootstrap-dev-leash/SKILL.md`.

This is the plugin's centerpiece — a skill that, run inside a target project, interviews the user and scaffolds the discipline. SKILL.md must specify:

1. **Frontmatter** — `name: bootstrap-dev-leash`, a `description:` that triggers on "set up dev-on-leash", "bootstrap this project", "add the harness".
2. **Interview** — ask (via `AskUserQuestion` where possible): project name; language/stack; mono-repo or single; test / lint / typecheck / build commands; branch flow (PR vs direct-to-main); does the project have a domain-rules concern (e.g. multi-tenancy) — include or drop the `{{DOMAIN_RULES}}` block; does it have a design system — include or drop `{{UI_RULES}}`; coverage targets.
3. **Render** — read `templates/CLAUDE.md.tmpl` / `AGENTS.md.tmpl` / `settings.json.tmpl` from the plugin dir, substitute every `{{placeholder}}` with interview answers, drop optional blocks not selected, write `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json` into the target project.
4. **Copy the agnostic layer** — invoke `scripts/init.*` (Task 12) to drop `scripts/harness/`, `docs/plans/` skeleton, and `templates/task-schema.md` + `plan-template.md` into the target project.
5. **Report** — list what was created and the next step (`write a plan, then execute-plan-task`).

Constraints to state in the skill: never overwrite an existing `CLAUDE.md`/`AGENTS.md` without showing a diff and confirming; the fixed process prose is non-negotiable (do not let the interview weaken TDD / branch discipline).

Commit: `feat(skills): add bootstrap-dev-leash interview skill`.

- [ ] **Task 7 complete**

<!-- task-meta
id: T07
touches:
  - skills/bootstrap-dev-leash/SKILL.md
depends: [T05]
verify: |-
  python -c "import pathlib,sys; t=pathlib.Path('skills/bootstrap-dev-leash/SKILL.md').read_text(encoding='utf-8'); sys.exit(0 if 'name: bootstrap-dev-leash' in t else 1)"
acceptance: null
-->

---

## Wave 5 — Review agents

Each agent is a Markdown file with YAML frontmatter (`name`, `description`, optional `tools`) followed by the agent's operating instructions. `plan-reviewer` below is the complete exemplar; the other three follow the same shape.

### Task 8: plan-reviewer agent

**Files:** Create `agents/plan-reviewer.md`:

```markdown
---
name: plan-reviewer
description: Audits an implementation plan against the dev-on-leash task-schema before execution. Use after a plan is written and before dispatching implementers.
tools: Read, Grep, Glob, Bash
---

You audit an implementation plan for structural soundness. You do NOT review code.

Given a plan file path:
1. Run `python scripts/harness/validate_plan.py <plan>` and report the result.
2. Run `python scripts/harness/plan_schedule.py <plan>` — report the layers and any `touches`-collision.
3. Read the plan and check each task: is `verify` fast and targeted (one nodeid / one file), not the whole suite? Does every task that creates code also touch a test file? Are there `depends` cycles or orphan tasks?
4. Flag any task whose steps contain placeholders ("TBD", "add error handling", "similar to Task N").

Report: PASS or a specific list of findings with task ids. Do not fix anything — report only.
```

Commit: `feat(agents): add plan-reviewer agent`.

- [ ] **Task 8 complete**

<!-- task-meta
id: T08
touches:
  - agents/plan-reviewer.md
depends: [T02]
verify: |-
  python -c "import pathlib,sys; t=pathlib.Path('agents/plan-reviewer.md').read_text(encoding='utf-8'); sys.exit(0 if 'name: plan-reviewer' in t else 1)"
acceptance: null
-->

### Task 9: tdd-evidence-checker agent

**Files:** Create `agents/tdd-evidence-checker.md` — frontmatter `name: tdd-evidence-checker`, `tools: Read, Grep, Glob, Bash`. Instructions: given a base and head git ref, inspect the diff; for every file changed under a source path that is NOT a test, confirm a corresponding test file was also changed; report any source change lacking test evidence, with file paths. Report-only.

Commit: `feat(agents): add tdd-evidence-checker agent`.

- [ ] **Task 9 complete**

<!-- task-meta
id: T09
touches:
  - agents/tdd-evidence-checker.md
depends: [T08]
verify: |-
  python -c "import pathlib,sys; t=pathlib.Path('agents/tdd-evidence-checker.md').read_text(encoding='utf-8'); sys.exit(0 if 'name: tdd-evidence-checker' in t else 1)"
acceptance: null
-->

### Task 10: isolation-reviewer agent

**Files:** Create `agents/isolation-reviewer.md` — frontmatter `name: isolation-reviewer`, `tools: Read, Grep, Glob`. Instructions: for projects with a stated boundary concern (multi-tenancy, per-user scoping, sandbox), review changed data-access code and confirm every new query/repository is scoped to the boundary key; flag any unscoped access. The skill is a no-op (reports "not applicable") when the project declares no isolation concern. Report-only.

Commit: `feat(agents): add isolation-reviewer agent`.

- [ ] **Task 10 complete**

<!-- task-meta
id: T10
touches:
  - agents/isolation-reviewer.md
depends: [T09]
verify: |-
  python -c "import pathlib,sys; t=pathlib.Path('agents/isolation-reviewer.md').read_text(encoding='utf-8'); sys.exit(0 if 'name: isolation-reviewer' in t else 1)"
acceptance: null
-->

### Task 11: verification-gate agent

**Files:** Create `agents/verification-gate.md` — frontmatter `name: verification-gate`, `tools: Bash, Read`. Instructions: do NOT trust any "it passes" claim; run the project's actual verification commands (from `AGENTS.md`) and `python scripts/harness/onda_done.py --plan <plan>` if a plan is given; paste real command output; report PASS only with evidence, FAIL with the failing output. This agent is the antidote to optimistic completion claims.

Commit: `feat(agents): add verification-gate agent`.

- [ ] **Task 11 complete**

<!-- task-meta
id: T11
touches:
  - agents/verification-gate.md
depends: [T10]
verify: |-
  python -c "import pathlib,sys; t=pathlib.Path('agents/verification-gate.md').read_text(encoding='utf-8'); sys.exit(0 if 'name: verification-gate' in t else 1)"
acceptance: null
-->

---

## Wave 6 — Init scripts

### Task 12: init.ps1 and init.sh

**Files:** Create `scripts/init.ps1` and `scripts/init.sh`.

Each takes one argument — the target repo path — and copies the project-agnostic layer into it: `scripts/harness/` (the whole dir), `templates/task-schema.md` + `plan-template.md` into the target's `docs/`, and creates an empty `docs/plans/` directory. It must NOT overwrite an existing `scripts/harness/` without printing a warning. It does NOT touch `CLAUDE.md`/`AGENTS.md` — those are the bootstrap skill's job (interview-driven).

Both scripts must be idempotent and print a summary of what was copied. Keep them dependency-free (pure PowerShell / pure POSIX sh).

**Step:** Smoke-test `init.sh` against a throwaway temp dir and confirm `scripts/harness/run_task.py` lands there. Commit: `feat(scripts): add init.ps1 / init.sh for the agnostic layer`.

- [ ] **Task 12 complete**

<!-- task-meta
id: T12
touches:
  - scripts/init.ps1
  - scripts/init.sh
depends: [T03, T04]
verify: python -c "import pathlib,sys; sys.exit(0 if pathlib.Path('scripts/init.ps1').exists() and pathlib.Path('scripts/init.sh').exists() else 1)"
acceptance: null
-->

---

## Wave 7 — Self-CI, changelog, smoke

### Task 13: Self-CI workflow

**Files:** Create `.github/workflows/ci.yml`.

A GitHub Actions workflow that, on push and PR, runs an `ubuntu-latest` job which:
1. Sets up Python 3.12, installs `pyyaml` + `pytest`.
2. Runs `python -m pytest tests/harness -q` (the vendored harness suite).
3. Validates the manifests parse: `python -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json'))"`.
4. Lints every `SKILL.md` and `agents/*.md` has valid YAML frontmatter (a small inline Python check: file starts with `---`, the frontmatter block parses as YAML, and contains a `name:` key).
5. Runs `python scripts/harness/validate_plan.py` on every file in `docs/plans/`.

Commit: `ci: add self-CI (harness tests, manifest + skill/agent lint)`.

- [ ] **Task 13 complete**

<!-- task-meta
id: T13
touches:
  - .github/workflows/ci.yml
depends: [T03]
verify: python -c "import pathlib,sys; t=pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8'); sys.exit(0 if 'pytest' in t and 'plugin.json' in t else 1)"
acceptance: null
-->

### Task 14: CHANGELOG + onda close

**Files:** Create `CHANGELOG.md` (the Keep a Changelog skeleton — copy the shape from `../bluenode/CHANGELOG.md`).

Then close the Onda: with all prior checkboxes ticked, run `python scripts/harness/onda_done.py --plan docs/plans/2026-05-21-dev-on-leash-bootstrap.md --skip-suite` — it appends the first real CHANGELOG entry, dogfooding the hook.

Commit: `docs: add CHANGELOG; close dev-on-leash bootstrap Onda`.

- [ ] **Task 14 complete**

<!-- task-meta
id: T14
touches:
  - CHANGELOG.md
depends: [T13]
verify: python -c "import pathlib,sys; t=pathlib.Path('CHANGELOG.md').read_text(encoding='utf-8'); sys.exit(0 if '## [Unreleased]' in t else 1)"
acceptance: null
-->

### Task 15: End-to-end install smoke test

**Files:** none committed — this is an acceptance task.

Verify the plugin actually installs and works:
1. `/plugin marketplace add diogeneshfg/dev-on-leash` then `/plugin install dev-on-leash@dev-on-leash` in a Claude Code session.
2. Confirm `bootstrap-dev-leash` and `execute-plan-task` appear as available skills and the four agents are listed.
3. Run `bootstrap-dev-leash` against a throwaway empty repo; confirm `CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, and `scripts/harness/` are generated and the harness tests run there.
4. Record the result in `CHANGELOG.md`.

- [ ] **Task 15 complete**

<!-- task-meta
id: T15
touches:
  - CHANGELOG.md
depends: [T07, T11, T12, T14]
verify: python -c "print('manual acceptance task — confirm install + bootstrap smoke in CHANGELOG'); import sys; sys.exit(0)"
acceptance: Install the plugin from GitHub, run bootstrap-dev-leash against an empty repo, confirm generated files + green harness tests.
-->

---

## Done criteria

- All 15 task checkboxes ticked via `scripts/harness/run_task.py`.
- `python -m pytest tests/harness -q` green.
- `python scripts/harness/validate_plan.py docs/plans/2026-05-21-dev-on-leash-bootstrap.md` exits 0.
- Self-CI green on GitHub.
- Plugin installs from GitHub and `bootstrap-dev-leash` scaffolds a clean target repo.

## Notes for the executor

- The sibling `../bluenode/` repo is the source for every "copy from bluenode" task. If it has moved, ask before guessing file contents.
- bluenode remains the canonical upstream for `scripts/harness/`. A future task (not in this plan) adds a drift check comparing the vendored copy to bluenode's.
- Verify the Claude Code plugin manifest schema against current docs (Task 1) — the format evolves; do not trust the snippets in this plan blindly.
