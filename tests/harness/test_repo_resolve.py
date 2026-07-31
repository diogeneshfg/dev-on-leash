"""Tests for the shared path->repo resolver."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.repo_resolve import (
    RepoResolveError,
    nearest_existing_dir,
    paths_equal,
    resolve_repo,
    validate_repo_root,
    workspace_candidates,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_repo(path: Path, default: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", default)
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _add_worktree(repo: Path, slug: str, branch: str) -> Path:
    wt = repo / ".worktrees" / slug
    _git(repo, "worktree", "add", "-b", branch, str(wt), "main")
    return wt


# --- paths_equal / nearest_existing_dir -------------------------------------

def test_paths_equal_normalizes_case_per_platform(tmp_path: Path):
    d = tmp_path / "Repo"
    d.mkdir()
    import os
    same = paths_equal(d, Path(str(d).upper()))
    # On Windows normcase folds case -> equal; on POSIX they differ.
    assert same == (os.path.normcase("A") == os.path.normcase("a"))


def test_nearest_existing_dir_walks_up_through_missing_leaves(tmp_path: Path):
    missing = tmp_path / "a" / "b" / "c" / "new.py"
    assert nearest_existing_dir(missing) == tmp_path


def test_nearest_existing_dir_for_existing_file_is_its_parent(tmp_path: Path):
    f = tmp_path / "x.txt"
    f.write_text("x", encoding="utf-8")
    assert nearest_existing_dir(f) == tmp_path


# --- resolve_repo ------------------------------------------------------------

def test_resolve_repo_main_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    info = resolve_repo(repo / "seed")
    assert info is not None
    assert paths_equal(info.main_worktree, repo)
    assert paths_equal(info.toplevel, repo)
    assert info.is_linked is False


def test_resolve_repo_linked_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "sluga", "feat/sluga")
    info = resolve_repo(wt / "seed")
    assert info is not None
    assert info.is_linked is True
    assert paths_equal(info.main_worktree, repo)
    assert paths_equal(info.toplevel, wt)


def test_resolve_repo_new_path_in_new_subdir(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    info = resolve_repo(repo / "newdir" / "deeper" / "new.py")
    assert info is not None
    assert paths_equal(info.main_worktree, repo)


def test_resolve_repo_outside_any_repo(tmp_path: Path):
    assert resolve_repo(tmp_path / "plain.txt") is None


def test_resolve_repo_git_unusable_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-dir"))
    with pytest.raises(RepoResolveError):
        resolve_repo(tmp_path)


# --- validate_repo_root -------------------------------------------------------

def test_validate_accepts_main_toplevel(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    assert paths_equal(validate_repo_root(repo), repo)


def test_validate_refuses_subdirectory(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    (repo / "sub").mkdir()
    with pytest.raises(RepoResolveError, match="toplevel"):
        validate_repo_root(repo / "sub")


def test_validate_refuses_non_repo(tmp_path: Path):
    with pytest.raises(RepoResolveError, match="not inside a git repository"):
        validate_repo_root(tmp_path)


def test_validate_refuses_linked_worktree(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = _add_worktree(repo, "sluga", "feat/sluga")
    with pytest.raises(RepoResolveError, match="linked worktree"):
        validate_repo_root(wt)


# --- workspace_candidates -----------------------------------------------------

def test_candidates_parent_folder_layout(tmp_path: Path):
    # session rooted at the workspace folder itself
    _init_repo(tmp_path / "repo-a")
    _init_repo(tmp_path / "repo-b")
    got = workspace_candidates(tmp_path)
    assert [p.name for p in got] == ["repo-a", "repo-b"]


def test_candidates_leash_managed_siblings(tmp_path: Path):
    # session rooted in one of several leash-managed sibling repos
    a = tmp_path / "repo-a"
    b = tmp_path / "repo-b"
    _init_repo(a)
    _init_repo(b)
    for r in (a, b):
        (r / ".harness").mkdir()
        (r / ".harness" / "branches.yaml").write_text("base: main\n", encoding="utf-8")
    got = workspace_candidates(a)
    assert [p.name for p in got] == ["repo-a", "repo-b"]


def test_no_candidates_for_plain_siblings(tmp_path: Path):
    # sibling repos WITHOUT .harness must not trigger the refusal
    a = tmp_path / "repo-a"
    _init_repo(a)
    _init_repo(tmp_path / "repo-b")
    assert workspace_candidates(a) == []


def test_no_candidates_single_repo(tmp_path: Path):
    a = tmp_path / "only"
    _init_repo(a)
    assert workspace_candidates(a) == []
