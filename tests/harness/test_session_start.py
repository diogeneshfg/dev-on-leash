"""SessionStart-hook tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_start import run as session_start_run


def _spawn_dummy() -> subprocess.Popen:
    """A subprocess that stays alive long enough to act as a peer."""
    return subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time; sys.stdout.write('ready\\n'); sys.stdout.flush(); time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_lone_session_becomes_primary(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    rc, message = session_start_run(
        sessions_dir=sessions_dir,
        primary_cwd=str(tmp_path),
        self_pid=os.getpid(),
    )
    assert rc == 0
    assert message == ""
    lockfiles = list(sessions_dir.glob("*.json"))
    assert len(lockfiles) == 1
    lf = sl.read_lockfile(lockfiles[0])
    assert lf.state == sl.STATE_PRIMARY


def test_second_session_becomes_pending_with_message(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    peer = _spawn_dummy()
    try:
        peer.stdout.readline()
        peer_lf = sl.Lockfile(
            schema=1, pid=peer.pid, started_at="2026-01-01T00:00:00Z",
            session_id="peer", primary_cwd=str(tmp_path),
            state=sl.STATE_PRIMARY, worktree_path=None, worktree_branch=None,
        )
        sl.write_lockfile(sessions_dir / f"{peer.pid}.json", peer_lf)
        self_pid = peer.pid + 1
        rc, message = session_start_run(
            sessions_dir=sessions_dir,
            primary_cwd=str(tmp_path),
            self_pid=self_pid,
        )
        assert rc == 0
        assert "SESSION LEASH" in message
        assert "/leash-session-new" in message
        our_lf = sl.read_lockfile(sessions_dir / f"{self_pid}.json")
        assert our_lf.state == sl.STATE_PENDING_WORKTREE
    finally:
        peer.terminate()
        peer.wait(timeout=5)


def test_dead_peer_is_gc_then_we_become_primary(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    dead = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    dead.wait()
    dead_lf = sl.Lockfile(
        schema=1, pid=dead.pid, started_at="x", session_id="ghost",
        primary_cwd=str(tmp_path), state=sl.STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions_dir / f"{dead.pid}.json", dead_lf)
    rc, message = session_start_run(
        sessions_dir=sessions_dir, primary_cwd=str(tmp_path), self_pid=os.getpid(),
    )
    assert rc == 0
    assert message == ""
    assert not (sessions_dir / f"{dead.pid}.json").exists()
    our = sl.read_lockfile(sessions_dir / f"{os.getpid()}.json")
    assert our.state == sl.STATE_PRIMARY


def test_lower_pid_self_wins_primary_against_higher_peer(tmp_path: Path):
    sessions_dir = tmp_path / ".harness" / "sessions"
    peer = _spawn_dummy()
    try:
        peer.stdout.readline()
        peer_lf = sl.Lockfile(
            schema=1, pid=peer.pid, started_at="x", session_id="peer",
            primary_cwd=str(tmp_path), state=sl.STATE_PENDING_RESOLUTION,
            worktree_path=None, worktree_branch=None,
        )
        sl.write_lockfile(sessions_dir / f"{peer.pid}.json", peer_lf)
        self_pid = 1
        rc, message = session_start_run(
            sessions_dir=sessions_dir,
            primary_cwd=str(tmp_path),
            self_pid=self_pid,
        )
        assert rc == 0
        assert message == ""
        ours = sl.read_lockfile(sessions_dir / f"{self_pid}.json")
        assert ours.state == sl.STATE_PRIMARY
    finally:
        peer.terminate()
        peer.wait(timeout=5)
