#!/usr/bin/env python3
"""Aggregate gate for cycle completion.

Checks:
  - No pending `- [ ]` checkboxes in the plan file.
  - Every command listed in `.harness/gates` exits 0
    (skippable via --skip-suite for harness self-tests).

On success, appends an `[Unreleased]` entry to CHANGELOG.md.

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

# Ensure repo root is importable when this file is run directly as a script.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.harness.branches import BranchConfigError, load_branch_config, prove_merged

DEFAULT_EXCEPTIONS = REPO_ROOT / ".harness" / "exceptions.log"
DEFAULT_GATES = REPO_ROOT / ".harness" / "gates"


def check_no_pending(plan_path: Path) -> bool:
    text = plan_path.read_text(encoding="utf-8")
    if re.search(r"^- \[ \]", text, re.MULTILINE):
        print(f"FAIL: pending checkboxes in {plan_path}", file=sys.stderr)
        return False
    print("OK: no pending tasks", file=sys.stderr)
    return True


def load_gates(gates_path: Path) -> list[str]:
    """Read `.harness/gates`: one shell command per line.

    Blank lines and lines starting with `#` are ignored. A missing file
    yields no gates — the cycle then closes on checkbox state alone.
    """
    if not gates_path.exists():
        return []
    gates: list[str] = []
    for line in gates_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            gates.append(stripped)
    return gates


def run_gates(gates: list[str]) -> bool:
    """Run each gate command from the repo root. All must exit 0."""
    ok = True
    for cmd in gates:
        rc = subprocess.call(cmd, shell=True, cwd=REPO_ROOT)
        if rc != 0:
            print(f"FAIL: gate exited {rc}: {cmd}", file=sys.stderr)
            ok = False
        else:
            print(f"OK: gate passed: {cmd}", file=sys.stderr)
    return ok


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


def _git_out(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    return proc.stdout if proc.returncode == 0 else ""


def _worktree_branches(
    repo: Path, *, prefix: str | None = "session/"
) -> list[tuple[Path, str]]:
    """Parse `git worktree list --porcelain` into (path, branch) pairs.

    With `prefix` set (default `"session/"`), returns only worktrees whose
    branch starts with it. With `prefix=None`, returns every branched
    worktree.
    """
    out = _git_out(["worktree", "list", "--porcelain"], repo)
    results: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch refs/heads/") and path is not None:
            branch = line[len("branch refs/heads/"):]
            if prefix is None or branch.startswith(prefix):
                results.append((path, branch))
            path = None
        elif line == "":
            path = None
    return results


def advise_merged_worktrees(*, repo_root: Path) -> list[str]:
    """Advisory reminders for merged proactive `<type>/<slug>` worktrees.

    Unlike `session/*` worktrees, proactive worktrees created by
    `leash-start-work` are developer-owned
    feature branches that may have an open PR. We never remove them — we
    only return a reminder string per merged one.

    Only worktrees physically located under `<repo_root>/.worktrees/` are
    considered — that is the proactive layout this feature defines. The
    location filter naturally excludes the primary checkout (the primary checkout is excluded by location, and merged-ness is proven per-branch against the configured merge target via `prove_merged`), and the sibling session worktrees.
    `session/*` branches are additionally skipped as defense in depth.
    """
    reminders: list[str] = []
    worktrees_root = (repo_root / ".worktrees").resolve()
    try:
        cfg = load_branch_config(repo_root)
    except BranchConfigError:
        # Advisory stays quiet on a bad config; finish_work (the
        # enforcement half) raises the loud error.
        return reminders
    for wt_path, branch in _worktree_branches(repo_root, prefix=None):
        if branch.startswith("session/"):
            continue  # session/* branches are not proactive worktrees
        try:
            under = wt_path.resolve().is_relative_to(worktrees_root)
        except (OSError, ValueError):
            under = False
        if not under:
            continue  # only proactive .worktrees/<slug> worktrees
        if prove_merged(repo_root, branch, cfg) is None:
            continue
        reminders.append(
            f"reminder: branch {branch} is merged — run "
            f'`git worktree remove "{wt_path}"` to clean up'
        )
    return reminders


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--skip-suite", action="store_true",
                   help="skip the .harness/gates commands (for harness self-tests only)")
    p.add_argument("--force", action="store_true", help="bypass failing gates")
    p.add_argument("-m", "--message", help="audit reason (required when --force)")
    args = p.parse_args(argv[1:])

    results = [check_no_pending(args.plan)]
    if not args.skip_suite:
        gates_path = Path(os.environ.get("HARNESS_GATES_PATH", DEFAULT_GATES))
        gates = load_gates(gates_path)
        if gates:
            results.append(run_gates(gates))
        else:
            print(f"note: no gate commands ({gates_path} absent or empty) — "
                  "closing on checkbox state only", file=sys.stderr)

    if all(results):
        changelog_path = Path(
            os.environ.get("HARNESS_CHANGELOG_PATH", REPO_ROOT / "CHANGELOG.md")
        )
        append_changelog(args.plan, changelog_path)
        print("ALL GATES PASS", file=sys.stderr)
        try:
            for msg in advise_merged_worktrees(repo_root=REPO_ROOT):
                print(msg, file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"advise: skipped ({exc})", file=sys.stderr)
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
