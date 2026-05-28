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

from scripts.harness import session_lockfile as sl  # noqa: E402
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


def _worktree_branches(repo: Path) -> list[tuple[Path, str]]:
    """Parse `git worktree list --porcelain` into (path, branch) pairs.

    Returns only worktrees whose branch starts with `session/`.
    """
    out = _git_out(["worktree", "list", "--porcelain"], repo)
    results: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line.startswith("branch refs/heads/") and path is not None:
            branch = line[len("branch refs/heads/"):]
            if branch.startswith("session/"):
                results.append((path, branch))
            path = None
        elif line == "":
            path = None
    return results


def _find_lockfile_for_worktree(sessions_dir: Path, wt_path: Path) -> Path | None:
    """Return the lockfile that points to this worktree, or None."""
    if not sessions_dir.exists():
        return None
    for p in sessions_dir.glob("*.json"):
        try:
            lf = sl.read_lockfile(p)
        except (ValueError, KeyError):
            continue
        if lf.worktree_path == str(wt_path):
            return p
    return None


def sweep_session_worktrees(*, repo_root: Path) -> list[str]:
    """Remove worktrees whose session/ branch is merged + clean + PID dead.

    Returns the list of removed worktree paths (stringified). Conservative:
    a worktree is removed ONLY if (a) its branch is merged, (b) its index
    is clean, AND (c) a lockfile exists that points at this worktree and
    whose PID is dead. A worktree with no matching lockfile is left alone
    — it may be a user-created session/* checkout we should not touch.
    """
    removed: list[str] = []
    sessions_dir = repo_root / ".harness" / "sessions"
    merged_raw = _git_out(["branch", "--merged"], repo_root)
    merged = {b.strip().lstrip("*+ ").strip() for b in merged_raw.splitlines()}
    for wt_path, branch in _worktree_branches(repo_root):
        if branch not in merged:
            print(f"sweep: leaving {wt_path} (branch {branch} unmerged)",
                  file=sys.stderr)
            continue
        if _git_out(["status", "--porcelain"], wt_path).strip():
            print(f"sweep: leaving {wt_path} (uncommitted changes)",
                  file=sys.stderr)
            continue
        matched_lf = _find_lockfile_for_worktree(sessions_dir, wt_path)
        if matched_lf is None:
            print(f"sweep: leaving {wt_path} (no matching lockfile; "
                  "may be user-created)", file=sys.stderr)
            continue
        try:
            lf = sl.read_lockfile(matched_lf)
        except (ValueError, KeyError):
            print(f"sweep: leaving {wt_path} (lockfile unreadable)",
                  file=sys.stderr)
            continue
        if sl.is_pid_alive(lf.pid):
            print(f"sweep: leaving {wt_path} (pid {lf.pid} alive)",
                  file=sys.stderr)
            continue
        rc = subprocess.call(
            ["git", "worktree", "remove", str(wt_path)], cwd=repo_root,
        )
        if rc != 0:
            print(f"sweep: git worktree remove failed for {wt_path}",
                  file=sys.stderr)
            continue
        subprocess.call(["git", "branch", "-d", branch], cwd=repo_root)
        matched_lf.unlink(missing_ok=True)
        removed.append(str(wt_path))
    return removed


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
            swept = sweep_session_worktrees(repo_root=REPO_ROOT)
            if swept:
                print(f"sweep: removed {len(swept)} session worktree(s)", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"sweep: skipped ({exc})", file=sys.stderr)
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
