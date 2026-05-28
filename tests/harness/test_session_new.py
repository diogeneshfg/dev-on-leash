"""leash-session-new worktree-creation tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_new import create_worktree, SessionNewError


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _plant_lockfile(repo: Path, pid: int, state: str) -> Path:
    sessions = repo / ".harness" / "sessions"
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=state,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions / f"{pid}.json", lf)
    return sessions / f"{pid}.json"


def test_creates_sibling_worktree_and_flips_state(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    lf_path = _plant_lockfile(repo, os.getpid(), sl.STATE_PENDING_WORKTREE)

    info = create_worktree(repo_root=repo, self_pid=os.getpid())

    assert info.worktree_path.parent == parent
    assert info.worktree_path.name.startswith("myproj--session-")
    assert info.worktree_path.exists()
    assert info.worktree_branch.startswith("session/")
    branches = subprocess.check_output(
        ["git", "branch", "--list"], cwd=repo, text=True,
    )
    assert info.worktree_branch in branches.replace("*", "").split()
    updated = sl.read_lockfile(lf_path)
    assert updated.state == sl.STATE_IN_WORKTREE
    assert updated.worktree_path == str(info.worktree_path)
    assert updated.worktree_branch == info.worktree_branch


def test_idempotent_on_already_in_worktree(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_lockfile(repo, os.getpid(), sl.STATE_PENDING_WORKTREE)
    info1 = create_worktree(repo_root=repo, self_pid=os.getpid())
    info2 = create_worktree(repo_root=repo, self_pid=os.getpid())
    assert info1.worktree_path == info2.worktree_path
    assert info1.worktree_branch == info2.worktree_branch


def test_errors_clearly_when_no_lockfile(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    with pytest.raises(SessionNewError, match="lockfile"):
        create_worktree(repo_root=repo, self_pid=os.getpid())
