"""list_sessions CLI tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.list_sessions import format_sessions


def _plant(sessions_dir: Path, pid: int, cwd: str, state: str) -> None:
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id=f"s{pid}",
        primary_cwd=cwd, state=state,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions_dir / f"{pid}.json", lf)


def test_empty_sessions_dir(tmp_path: Path):
    out = format_sessions(tmp_path / "sessions", primary_cwd=str(tmp_path))
    assert out.strip() == "(no live sessions)"


def test_lists_live_only(tmp_path: Path):
    sessions = tmp_path / "sessions"
    _plant(sessions, os.getpid(), str(tmp_path), sl.STATE_PRIMARY)
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    _plant(sessions, proc.pid, str(tmp_path), sl.STATE_PENDING_WORKTREE)
    out = format_sessions(sessions, primary_cwd=str(tmp_path))
    assert str(os.getpid()) in out
    assert str(proc.pid) not in out
