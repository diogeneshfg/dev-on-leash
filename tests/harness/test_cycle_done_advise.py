"""cycle_done advisory-reminder tests for proactive <type>/<slug> worktrees."""
from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.harness.cycle_done import advise_merged_worktrees


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "t@t"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "t"], cwd=path)
    (path / "README").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _add_worktree(repo: Path, rel_dir: str, branch: str) -> Path:
    wt = repo / rel_dir
    subprocess.check_call(
        ["git", "worktree", "add", str(wt), "-b", branch, "main"], cwd=repo,
    )
    return wt


def test_advises_merged_feature_worktree_without_removing(tmp_path: Path):
    repo = tmp_path / "p"
    _init_git_repo(repo)
    wt = _add_worktree(repo, ".worktrees/foo", "feat/foo")
    # A fresh branch off main with no extra commits is already merged.
    reminders = advise_merged_worktrees(repo_root=repo)
    assert any("feat/foo" in r for r in reminders), reminders
    assert any(str(wt) in r for r in reminders), reminders
    # The emitted command quotes the path so it copy-pastes verbatim.
    assert any(f'"{wt}"' in r for r in reminders), reminders
    # Advisory only: the worktree is NOT removed.
    assert wt.exists()


def test_advisory_path_is_quoted_for_spaces(tmp_path: Path):
    # Paths with spaces (this repo lives under ".../Python Projects/...") must
    # be double-quoted so the suggested `git worktree remove` runs verbatim.
    repo = tmp_path / "p"
    _init_git_repo(repo)
    wt = _add_worktree(repo, ".worktrees/a b", "feat/space-test")
    reminders = advise_merged_worktrees(repo_root=repo)
    matching = [r for r in reminders if "feat/space-test" in r]
    assert matching, reminders
    assert all(f'remove "{wt}"' in r for r in matching), matching


def test_no_advice_for_unmerged_feature_worktree(tmp_path: Path):
    repo = tmp_path / "p"
    _init_git_repo(repo)
    wt = _add_worktree(repo, ".worktrees/bar", "feat/bar")
    (wt / "x.txt").write_text("hi\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    reminders = advise_merged_worktrees(repo_root=repo)
    assert not any("feat/bar" in r for r in reminders), reminders


def test_no_advice_for_main_checkout(tmp_path: Path):
    # The primary checkout (on main, no "/" in branch name) must never be
    # advised for removal.
    repo = tmp_path / "p"
    _init_git_repo(repo)
    reminders = advise_merged_worktrees(repo_root=repo)
    assert reminders == [], reminders


def test_no_advice_for_primary_checkout_on_feature_branch(tmp_path: Path):
    # Dogfood regression: from the PRIMARY checkout on a feature branch, HEAD's
    # branch has a "/" and `git branch --merged` lists it (merged into itself).
    # With no .worktrees/ worktree present, the function must NOT advise
    # removing the primary checkout you are standing in.
    repo = tmp_path / "p"
    _init_git_repo(repo)
    subprocess.check_call(["git", "checkout", "-q", "-b", "feat/current"], cwd=repo)
    reminders = advise_merged_worktrees(repo_root=repo)
    assert reminders == [], reminders


def test_ignores_session_worktrees(tmp_path: Path):
    # session/* worktrees are auto-swept elsewhere; advisory must skip them.
    repo = tmp_path / "p"
    _init_git_repo(repo)
    _add_worktree(repo, ".worktrees/sess", "session/abc123")
    reminders = advise_merged_worktrees(repo_root=repo)
    assert not any("session/abc123" in r for r in reminders), reminders


def test_advises_branch_merged_into_declared_target_not_head(tmp_path: Path):
    """Advisory must agree with finish_work: merged into dev while HEAD
    is on main still earns a clean-up reminder."""
    repo = tmp_path / "p"
    _init_git_repo(repo)
    subprocess.check_call(["git", "branch", "dev"], cwd=repo)
    wt = _add_worktree(repo, ".worktrees/x", "feat/x")
    (wt / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=wt)
    subprocess.check_call(["git", "commit", "-q", "-m", "wip"], cwd=wt)
    subprocess.check_call(["git", "fetch", ".", "feat/x:dev"], cwd=repo)
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(
        "merge_target: dev\nlong_lived: [dev]\n", encoding="utf-8")
    reminders = advise_merged_worktrees(repo_root=repo)
    assert any("feat/x" in r for r in reminders), reminders


def test_advisory_quiet_on_malformed_config(tmp_path: Path):
    repo = tmp_path / "p"
    _init_git_repo(repo)
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text("bogus: 1\n", encoding="utf-8")
    # advisory never raises — enforcement (finish_work) surfaces the error
    assert advise_merged_worktrees(repo_root=repo) == []
