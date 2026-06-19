"""Tests for the stateless leash-finish-work backend."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.finish_work import finish_work, FinishWorkError


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _add_worktree(repo: Path, slug: str, branch: str) -> Path:
    wt = repo / ".worktrees" / slug
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", branch, "main"], cwd=repo)
    return wt


def test_removes_merged_clean_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    # branch has no new commits → trivially merged into main
    branch = finish_work(repo_root=repo, slug="feat-x")
    assert branch == "feat/x"
    assert not wt.exists()


def test_refuses_dirty_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(FinishWorkError, match="uncommitted"):
        finish_work(repo_root=repo, slug="feat-x")
    assert wt.exists()


def test_refuses_unmerged_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    with pytest.raises(FinishWorkError, match="unmerged"):
        finish_work(repo_root=repo, slug="feat-x")


def test_keep_branch_skips_merge_check(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    branch = finish_work(repo_root=repo, slug="feat-x", keep_branch=True)
    assert branch == "feat/x"
    assert not wt.exists()
    # branch still present
    out = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert "feat/x" in out


def test_refuses_main_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    with pytest.raises(FinishWorkError):
        finish_work(repo_root=repo, worktree_path=str(repo))


def test_requires_a_name(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    with pytest.raises(FinishWorkError, match="name the worktree"):
        finish_work(repo_root=repo)
