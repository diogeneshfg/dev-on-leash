"""cycle_done worktree-sweep tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.cycle_done import sweep_session_worktrees


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _make_wt(repo: Path, sid: str) -> tuple[Path, str]:
    wt = repo.parent / f"{repo.name}--session-{sid}"
    branch = f"session/{sid}"
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", branch, "HEAD"], cwd=repo,
    )
    return wt, branch


def test_removes_clean_merged_dead_pid(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "aaa111")
    subprocess.check_call(["git", "merge", "--no-ff", branch, "-m", "m"], cwd=repo)
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    lf = sl.Lockfile(
        schema=1, pid=proc.pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_IN_WORKTREE,
        worktree_path=str(wt), worktree_branch=branch,
    )
    sl.write_lockfile(repo / ".harness" / "sessions" / f"{proc.pid}.json", lf)

    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) in removed
    assert not wt.exists()


def test_leaves_unmerged(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "bbb222")
    (wt / "x.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()
    lf = sl.Lockfile(
        schema=1, pid=proc.pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_IN_WORKTREE,
        worktree_path=str(wt), worktree_branch=branch,
    )
    sl.write_lockfile(repo / ".harness" / "sessions" / f"{proc.pid}.json", lf)

    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) not in removed
    assert wt.exists()


def test_leaves_live_pid_even_if_merged(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "ccc333")
    subprocess.check_call(["git", "merge", "--no-ff", branch, "-m", "m"], cwd=repo)
    lf = sl.Lockfile(
        schema=1, pid=os.getpid(), started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_IN_WORKTREE,
        worktree_path=str(wt), worktree_branch=branch,
    )
    sl.write_lockfile(repo / ".harness" / "sessions" / f"{os.getpid()}.json", lf)

    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) not in removed
    assert wt.exists()


def test_leaves_worktree_with_no_lockfile(tmp_path: Path):
    """A session/* worktree with no matching lockfile is user-created;
    sweep must leave it alone. Spec §5 requires lockfile-dead, not
    lockfile-absent.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "p"
    _init_git_repo(repo)
    wt, branch = _make_wt(repo, "ddd444")
    subprocess.check_call(["git", "merge", "--no-ff", branch, "-m", "m"], cwd=repo)
    removed = sweep_session_worktrees(repo_root=repo)
    assert str(wt) not in removed
    assert wt.exists()
