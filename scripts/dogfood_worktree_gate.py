#!/usr/bin/env python3
"""Dogfood the worktree gate on a throwaway repo.

Steps:
  1. init a git repo (main worktree).
  2. Gate an Edit targeting the main tree -> assert DENY (names leash-start-work).
  3. Add a linked worktree; gate an Edit inside it -> assert ALLOW.
  4. Plant the one-shot marker; gate a main-tree Edit -> assert ALLOW, marker
     consumed, exceptions.log appended. A second main-tree Edit -> assert DENY.
  5. Teardown.

Exits 0 only if every step asserted clean. Used by smoke_e2e.py and as the
verify command for the dogfood task.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.harness.session_gate import decide, list_worktrees  # noqa: E402
from scripts.harness.allow_main_write import write_marker  # noqa: E402


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="dol-wtgate-"))
    repo = parent / "throwaway"
    try:
        _init_repo(repo)
        harness = repo / ".harness"
        marker = harness / "allow-main-write"
        log = harness / "exceptions.log"

        wts = list_worktrees(repo)
        assert wts is not None and wts[0] == repo.resolve(), "main worktree first"

        d_main = decide(
            tool_name="Edit", tool_input={"file_path": str(repo / "README.md")},
            worktrees=wts, marker_path=marker, log_path=log,
        )
        assert not d_main.allow, "gate must deny main-tree write"
        assert "/leash-start-work" in d_main.reason

        wt = repo / ".worktrees" / "feat-x"
        subprocess.check_call(
            ["git", "worktree", "add", str(wt), "-b", "feat/x", "main"], cwd=repo)
        wts2 = list_worktrees(repo)
        d_wt = decide(
            tool_name="Edit", tool_input={"file_path": str(wt / "y.py")},
            worktrees=wts2, marker_path=marker, log_path=log,
        )
        assert d_wt.allow, f"gate must allow inside worktree: {d_wt.reason}"

        write_marker(harness_dir=harness, reason="dogfood")
        d_escape = decide(
            tool_name="Edit", tool_input={"file_path": str(repo / "README.md")},
            worktrees=wts2, marker_path=marker, log_path=log,
        )
        assert d_escape.allow, "one-shot marker must allow"
        assert not marker.exists(), "marker must be consumed"
        assert log.exists() and "main-write" in log.read_text(encoding="utf-8")

        d_again = decide(
            tool_name="Edit", tool_input={"file_path": str(repo / "README.md")},
            worktrees=wts2, marker_path=marker, log_path=log,
        )
        assert not d_again.allow, "second main write must deny after consume"

        print("WORKTREE-GATE DOGFOOD PASS")
        return 0
    except AssertionError as exc:
        print(f"WORKTREE-GATE DOGFOOD FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
