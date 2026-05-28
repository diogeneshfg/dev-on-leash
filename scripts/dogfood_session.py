#!/usr/bin/env python3
"""Dogfood the session leash on a throwaway repo.

Steps:
  1. init a git repo + an empty .harness/sessions dir.
  2. Plant a peer lockfile claiming a LIVE pid (we spawn a sleeper).
  3. Run session_start.run(); assert resolved state is pending-worktree.
  4. Run session_gate.decide() with an Edit payload; assert deny.
  5. Run session_new.create_worktree(); assert worktree exists and
     lockfile flips to in-worktree.
  6. Re-run session_gate.decide() against a path inside the worktree;
     assert allow.
  7. Teardown: kill peer, remove worktree, remove lockfiles.

Exits 0 only if every step asserted clean. Used by smoke_e2e.py and as
the verify command for the dogfood task.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.harness import session_lockfile as sl  # noqa: E402
from scripts.harness import session_start as ss  # noqa: E402
from scripts.harness import session_gate as sg  # noqa: E402
from scripts.harness import session_new as sn  # noqa: E402


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="dol-session-"))
    repo = parent / "throwaway"
    peer = None
    try:
        _init_repo(repo)
        sessions = repo / ".harness" / "sessions"

        peer = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(60)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        peer.stdout.readline()
        peer_lf = sl.Lockfile(
            schema=1, pid=peer.pid, started_at="2026-05-28T00:00:00Z",
            session_id="peer", primary_cwd=str(repo),
            state=sl.STATE_PRIMARY, worktree_path=None, worktree_branch=None,
        )
        sl.write_lockfile(sessions / f"{peer.pid}.json", peer_lf)

        self_pid = peer.pid + 1
        rc, message = ss.run(
            sessions_dir=sessions, primary_cwd=str(repo), self_pid=self_pid,
        )
        assert rc == 0, "session_start.run returned non-zero"
        assert "SESSION LEASH" in message, "expected block message"
        our_lf = sl.read_lockfile(sessions / f"{self_pid}.json")
        assert our_lf.state == sl.STATE_PENDING_WORKTREE, our_lf.state

        d = sg.decide(
            sessions_dir=sessions, self_pid=self_pid,
            tool_name="Edit", tool_input={"file_path": str(repo / "x.py")},
        )
        assert not d.allow, "gate must deny while pending-worktree"
        assert "/leash-session-new" in d.reason

        info = sn.create_worktree(repo_root=repo, self_pid=self_pid)
        assert info.worktree_path.exists()
        assert info.worktree_branch.startswith("session/")

        d2 = sg.decide(
            sessions_dir=sessions, self_pid=self_pid,
            tool_name="Edit",
            tool_input={"file_path": str(info.worktree_path / "y.py")},
        )
        assert d2.allow, f"gate must allow inside worktree: {d2.reason}"

        d3 = sg.decide(
            sessions_dir=sessions, self_pid=self_pid,
            tool_name="Edit",
            tool_input={"file_path": str(repo / "outside.py")},
        )
        assert not d3.allow, "gate must deny edits outside the worktree"

        print("SESSION-LEASH DOGFOOD PASS")
        return 0
    except AssertionError as exc:
        print(f"SESSION-LEASH DOGFOOD FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if peer is not None:
            try:
                peer.terminate()
                peer.wait(timeout=5)
            except Exception:
                pass
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
