#!/usr/bin/env python3
"""Re-verify every ticked task in a plan.

run_task.py ticks a task's checkbox only after its `verify` command exits 0.
This script independently re-runs `verify` for every task whose checkbox is
already `- [x]`. A box ticked without the work actually done fails its own
verify here — so a hand-edited tick cannot survive CI or the pre-commit hook.
Nothing is trusted but the plan file and the source tree.

Usage:
    python scripts/harness/recheck_plan.py <plan.md>

Exit codes:
    0 - every ticked task re-verified (or the plan has no ticked tasks)
    1 - at least one ticked task failed to re-verify
    2 - usage error / plan file missing / schema error
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import (
    SchemaError,
    TaskRegion,
    _strip_fenced_blocks,
    parse_regions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _region_is_ticked(plan_text: str, region: TaskRegion) -> bool:
    """True if the first real checkbox in `region` is `- [x]`.

    Mirrors run_task.py: the first checkbox not blanked by _strip_fenced_blocks
    is the task's status box. No checkbox at all -> treated as not ticked.
    """
    lines = plan_text.split("\n")
    stripped = _strip_fenced_blocks(plan_text).split("\n")
    for j in range(region.heading_line, min(region.end_line, len(lines))):
        if not stripped[j].strip():
            continue
        if re.search(r"- \[x\]", lines[j]):
            return True
        if re.search(r"- \[ \]", lines[j]):
            return False
    return False


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: recheck_plan.py <plan.md>", file=sys.stderr)
        return 2
    plan_path = Path(argv[1])
    if not plan_path.exists():
        print(f"error: {plan_path} does not exist", file=sys.stderr)
        return 2
    try:
        regions = parse_regions(plan_path)
    except SchemaError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    plan_text = plan_path.read_text(encoding="utf-8")
    ticked = [
        r
        for r in regions
        if r.meta is not None and _region_is_ticked(plan_text, r)
    ]
    if not ticked:
        print("OK: no ticked tasks to re-verify", file=sys.stderr)
        return 0

    failures: list[str] = []
    for r in ticked:
        print(f"[recheck] {r.meta.id}: {r.meta.verify}", file=sys.stderr)
        rc = subprocess.call(r.meta.verify, shell=True, cwd=REPO_ROOT)
        if rc == 0:
            print(f"OK: {r.meta.id} re-verified", file=sys.stderr)
        else:
            print(
                f"FAIL: {r.meta.id} is ticked but verify exited {rc}",
                file=sys.stderr,
            )
            failures.append(r.meta.id)

    if failures:
        print(
            f"REJECTED: {len(failures)} ticked task(s) failed re-verify: {failures}",
            file=sys.stderr,
        )
        return 1
    print(f"ALL CLEAR: {len(ticked)} ticked task(s) re-verified", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
