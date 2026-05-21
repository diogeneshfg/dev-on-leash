#!/usr/bin/env python3
"""Aggregate gate for cycle completion.

Checks:
  - No pending `- [ ]` checkboxes in the plan file.
  - check_regression exits 0 (skippable via --skip-suite for unit-test purposes).
  - pre-commit clean.
  - web suite green (cd packages/web && npm run test) — skippable in --skip-suite.

Exit codes:
  0 - all gates pass (or --force used + reason logged)
  1 - at least one gate failed
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXCEPTIONS = REPO_ROOT / ".harness" / "exceptions.log"

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.harness._common import bash_shell_cmd  # noqa: E402


def check_no_pending(plan_path: Path) -> bool:
    text = plan_path.read_text(encoding="utf-8")
    if re.search(r"^- \[ \]", text, re.MULTILINE):
        print(f"FAIL: pending checkboxes in {plan_path}", file=sys.stderr)
        return False
    print("OK: no pending tasks", file=sys.stderr)
    return True


def check_regression() -> bool:
    # bash_shell_cmd applies the POSIX-path + shlex.quote pattern that
    # snapshot_baseline.py and check_regression.py also use. Without it, a
    # Windows-native path passed list-form to bash fails on MSYS2 / Git Bash.
    shell_cmd = bash_shell_cmd(REPO_ROOT / "scripts" / "harness" / "check_regression.sh", [])
    rc = subprocess.call(shell_cmd, shell=True, cwd=REPO_ROOT)
    if rc != 0:
        print("FAIL: integration regression", file=sys.stderr)
        return False
    print("OK: no integration regression", file=sys.stderr)
    return True


def check_web_suite() -> bool:
    rc = subprocess.call(
        ["npm", "run", "test", "--", "--run"],
        cwd=REPO_ROOT / "packages" / "web",
    )
    if rc != 0:
        print("FAIL: web suite", file=sys.stderr)
        return False
    print("OK: web suite green", file=sys.stderr)
    return True


def check_pre_commit() -> bool:
    rc = subprocess.call(["pre-commit", "run", "--all-files"], cwd=REPO_ROOT)
    if rc != 0:
        print("FAIL: pre-commit", file=sys.stderr)
        return False
    print("OK: pre-commit clean", file=sys.stderr)
    return True


def _plan_title(plan_path: Path) -> str:
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return plan_path.stem


def append_changelog(plan_path: Path, changelog_path: Path) -> bool:
    """Append an [Unreleased] entry for this plan. Idempotent. Returns True if written."""
    today = _dt.date.today().isoformat()
    slug = plan_path.stem
    entry_header = f"### {today} — {slug}"
    if changelog_path.exists():
        text = changelog_path.read_text(encoding="utf-8")
    else:
        text = "# Changelog\n\nAll notable changes are recorded here.\n\n## [Unreleased]\n"
    if entry_header in text:
        print(f"OK: changelog already records {slug} for {today}", file=sys.stderr)
        return False
    entry = f"\n{entry_header}\n- Cycle closed: {_plan_title(plan_path)}\n"
    if "## [Unreleased]" in text:
        text = text.replace("## [Unreleased]", "## [Unreleased]" + entry, 1)
    else:
        text += "\n## [Unreleased]\n" + entry
    changelog_path.write_text(text, encoding="utf-8")
    print(f"OK: appended changelog entry for {slug}", file=sys.stderr)
    return True


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--skip-suite", action="store_true",
                   help="skip integration + web + pre-commit (for harness self-tests only)")
    p.add_argument("--force", action="store_true", help="bypass failing gates")
    p.add_argument("-m", "--message", help="audit reason (required when --force)")
    args = p.parse_args(argv[1:])

    results = [check_no_pending(args.plan)]
    if not args.skip_suite:
        results.append(check_regression())
        results.append(check_web_suite())
        results.append(check_pre_commit())

    if all(results):
        changelog_path = Path(
            os.environ.get("HARNESS_CHANGELOG_PATH", REPO_ROOT / "CHANGELOG.md")
        )
        append_changelog(args.plan, changelog_path)
        print("ALL GATES PASS", file=sys.stderr)
        return 0

    if not args.force:
        return 1

    if not args.message:
        print("--force requires -m <reason>", file=sys.stderr)
        return 1

    audit_path = Path(os.environ.get("HARNESS_EXCEPTIONS_PATH", DEFAULT_EXCEPTIONS))
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as f:
        ts = _dt.datetime.now(_dt.UTC).isoformat()
        f.write(f"{ts}\tFORCE\tplan={args.plan}\treason={args.message}\n")
    print(f"FORCED through; logged to {audit_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
