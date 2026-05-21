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

from scripts.harness.schema import _strip_fenced_blocks, parse_plan

REPO_ROOT = Path(__file__).resolve().parents[2]

# Outer task headings can be H2 or H3 at column 0. Test-fixture `### Task` lines
# (indented under fences) and prose mentions ("### Task N:") never match this.
HEADING_RE = re.compile(r"^##+\s+Task\b[^\n]*$", re.MULTILINE)


def _tick_first_checkbox(plan_text: str, task_id: str) -> str:
    """Replace the first `- [ ]` after the heading of the task with id `task_id` with `- [x]`.

    Works on *line indices*, not character offsets: `_strip_fenced_blocks`
    preserves line count but not character positions (it blanks fenced lines
    to empty strings), so heading positions found in the stripped text are
    only valid as line numbers. Headings are located in the stripped text (so
    example `### Task` / `id:` lines inside fenced fixtures are ignored); the
    checkbox is flipped in the original text at the same line index.
    """
    lines = plan_text.split("\n")
    stripped_lines = _strip_fenced_blocks(plan_text).split("\n")
    heading_idxs = [
        i for i, line in enumerate(stripped_lines) if HEADING_RE.match(line)
    ]
    if not heading_idxs:
        return plan_text

    for k, start in enumerate(heading_idxs):
        end = heading_idxs[k + 1] if k + 1 < len(heading_idxs) else len(stripped_lines)
        if not any(f"id: {task_id}" in stripped_lines[j] for j in range(start, end)):
            continue
        # Found the task: flip the first "- [ ]" in the original text in range.
        for j in range(start, end):
            if not stripped_lines[j]:
                # Blank in the stripped text => the line was inside a fenced
                # block (or genuinely empty). Never tick a fenced example
                # checkbox; only real checkboxes survive stripping.
                continue
            new_line, n = re.subn(r"- \[ \]", "- [x]", lines[j], count=1)
            if n:
                lines[j] = new_line
                return "\n".join(lines)
        return plan_text

    return plan_text


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: run_task.py <plan.md> <task_id>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    task_id = argv[2]
    tasks = {t.id: t for t in parse_plan(plan_path)}
    if task_id not in tasks:
        print(f"error: task {task_id} not found in {plan_path}", file=sys.stderr)
        return 2
    task = tasks[task_id]
    print(f"[harness] running verify for {task_id}: {task.verify}", file=sys.stderr)
    # verify commands are written assuming repo-root CWD (e.g. `cd packages/api && ...`).
    # Force CWD to repo root so invocation location doesn't change semantics.
    rc = subprocess.call(task.verify, shell=True, cwd=REPO_ROOT)
    if rc != 0:
        print(f"[harness] verify FAILED (exit {rc}); checkbox left unticked", file=sys.stderr)
        return 1
    new_text = _tick_first_checkbox(plan_path.read_text(encoding="utf-8"), task_id)
    plan_path.write_text(new_text, encoding="utf-8")
    print(f"[harness] {task_id} OK; checkbox ticked", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
