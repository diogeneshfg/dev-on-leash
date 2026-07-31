"""Gate tests: multi-repo fixture — the regression test for the field failure."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.harness.session_gate import decide, list_worktrees, main as gate_main


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


def _cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


@pytest.fixture()
def workspace(tmp_path: Path):
    """Two sibling leash-managed repos, one per mode; session rooted elsewhere."""
    wt_repo = tmp_path / "repo-worktree"
    br_repo = tmp_path / "repo-branch"
    _init_repo(wt_repo)
    _init_repo(br_repo)
    _cfg(wt_repo, "workflow: worktree\n")
    _cfg(br_repo, "workflow: branch\nlong_lived: [prod, homol, qa, dev]\n"
                  "base: prod\nmerge_target: dev\n")
    for env in ("prod", "homol", "qa", "dev"):
        _git(br_repo, "branch", env)
    return wt_repo, br_repo


def _edit(path: Path):
    return decide(tool_name="Edit", tool_input={"file_path": str(path)})


def test_worktree_repo_main_tree_denied(workspace):
    wt_repo, _ = workspace
    d = _edit(wt_repo / "seed")
    assert not d.allow
    assert "read-only" in d.reason and "--repo-root" in d.reason


def test_worktree_repo_new_subdir_write_denied(workspace):
    # regression: file creation into a not-yet-existing directory
    wt_repo, _ = workspace
    d = decide(tool_name="Write",
               tool_input={"file_path": str(wt_repo / "newdir" / "x.py")})
    assert not d.allow


def test_worktree_repo_linked_worktree_allowed(workspace):
    wt_repo, _ = workspace
    wt = wt_repo / ".worktrees" / "sluga"
    _git(wt_repo, "worktree", "add", "-b", "feat/sluga", str(wt), "main")
    assert _edit(wt / "seed").allow


def test_unmanaged_repo_untouched(tmp_path: Path):
    # a repo WITHOUT .harness (cloned dependency) must never be gated
    plain = tmp_path / "third-party"
    _init_repo(plain)
    assert _edit(plain / "seed").allow
    assert not (plain / ".harness").exists()   # and no .harness side effects


def test_branch_repo_denied_on_protected_branch(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "dev")
    d = _edit(br_repo / "seed")
    assert not d.allow
    assert "dev" in d.reason and "leash-start-work" in d.reason


def test_branch_repo_denied_on_nonconforming_branch(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "-b", "experiment")
    assert not _edit(br_repo / "seed").allow


def test_branch_repo_denied_on_detached_head(workspace):
    _, br_repo = workspace
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=br_repo, text=True).strip()
    _git(br_repo, "checkout", "-q", sha)
    assert not _edit(br_repo / "seed").allow


def test_branch_repo_allowed_on_work_branch(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "-b", "feat/demand-a", "prod")
    assert _edit(br_repo / "seed").allow


def test_branch_repo_linked_worktree_still_allowed(workspace):
    # mixed state: a branch-mode repo with a pre-flip worktree
    _, br_repo = workspace
    wt = br_repo / ".worktrees" / "old"
    _git(br_repo, "worktree", "add", "-b", "feat/old", str(wt), "main")
    _git(br_repo, "checkout", "-q", "dev")
    assert _edit(wt / "seed").allow


def test_malformed_config_denies_with_reason(workspace):
    wt_repo, _ = workspace
    _cfg(wt_repo, "workflow: yolo\n")
    d = _edit(wt_repo / "seed")
    assert not d.allow
    assert "workflow" in d.reason


def test_outside_any_repo_allowed(tmp_path: Path):
    f = tmp_path / "free.txt"
    f.write_text("x", encoding="utf-8")
    assert _edit(f).allow


def test_marker_consumed_in_target_repo(workspace):
    wt_repo, _ = workspace
    marker = wt_repo / ".harness" / "allow-main-write"
    marker.write_text(json.dumps({"schema": 1, "reason": "t"}), encoding="utf-8")
    assert _edit(wt_repo / "seed").allow
    assert not marker.exists()
    assert (wt_repo / ".harness" / "exceptions.log").exists()
    assert not _edit(wt_repo / "seed").allow  # one-shot


def test_marker_works_in_branch_mode_repo(workspace):
    _, br_repo = workspace
    _git(br_repo, "checkout", "-q", "dev")
    marker = br_repo / ".harness" / "allow-main-write"
    marker.write_text(json.dumps({"schema": 1, "reason": "t"}), encoding="utf-8")
    assert _edit(br_repo / "seed").allow
    assert not _edit(br_repo / "seed").allow


def test_main_hook_protocol(workspace, monkeypatch, capsys):
    # the code that actually runs as the PreToolUse hook
    import io, sys
    wt_repo, _ = workspace
    payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(wt_repo / "seed")},
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert gate_main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "deny"
    assert "read-only" in out["reason"]


def test_list_worktrees_on_real_repo(tmp_path: Path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=repo)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=repo)
    (repo / "seed").write_text("s\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=repo)
    wts = list_worktrees(repo)
    assert wts is not None
    assert wts[0] == repo.resolve()


def test_list_worktrees_non_repo_returns_none(tmp_path: Path):
    assert list_worktrees(tmp_path) is None
