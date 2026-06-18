"""Behavioural tests for scripts.harness.session_new.create_worktree.

The session-leash worktree is the *independent-developer* model: a second
session doing distinct work should branch from the trunk (main/master), not
from whatever feature branch the primary checkout happens to sit on. Basing
off HEAD would make session/<id> carry the primary branch's commits, so it
could never merge to main independently and would strand if that branch were
rebased or abandoned.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness import session_new


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _init_repo(root: Path, trunk: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(["init"], root)
    _git(["symbolic-ref", "HEAD", f"refs/heads/{trunk}"], root)
    _git(["config", "user.email", "t@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "README.md").write_text("trunk\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "initial on trunk"], root)


def _diverge_onto_feature(root: Path, branch: str) -> None:
    """Checkout a feature branch with a commit the trunk does not have."""
    _git(["checkout", "-b", branch], root)
    (root / "feature.txt").write_text("wip\n", encoding="utf-8")
    _git(["add", "."], root)
    _git(["commit", "-m", "feature work"], root)


def _write_pending_lockfile(root: Path, pid: int) -> None:
    lf = sl.Lockfile(
        schema=sl.SCHEMA,
        pid=pid,
        started_at="2026-01-01T00:00:00Z",
        session_id="test-session",
        primary_cwd=str(root),
        state=sl.STATE_PENDING_WORKTREE,
        worktree_path=None,
        worktree_branch=None,
    )
    sl.write_lockfile(root / ".harness" / "sessions" / f"{pid}.json", lf)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path / "repo"


def _cleanup_worktree(info) -> None:
    if info and info.worktree_path and Path(info.worktree_path).exists():
        # Best-effort; the test repo lives under tmp_path and is removed anyway.
        pass


def test_branches_from_main_not_head(repo: Path):
    _init_repo(repo, "main")
    main_tip = _git(["rev-parse", "main"], repo)
    _diverge_onto_feature(repo, "feat/in-progress")
    feat_tip = _git(["rev-parse", "HEAD"], repo)
    assert main_tip != feat_tip
    pid = os.getpid()
    _write_pending_lockfile(repo, pid)

    info = session_new.create_worktree(repo_root=repo, self_pid=pid)

    new_tip = _git(["rev-parse", info.worktree_branch], repo)
    assert new_tip == main_tip
    assert new_tip != feat_tip


def test_branches_from_master_when_no_main(repo: Path):
    _init_repo(repo, "master")
    master_tip = _git(["rev-parse", "master"], repo)
    _diverge_onto_feature(repo, "feat/in-progress")
    feat_tip = _git(["rev-parse", "HEAD"], repo)
    assert master_tip != feat_tip
    pid = os.getpid()
    _write_pending_lockfile(repo, pid)

    info = session_new.create_worktree(repo_root=repo, self_pid=pid)

    new_tip = _git(["rev-parse", info.worktree_branch], repo)
    assert new_tip == master_tip


def test_falls_back_to_head_when_no_trunk(repo: Path):
    # No main/master at all — escape hatch must still produce a worktree.
    _init_repo(repo, "develop")
    _git(["checkout", "-b", "feat/in-progress"], repo)
    (repo / "feature.txt").write_text("wip\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "feature work"], repo)
    head_tip = _git(["rev-parse", "HEAD"], repo)
    pid = os.getpid()
    _write_pending_lockfile(repo, pid)

    info = session_new.create_worktree(repo_root=repo, self_pid=pid)

    new_tip = _git(["rev-parse", info.worktree_branch], repo)
    assert new_tip == head_tip
