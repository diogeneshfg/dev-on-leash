"""Tests for the .harness/branches.yaml reader and merge proof."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.branches import (
    BranchConfig,
    BranchConfigError,
    detect_default_branch,
    load_branch_config,
    prove_merged,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_repo(path: Path, default: str = "main") -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", default)
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _write_cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


# --- defaults ---------------------------------------------------------------

def test_missing_file_gives_current_behavior(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    cfg = load_branch_config(repo)
    assert cfg.base == "main"
    assert cfg.merge_target == "main"
    assert cfg.protected == frozenset({"main", "master"})


def test_detect_default_branch_master(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo, default="master")
    assert detect_default_branch(repo) == "master"
    assert load_branch_config(repo).base == "master"


# --- valid config -----------------------------------------------------------

def test_full_config(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: prod\nmerge_target: dev\nlong_lived: [dev, qa, homol, prod]\n")
    cfg = load_branch_config(repo)
    assert cfg.base == "prod"
    assert cfg.merge_target == "dev"
    assert cfg.protected == frozenset({"dev", "qa", "homol", "prod", "main", "master"})


def test_partial_config_falls_back_to_default(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: [dev]\n")
    cfg = load_branch_config(repo)
    assert cfg.base == "main"
    assert cfg.merge_target == "main"
    assert "dev" in cfg.protected


# --- malformed config: hard errors -------------------------------------------

def test_unknown_key_fails_loud(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: main\nbogus: 1\n")
    with pytest.raises(BranchConfigError, match="unknown key.*bogus"):
        load_branch_config(repo)


def test_base_not_in_long_lived_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: prod\nlong_lived: [dev]\n")
    with pytest.raises(BranchConfigError, match="base.*prod"):
        load_branch_config(repo)


def test_merge_target_not_in_long_lived_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "merge_target: qa\nlong_lived: [dev]\n")
    with pytest.raises(BranchConfigError, match="merge_target.*qa"):
        load_branch_config(repo)


@pytest.mark.parametrize("bad", ["feat/x", "-dev", "a b", ""])
def test_bad_ref_names_rejected(tmp_path: Path, bad: str):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, f'long_lived: ["{bad}"]\n')
    with pytest.raises(BranchConfigError):
        load_branch_config(repo)


def test_invalid_yaml_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: [unclosed\n")
    with pytest.raises(BranchConfigError, match="branches.yaml"):
        load_branch_config(repo)


def test_non_mapping_top_level_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "- just\n- a list\n")
    with pytest.raises(BranchConfigError, match="mapping"):
        load_branch_config(repo)


def test_long_lived_scalar_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: dev\n")
    with pytest.raises(BranchConfigError, match="must be a list"):
        load_branch_config(repo)


def test_base_non_string_rejected(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: 123\n")
    with pytest.raises(BranchConfigError):
        load_branch_config(repo)


# --- prove_merged -------------------------------------------------------------

def test_prove_merged_local_target(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "dev")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--no-ff", "feat/x", "-m", "merge")
    _git(repo, "checkout", "-q", "main")
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    cfg = load_branch_config(repo)
    # merged into dev, HEAD is on main — proof must still succeed
    assert prove_merged(repo, "feat/x", cfg) == "refs/heads/dev"


def test_prove_merged_remote_tracking_only(tmp_path: Path):
    # origin/dev has the merge; local dev is stale (still at seed)
    origin = tmp_path / "origin"
    _init_repo(origin)
    _git(origin, "checkout", "-q", "-b", "dev")
    _git(origin, "checkout", "-q", "main")

    repo = tmp_path / "r"
    subprocess.check_call(["git", "clone", "-q", str(origin), str(repo)])
    _git(repo, "config", "user.email", "d@d")
    _git(repo, "config", "user.name", "d")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "push", "-q", "origin", "feat/x:dev")  # lands in origin/dev
    _git(repo, "checkout", "-q", "main")
    _git(repo, "fetch", "-q", "origin")
    _write_cfg(repo, "merge_target: dev\nlong_lived: [dev]\n")
    cfg = load_branch_config(repo)
    assert prove_merged(repo, "feat/x", cfg) == "refs/remotes/origin/dev"


def test_prove_merged_unmerged_is_none(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "f").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "wip")
    _git(repo, "checkout", "-q", "main")
    cfg = load_branch_config(repo)
    assert prove_merged(repo, "feat/x", cfg) is None


# --- workflow key -------------------------------------------------------------

def test_workflow_defaults_to_worktree_when_file_missing(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    assert load_branch_config(repo).workflow == "worktree"


def test_workflow_defaults_to_worktree_when_key_absent(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: main\n")
    assert load_branch_config(repo).workflow == "worktree"


def test_workflow_empty_value_defaults_not_errors(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "workflow:\n")
    assert load_branch_config(repo).workflow == "worktree"


def test_workflow_branch_accepted(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "workflow: branch\n")
    assert load_branch_config(repo).workflow == "branch"


def test_workflow_junk_is_hard_error(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "workflow: yolo\n")
    with pytest.raises(BranchConfigError, match="workflow"):
        load_branch_config(repo)


def test_work_branch_re_exported():
    from scripts.harness.branches import WORK_BRANCH_RE
    assert WORK_BRANCH_RE.match("feat/my-slug")
    assert not WORK_BRANCH_RE.match("dev")
    assert not WORK_BRANCH_RE.match("hotfix/x")
