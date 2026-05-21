#!/usr/bin/env python3
"""Run the integration suite and write `.harness/baseline.json`.

Usage:
    python scripts/harness/snapshot_baseline.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.harness._common import bash_shell_cmd
from scripts.harness.baseline import build_from_junit, save

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO_ROOT / ".harness" / "baseline.json"
JUNIT_PATH = REPO_ROOT / ".harness" / "_last_junit.xml"

# Match the default invocation inside scripts/test-integration.sh (zero-args branch),
# plus --junitxml. We MUST repeat the marker + flags because passing any args to the
# script replaces the defaults instead of appending.
PYTEST_ARGS = ["-m", "integration", "--no-cov", "-q", "--junitxml=.harness/_last_junit.xml"]


def main() -> int:
    JUNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if JUNIT_PATH.exists():
        JUNIT_PATH.unlink()

    shell_cmd = bash_shell_cmd(REPO_ROOT / "scripts" / "test-integration.sh", PYTEST_ARGS)
    print(f"running: {shell_cmd}", file=sys.stderr)
    rc = subprocess.call(shell_cmd, shell=True, cwd=REPO_ROOT)
    if not JUNIT_PATH.exists():
        print(f"error: {JUNIT_PATH} not produced (suite exited {rc})", file=sys.stderr)
        return 1
    baseline = build_from_junit(JUNIT_PATH, suite="integration")
    save(baseline, BASELINE_PATH)
    print(
        f"baseline updated: {len(baseline.passed)} passed, "
        f"{len(baseline.xfail)} xfail, {len(baseline.xpass)} xpass, "
        f"{len(baseline.skipped)} skipped",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
