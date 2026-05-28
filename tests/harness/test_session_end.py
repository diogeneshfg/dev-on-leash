"""leash-session-end teardown tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.harness import session_lockfile as sl
from scripts.harness.session_new import create_worktree
from scripts.harness.session_end import end_session, SessionEndError


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _plant_pending(repo: Path, pid: int) -> Path:
    sessions = repo / ".harness" / "sessions"
    lf = sl.Lockfile(
        schema=1, pid=pid, started_at="x", session_id="s",
        primary_cwd=str(repo), state=sl.STATE_PENDING_WORKTREE,
        worktree_path=None, worktree_branch=None,
    )
    sl.write_lockfile(sessions / f"{pid}.json", lf)
    return sessions / f"{pid}.json"


def test_removes_clean_merged_worktree_and_lockfile(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    subprocess.check_call(
        ["git", "merge", "--no-ff", info.worktree_branch, "-m", "merge"], cwd=repo,
    )
    end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)
    assert not info.worktree_path.exists()
    assert not (repo / ".harness" / "sessions" / f"{os.getpid()}.json").exists()
    branches = subprocess.check_output(["git", "branch"], cwd=repo, text=True)
    assert info.worktree_branch not in branches


def test_refuses_on_dirty_worktree(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    (info.worktree_path / "dirty.txt").write_text("uncommitted", encoding="utf-8")
    with pytest.raises(SessionEndError, match="uncommitted"):
        end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)
    assert info.worktree_path.exists()


def test_refuses_on_unmerged_branch_without_keep(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    (info.worktree_path / "new.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=info.worktree_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=info.worktree_path)
    with pytest.raises(SessionEndError, match="unmerged"):
        end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)


def test_missing_worktree_dir_still_deletes_merged_branch(tmp_path: Path):
    """If the user manually removed the worktree directory but the
    session/* branch is still around and merged, end_session must
    delete the branch — not leak it. Regression: previously this path
    pruned + unlinked the lockfile and returned without touching the
    branch.
    """
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    subprocess.check_call(
        ["git", "merge", "--no-ff", info.worktree_branch, "-m", "merge"], cwd=repo,
    )
    # Simulate the user deleting the worktree directory by hand.
    import shutil
    shutil.rmtree(info.worktree_path)
    end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)
    branches = subprocess.check_output(["git", "branch"], cwd=repo, text=True)
    assert info.worktree_branch not in branches, (
        "branch should be deleted when wt dir is gone but branch was merged"
    )
    assert not (repo / ".harness" / "sessions" / f"{os.getpid()}.json").exists()


def test_missing_worktree_dir_refuses_unmerged_branch_without_keep(tmp_path: Path):
    """If wt dir is gone and the branch is unmerged, the missing-wt
    path must still refuse without --keep-branch, matching the normal
    path's strictness."""
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    (info.worktree_path / "n.txt").write_text("wip\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=info.worktree_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=info.worktree_path)
    import shutil
    shutil.rmtree(info.worktree_path)
    with pytest.raises(SessionEndError, match="unmerged"):
        end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=False)


def test_keep_branch_skips_merge_check(tmp_path: Path):
    parent = tmp_path / "parent"
    parent.mkdir()
    repo = parent / "myproj"
    _init_git_repo(repo)
    _plant_pending(repo, os.getpid())
    info = create_worktree(repo_root=repo, self_pid=os.getpid())
    (info.worktree_path / "new.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=info.worktree_path)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=info.worktree_path)
    end_session(repo_root=repo, self_pid=os.getpid(), keep_branch=True)
    assert not info.worktree_path.exists()
    branches = subprocess.check_output(["git", "branch"], cwd=repo, text=True)
    assert info.worktree_branch in branches.replace("*", "").split()
