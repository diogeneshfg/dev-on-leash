# dev-on-leash — Agent Operating Manual

dev-on-leash is a Claude Code plugin that installs a disciplined development harness (TDD, plan-based tasks, gates, cycle-done) in any target project.

This file orients automated agents (Claude Code, CI bots, code-review agents) working on the codebase. It describes the mandatory development discipline and how to run the test suites locally.

---

## Branch discipline (mandatory)

> Every implementation MUST be done on a new branch created from `main`. Never commit implementation changes directly to `main`.

Standard flow before any change:

1. `git checkout main && git pull` — start from the latest state.
2. `git checkout -b <type>/<short-description>` — e.g. `feat/two-step-upload`, `fix/null-pointer`.
3. Implement following TDD (see section below).
4. Open PR — CI runs mandatory jobs; merge only after green.

---

## Test-Driven Development (mandatory)

> Every new feature, bugfix, or behavior change MUST follow Red → Green → Refactor.

How to run tests:

```bash
python -m pytest tests/ -q
```

---

## Harness tooling

Five scripts extend the execution harness. All exit `0` on success, `1` on a real failure, `2` on a usage error. Plans live in `docs/plans/`.

- **Task runner** — `python scripts/harness/run_task.py <plan.md> <task-id>`
- **Cycle closer** — `python scripts/harness/cycle_done.py --plan <file>`
- **Plan validator** — `python scripts/harness/validate_plan.py <plan.md>`

---

<!-- OPTIONAL:ARCHITECTURE -->
## Architecture

This project follows **dev-on-leash internal — 3 layers (harness / plugin-interface / support)**. The structured spec is in [`.harness/architecture.yaml`](.harness/architecture.yaml) — that file is the source of truth. The summary below is regenerated from it; do not hand-edit.

**Layers**

| Layer | Paths |
| --- | --- |
| harness | scripts/harness/** |
| plugin_interface | agents/**, skills/**, templates/** |
| support | tests/**, docs/** |

**Allowed dependencies**

- `support` → `harness`
- (no other edges allowed)

**Mechanical gates**

- `python .harness/checks/pattern-harness_no_network_requests.py` — forbids network libraries in the harness layer.
- `python -m importlinter --config .harness/importlinter.ini` — enforces declared dependency edges between Python modules.

**Reviewer agent**

The `architecture-reviewer` agent at `agents/architecture-reviewer.md` enforces judgment-level rules from `review_rules[]`. Run it before opening a PR.

**Changing the architecture**

Re-run the `compose-architecture-leash` skill (modes: add / revise / re-describe). Hand-editing this section will be overwritten on the next compile.
<!-- /OPTIONAL:ARCHITECTURE -->
