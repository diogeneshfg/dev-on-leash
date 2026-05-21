# Task Schema

Every task in a plan under `docs/plans/` MUST embed a `task-meta` block somewhere within its `### Task N` section (parser pairs headings and blocks by occurrence order, not physical adjacency; convention is to place the block at the end of the task body). The block is an HTML comment containing YAML — invisible when the plan is rendered, parseable by `scripts/harness/schema.py`.

## Shape

```html
<!-- task-meta
id: T03
touches:
  - src/yourpkg/module.py
  - tests/test_module.py
depends: [T01, T02]
verify: python -m pytest tests/test_module.py::test_bar -xvs
acceptance: null
-->
```

For an entrypoint task (no dependencies), use `depends: []`.

## Fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `id` | yes | string matching `^T\d{2,3}$` | unique within the plan |
| `touches` | yes | list[str] | repo-relative paths the task may create or modify. `plan_schedule.py` uses these to reject same-layer write-collisions. Empty list is invalid — every task must touch something. |
| `depends` | yes | list[str] | task ids that must complete before this one. `[]` for entrypoints. Cycles are rejected. |
| `verify` | yes | string | a single shell command that proves the task is done. Must exit 0 on success. Should be **fast and targeted** (one nodeid, one file) — not the whole suite. |
| `acceptance` | no (warn) | string \| null | second command for end-to-end / visual proof. Warning emitted by `validate_plan.py` when a task touches a UI/presentation path but acceptance is null. |

## Why HTML-comment YAML

- Survives every markdown renderer unchanged (invisible).
- One regex (`<!--\s*task-meta\s*\n(.*?)\n-->` with DOTALL) extracts the YAML body.
- No new fenced-block extension to teach editors.
