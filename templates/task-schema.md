# Task Schema

A **plan** is an ordinary Markdown document — `## Task N` (or `### Task N`)
headings, prose, checkboxes — authored however you like: by hand, with
`superpowers:writing-plans`, or any other tool.

To make a task **machine-verifiable**, augment it with a `task-meta` block: an
HTML comment containing YAML, placed anywhere inside that task's section. A
task *with* a `task-meta` block is run and checkbox-ticked by
`scripts/harness/run_task.py` only when its `verify` command exits 0; a task
*without* one is human-run and ignored by the harness. Add `task-meta` only to
the tasks you want verified — it augments a normal plan, it is not a separate
plan format.

The block is invisible when the plan is rendered and is parsed by
`scripts/harness/schema.py`. The parser pairs headings and blocks by
occurrence order, not physical adjacency; by convention the block sits at the
end of the task body.

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
| `verify` | yes | string | a single shell command that proves the task is done. Must exit 0 on success. Should be **fast and targeted** (one nodeid, one file) — not the whole suite. If the command contains `: ` (colon-space), write it as a YAML block scalar (`verify: |-`) so it parses. |
| `acceptance` | no | string \| null | optional second command for end-to-end / visual proof. |

## Why HTML-comment YAML

- Survives every markdown renderer unchanged (invisible).
- One regex (`<!--\s*task-meta\s*\n(.*?)\n-->` with DOTALL) extracts the YAML body.
- No new fenced-block extension to teach editors.
