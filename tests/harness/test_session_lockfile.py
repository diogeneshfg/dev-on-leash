"""Lockfile-module tests for session-leash."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.harness.session_lockfile import (
    STATE_PRIMARY,
    STATE_PENDING_RESOLUTION,
    STATE_PENDING_WORKTREE,
    STATE_IN_WORKTREE,
    Lockfile,
    is_pid_alive,
    gc_dead_lockfiles,
    list_live_lockfiles,
    write_lockfile,
    read_lockfile,
    resolve_state,
)


def test_self_pid_is_alive():
    assert is_pid_alive(os.getpid())


def test_clearly_dead_pid_is_not_alive():
    # Spawn a tiny process, wait for it to exit, then probe.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    assert not is_pid_alive(proc.pid)


def test_round_trip(tmp_path: Path):
    lf = Lockfile(
        schema=1,
        pid=os.getpid(),
        started_at="2026-05-28T12:00:00Z",
        session_id="probe",
        primary_cwd=str(tmp_path),
        state=STATE_PRIMARY,
        worktree_path=None,
        worktree_branch=None,
    )
    path = tmp_path / f"{lf.pid}.json"
    write_lockfile(path, lf)
    assert path.exists()
    got = read_lockfile(path)
    assert got == lf


def test_atomic_write_no_tmp_left_behind(tmp_path: Path):
    lf = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="s",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / "1.json", lf)
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_gc_removes_only_dead_pids(tmp_path: Path):
    # Live lockfile = our pid.
    alive = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="a",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / f"{alive.pid}.json", alive)
    # Dead lockfile = freshly exited pid.
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    dead = Lockfile(
        schema=1, pid=proc.pid, started_at="y", session_id="b",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / f"{dead.pid}.json", dead)

    gc_dead_lockfiles(tmp_path)
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [f"{alive.pid}.json"]


def test_list_live_lockfiles_filters_by_cwd(tmp_path: Path):
    here = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="a",
        primary_cwd=str(tmp_path), state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    elsewhere = Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="b",
        primary_cwd="/somewhere/else", state=STATE_PRIMARY,
        worktree_path=None, worktree_branch=None,
    )
    write_lockfile(tmp_path / "a.json", here)
    write_lockfile(tmp_path / "b.json", elsewhere)
    live = list_live_lockfiles(tmp_path, primary_cwd=str(tmp_path))
    assert len(live) == 1
    assert live[0].session_id == "a"


def test_resolve_state_lone_session_becomes_primary(tmp_path: Path):
    self_pid = os.getpid()
    state = resolve_state(self_pid=self_pid, live_peer_pids=[])
    assert state == STATE_PRIMARY


def test_resolve_state_lowest_pid_wins_primary(tmp_path: Path):
    self_pid = 100
    state = resolve_state(self_pid=self_pid, live_peer_pids=[200, 300])
    assert state == STATE_PRIMARY


def test_resolve_state_higher_pid_takes_pending(tmp_path: Path):
    self_pid = 500
    state = resolve_state(self_pid=self_pid, live_peer_pids=[100, 200])
    assert state == STATE_PENDING_WORKTREE


def test_corrupt_lockfile_is_treated_as_absent(tmp_path: Path):
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    # GC and list both must not raise.
    gc_dead_lockfiles(tmp_path)
    live = list_live_lockfiles(tmp_path, primary_cwd=str(tmp_path))
    # Corrupt file should be deleted by GC.
    assert not (tmp_path / "bad.json").exists()
    assert live == []
