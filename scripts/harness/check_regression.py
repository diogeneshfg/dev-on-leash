#!/usr/bin/env python3
"""Run the integration suite and fail iff the result regresses against the baseline.

Usage:
    python scripts/harness/check_regression.py

Exit codes:
    0 - no regression (may print INFO when xfail→pass for manual review)
    1 - regression: previously-passing nodeids are now failing or missing
    2 - infrastructure error (suite did not produce junit)
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness._common import bash_shell_cmd
from scripts.harness.baseline import Baseline, build_from_junit, load

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".harness" / "baseline.json"
JUNIT_PATH = REPO_ROOT / ".harness" / "_last_junit.xml"


@dataclass(frozen=True)
class RegressionResult:
    is_regression: bool
    new_failures: list[str] = field(default_factory=list)
    disappeared: list[str] = field(default_factory=list)
    xfail_to_pass: list[str] = field(default_factory=list)
    new_tests: list[str] = field(default_factory=list)
    summary: str = ""


def diff(base: Baseline, curr: Baseline) -> RegressionResult:
    base_passed = set(base.passed)
    base_xfail = set(base.xfail)
    curr_passed = set(curr.passed)
    curr_xfail = set(curr.xfail)
    curr_present = curr_passed | curr_xfail

    # A nodeid in baseline.passed that is not present (passed or xfail) now = regression.
    disappeared = sorted(base_passed - curr_present)
    # xfail in baseline now passing — informational, not a regression.
    xfail_to_pass = sorted(base_xfail & curr_passed)
    new_tests = sorted(curr_passed - base_passed - base_xfail)

    is_regression = bool(disappeared)
    parts = []
    if disappeared:
        parts.append(f"{len(disappeared)} previously-passing test(s) missing or failing")
    if xfail_to_pass:
        parts.append(f"{len(xfail_to_pass)} xfail→pass (consider promote via accept_baseline)")
    if new_tests:
        parts.append(f"{len(new_tests)} new passing test(s)")
    return RegressionResult(
        is_regression=is_regression,
        new_failures=[],
        disappeared=disappeared,
        xfail_to_pass=xfail_to_pass,
        new_tests=new_tests,
        summary="; ".join(parts) or "clean match",
    )


PYTEST_ARGS = ["-m", "integration", "--no-cov", "-q", "--junitxml=.harness/_last_junit.xml"]


def _run_suite() -> int:
    JUNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if JUNIT_PATH.exists():
        JUNIT_PATH.unlink()
    shell_cmd = bash_shell_cmd(REPO_ROOT / "scripts" / "test-integration.sh", PYTEST_ARGS)
    return subprocess.call(shell_cmd, shell=True, cwd=REPO_ROOT)


def main() -> int:
    if not BASELINE_PATH.exists():
        print(
            f"error: {BASELINE_PATH} missing — run scripts/harness/snapshot_baseline.py first",
            file=sys.stderr,
        )
        return 2
    base = load(BASELINE_PATH)
    _run_suite()
    if not JUNIT_PATH.exists():
        print(f"error: {JUNIT_PATH} not produced by suite", file=sys.stderr)
        return 2
    curr = build_from_junit(JUNIT_PATH, suite=base.suite)
    r = diff(base, curr)
    print(r.summary, file=sys.stderr)
    if r.disappeared:
        print("disappeared/failing nodeids:", file=sys.stderr)
        for n in r.disappeared[:20]:
            print(f"  - {n}", file=sys.stderr)
        if len(r.disappeared) > 20:
            print(f"  ... and {len(r.disappeared) - 20} more", file=sys.stderr)
    if r.xfail_to_pass:
        print(
            "INFO: xfail→pass — run scripts/harness/accept_baseline.py if intentional",
            file=sys.stderr,
        )
    return 1 if r.is_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
