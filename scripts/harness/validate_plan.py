#!/usr/bin/env python3
"""Validate a plan file against the task-meta schema.

Usage:
    python scripts/harness/validate_plan.py <plan_path>

Exits 0 if valid (may print warnings on stderr), 1 on schema error.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.schema import SchemaError, parse_plan

UI_PREFIX = "packages/web/src/presentation/"


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

    for t in tasks:
        if any(p.startswith(UI_PREFIX) for p in t.touches) and t.acceptance is None:
            print(f"WARN: {t.id} touches UI ({UI_PREFIX}*) but has no acceptance command", file=sys.stderr)

    print(f"OK: {len(tasks)} task(s) valid", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
