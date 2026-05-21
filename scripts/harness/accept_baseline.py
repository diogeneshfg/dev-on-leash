#!/usr/bin/env python3
"""Promote the most recent suite run to baseline, with an audit-log message.

Usage:
    python scripts/harness/accept_baseline.py -m "<reason>"

Reads JUnit from `.harness/_last_junit.xml` (or HARNESS_JUNIT_PATH env), writes
`.harness/baseline.json`, appends to `.harness/baseline_audit.log`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness.baseline import build_from_junit, save

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPO_ROOT / ".harness" / "baseline.json"
DEFAULT_JUNIT = REPO_ROOT / ".harness" / "_last_junit.xml"
DEFAULT_AUDIT = REPO_ROOT / ".harness" / "baseline_audit.log"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--message", required=True, help="reason for baseline promotion")
    args = parser.parse_args(argv[1:])

    baseline_path = Path(os.environ.get("HARNESS_BASELINE_PATH", DEFAULT_BASELINE))
    junit_path = Path(os.environ.get("HARNESS_JUNIT_PATH", DEFAULT_JUNIT))
    audit_path = Path(os.environ.get("HARNESS_AUDIT_PATH", DEFAULT_AUDIT))

    if not junit_path.exists():
        print(f"error: {junit_path} not found — run check_regression first", file=sys.stderr)
        return 1

    b = build_from_junit(junit_path, suite="integration")
    save(b, baseline_path)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as f:
        ts = _dt.datetime.now(_dt.UTC).isoformat()
        f.write(f"{ts}\t{args.message}\tpassed={len(b.passed)} xfail={len(b.xfail)}\n")
    print(f"baseline promoted: {baseline_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
