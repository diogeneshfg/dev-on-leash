"""PreToolUse-gate tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_gate import decide, Decision


def _write_lf(sessions_dir: Path, pid: int, state: str,
              cwd: str, worktree_path: str | None = None) -> None:
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id="s",
        primary_cwd=cwd, state=state,
        worktree_path=worktree_path, worktree_branch=None,
    )
    sl.write_lockfile(sessions_dir / f"{pid}.json", lf)


def test_no_lockfile_allows(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    sessions_dir.mkdir(parents=True)
    d = decide(
        sessions_dir=sessions_dir, self_pid=99999,
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is True


def test_primary_state_allows(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PRIMARY, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Write", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is True


def test_pending_worktree_denies_edit(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PENDING_WORKTREE, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is False
    assert "/leash-session-new" in d.reason


def test_pending_resolution_also_denies(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PENDING_RESOLUTION, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="MultiEdit", tool_input={"file_path": str(tmp_path / "x.py")},
    )
    assert d.allow is False


def test_in_worktree_allows_edit_inside(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_lf(sessions_dir, os.getpid(), sl.STATE_IN_WORKTREE,
              str(tmp_path), worktree_path=str(wt))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Edit", tool_input={"file_path": str(wt / "y.py")},
    )
    assert d.allow is True


def test_in_worktree_denies_edit_outside(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_lf(sessions_dir, os.getpid(), sl.STATE_IN_WORKTREE,
              str(tmp_path), worktree_path=str(wt))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "outside.py")},
    )
    assert d.allow is False
    assert str(wt) in d.reason


def test_unknown_tool_name_allows(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    _write_lf(sessions_dir, os.getpid(), sl.STATE_PENDING_WORKTREE, str(tmp_path))
    d = decide(
        sessions_dir=sessions_dir, self_pid=os.getpid(),
        tool_name="Bash", tool_input={"command": "ls"},
    )
    assert d.allow is True
