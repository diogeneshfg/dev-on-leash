#!/usr/bin/env python3
"""Execute one task's verify command. On success, tick the first checkbox in the task body.

Usage:
    python scripts/harness/run_task.py <plan.md> <task_id>
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import TaskRegion, _strip_fenced_blocks, parse_regions

REPO_ROOT = Path(__file__).resolve().parents[2]


def _tick_checkbox_in_region(plan_text: str, region: TaskRegion) -> str:
    """Flip the first real `- [ ]` inside `region` to `- [x]`.

    Lines blank in the fence-stripped text were inside a fenced block (or
    genuinely empty) and are skipped — an example checkbox in a code fence is
    never ticked. Operates on line indices: `_strip_fenced_blocks` preserves
    line count, and `region`'s indices come from the same stripping.
    """
    lines = plan_text.split("\n")
    stripped_lines = _strip_fenced_blocks(plan_text).split("\n")
    for j in range(region.heading_line, min(region.end_line, len(lines))):
        if not stripped_lines[j].strip():
            continue
        new_line, n = re.subn(r"- \[ \]", "- [x]", lines[j], count=1)
        if n:
            lines[j] = new_line
            return "\n".join(lines)
    return plan_text


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: run_task.py <plan.md> <task_id>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    task_id = argv[2]
    regions = parse_regions(plan_path)
    region = next(
        (r for r in regions if r.meta is not None and r.meta.id == task_id),
        None,
    )
    if region is None:
        print(f"error: task {task_id} not found in {plan_path}", file=sys.stderr)
        return 2
    task = region.meta
    print(f"[harness] running verify for {task_id}: {task.verify}", file=sys.stderr)
    # verify commands assume repo-root CWD; force it so invocation location
    # does not change semantics.
    rc = subprocess.call(task.verify, shell=True, cwd=REPO_ROOT)
    if rc != 0:
        print(f"[harness] verify FAILED (exit {rc}); checkbox left unticked", file=sys.stderr)
        return 1
    new_text = _tick_checkbox_in_region(
        plan_path.read_text(encoding="utf-8"), region
    )
    plan_path.write_text(new_text, encoding="utf-8")
    print(f"[harness] {task_id} OK; checkbox ticked", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
