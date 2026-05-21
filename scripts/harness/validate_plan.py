#!/usr/bin/env python3
"""Validate a plan file against the task-meta schema.

Usage:
    python scripts/harness/validate_plan.py <plan_path>

Exits 0 if valid (may print warnings on stderr), 1 on schema error.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import SchemaError, _strip_fenced_blocks, parse_plan

UI_PREFIX = "packages/web/src/presentation/"

# A "task heading" is an H2-or-deeper Markdown heading whose text starts with
# "Task" — run_task.py recognises the same shape. Counting these lets
# validate_plan flag a plan whose task headings carry no task-meta block,
# instead of silently reporting "0 tasks valid".
TASK_HEADING_RE = re.compile(r"^#{2,}\s+Task\b", re.MULTILINE)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_plan.py <plan.md>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    if not plan_path.exists():
        print(f"error: {plan_path} does not exist", file=sys.stderr)
        return 1
    try:
        tasks = parse_plan(plan_path)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # A task-meta block is what makes a task machine-runnable; a task heading
    # without one is human-run. Compare the two so a plan that has tasks but
    # no task-meta is reported clearly rather than passing as "0 tasks".
    raw = plan_path.read_text(encoding="utf-8")
    heading_count = len(TASK_HEADING_RE.findall(_strip_fenced_blocks(raw)))

    if heading_count and not tasks:
        print(
            f"error: {plan_path} has {heading_count} task heading(s) but no "
            "task-meta blocks - the harness cannot execute it. Add a "
            "<!-- task-meta --> block to each task you want run_task.py to "
            "verify (see docs/task-schema.md).",
            file=sys.stderr,
        )
        return 1

    untracked = heading_count - len(tasks)
    if untracked > 0:
        print(
            f"WARN: {untracked} of {heading_count} task heading(s) have no "
            "task-meta block — those tasks are not harness-tracked.",
            file=sys.stderr,
        )

    for t in tasks:
        if any(p.startswith(UI_PREFIX) for p in t.touches) and t.acceptance is None:
            print(f"WARN: {t.id} touches UI ({UI_PREFIX}*) but has no acceptance command", file=sys.stderr)

    print(f"OK: {len(tasks)} harness task(s) valid", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
