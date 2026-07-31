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


def _write_cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


def test_merged_into_declared_target_while_head_on_main(tmp_path: Path):
    """The critic-found blocker: merged into dev, HEAD on main — must
    remove worktree AND delete branch (proof-based -D, not -d)."""
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    # merge feat/x into dev without touching main's checkout:
    subprocess.check_call(
        ["git", "fetch", ".", "feat/x:dev"], cwd=repo)  # fast-forward dev
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    branch = finish_work(repo_root=repo, slug="feat-x")
    assert branch == "feat/x"
    assert not wt.exists()
    out = subprocess.run(["git", "branch"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "feat/x" not in out
    audit = (repo / ".harness" / "finish_audit.log").read_text(encoding="utf-8")
    assert "branch=feat/x" in audit and "proven=refs/heads/dev" in audit


def test_unmerged_into_target_still_refused(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)
    wt = _add_worktree(repo, "feat-x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    with pytest.raises(FinishWorkError, match="not an ancestor"):
        finish_work(repo_root=repo, slug="feat-x")
    assert wt.exists(), "nothing may be removed when the proof fails"


def test_refuses_worktree_on_declared_long_lived_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: [dev]\n")
    wt = repo / ".worktrees" / "devwt"
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", "dev", "main"], cwd=repo)
    with pytest.raises(FinishWorkError, match="refusing"):
        finish_work(repo_root=repo, worktree_path=str(wt))


def test_malformed_branches_yaml_is_hard_error(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "bogus: 1\n")
    _add_worktree(repo, "feat-x", "feat/x")
    with pytest.raises(FinishWorkError, match="unknown key"):
        finish_work(repo_root=repo, slug="feat-x")


from scripts.harness.finish_work import FinishWorkError, finish_branch


def _cfg_branch(repo: Path) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(
        "workflow: branch\nlong_lived: [prod, dev]\nbase: prod\nmerge_target: dev\n",
        encoding="utf-8",
    )
    subprocess.check_call(["git", "add", ".harness"], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "cfg"], cwd=repo)


def _seed_envs(repo: Path) -> None:
    subprocess.check_call(["git", "branch", "prod"], cwd=repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)


def _work_then_merge(repo: Path) -> None:
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/w", "prod"], cwd=repo)
    (repo / "w.txt").write_text("w\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "w"], cwd=repo)
    subprocess.check_call(["git", "checkout", "-q", "dev"], cwd=repo)
    subprocess.check_call(["git", "merge", "-q", "--no-ff", "feat/w"], cwd=repo)
    subprocess.check_call(["git", "checkout", "-q", "feat/w"], cwd=repo)


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
    ).strip()


def test_finish_branch_defaults_to_head_and_ends_on_merge_target(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    got = finish_branch(repo_root=repo, branch=None)
    assert got == "feat/w"
    assert _head(repo) == "dev"          # merge_target — never prod/base
    out = subprocess.run(["git", "rev-parse", "--verify", "refs/heads/feat/w"],
                         cwd=repo, capture_output=True)
    assert out.returncode != 0           # branch deleted
    assert (repo / ".harness" / "finish_audit.log").exists()


def test_finish_branch_untracked_files_do_not_block(tmp_path):
    # the .env-style scratch file the mode was designed to tolerate
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    (repo / "scratch.env").write_text("x\n", encoding="utf-8")
    warnings: list[str] = []
    got = finish_branch(repo_root=repo, branch=None, warn=warnings.append)
    assert got == "feat/w"
    assert _head(repo) == "dev"
    assert any("scratch.env" in w for w in warnings)


def test_finish_branch_refuses_unmerged(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/u", "prod"], cwd=repo)
    (repo / "u.txt").write_text("u\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "u"], cwd=repo)
    with pytest.raises(FinishWorkError, match="unmerged"):
        finish_branch(repo_root=repo, branch=None)


def test_finish_branch_keep_branch(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/k", "prod"], cwd=repo)
    got = finish_branch(repo_root=repo, branch=None, keep_branch=True)
    assert got == "feat/k"
    assert _head(repo) == "dev"
    out = subprocess.run(["git", "rev-parse", "--verify", "refs/heads/feat/k"],
                         cwd=repo, capture_output=True)
    assert out.returncode == 0           # kept


def test_finish_branch_refuses_tracked_dirty(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    (repo / "seed").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(FinishWorkError, match="tracked changes"):
        finish_branch(repo_root=repo, branch=None)


def test_finish_branch_refuses_head_not_work_branch_and_no_arg(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    subprocess.check_call(["git", "checkout", "-q", "dev"], cwd=repo)
    with pytest.raises(FinishWorkError, match="name the branch"):
        finish_branch(repo_root=repo, branch=None)


def test_finish_branch_by_name_from_elsewhere(tmp_path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch(repo)
    _seed_envs(repo)
    _work_then_merge(repo)
    subprocess.check_call(["git", "checkout", "-q", "main"], cwd=repo)
    got = finish_branch(repo_root=repo, branch="feat/w")
    assert got == "feat/w"
    assert _head(repo) == "dev"
