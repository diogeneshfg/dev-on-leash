"""Tests for the mechanical leash-start-work backend."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.harness.start_work import StartWorkError, start_work


def _git(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "d@d")
    _git(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "seed")


def _write_cfg(repo: Path, text: str) -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(text, encoding="utf-8")


def _clone(origin: Path, dest: Path) -> None:
    subprocess.check_call(["git", "clone", "-q", str(origin), str(dest)])
    _git(dest, "config", "user.email", "d@d")
    _git(dest, "config", "user.name", "d")


def test_default_no_config_branches_from_main(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    wt = start_work(repo_root=repo, branch="feat/x")
    assert wt == repo / ".worktrees" / "x"
    assert wt.exists()
    head = _git_out(wt, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert head == "feat/x"


def test_config_base_used(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "prod")
    _git(repo, "checkout", "-q", "-b", "dev")
    (repo / "ahead").write_text("dev ahead\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "dev ahead")
    _git(repo, "checkout", "-q", "main")
    _write_cfg(repo, "base: prod\nlong_lived: [dev, prod]\n")
    wt = start_work(repo_root=repo, branch="fix/hot")
    # started from prod (== seed), not from dev
    assert not (wt / "ahead").exists()


def test_base_override_wins(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "dev")
    (repo / "ahead").write_text("dev ahead\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "dev ahead")
    _git(repo, "checkout", "-q", "main")
    _write_cfg(repo, "base: main\nlong_lived: [dev]\n")
    wt = start_work(repo_root=repo, branch="feat/y", base_override="dev")
    assert (wt / "ahead").exists()


def test_base_override_must_be_declared(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _git(repo, "branch", "topic")  # exists but not declared
    with pytest.raises(StartWorkError, match="not a declared branch"):
        start_work(repo_root=repo, branch="feat/z", base_override="topic")


def test_refuses_protected_slug(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "long_lived: [prod]\n")
    with pytest.raises(StartWorkError, match="protected"):
        start_work(repo_root=repo, branch="feat/prod")


def test_refuses_bad_branch_shape(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    with pytest.raises(StartWorkError, match="<type>/<slug>"):
        start_work(repo_root=repo, branch="feature/X_Bad")


def test_refuses_missing_base_ref(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _write_cfg(repo, "base: dev\nlong_lived: [dev]\n")  # dev declared, never created
    with pytest.raises(StartWorkError, match="no local branch and no remote-tracking"):
        start_work(repo_root=repo, branch="feat/x")


def test_behind_base_starts_from_remote_with_no_upstream(tmp_path: Path):
    origin = tmp_path / "origin"
    _init_repo(origin)
    repo = tmp_path / "r"
    _clone(origin, repo)
    # origin/main advances after the clone → local main is behind
    (origin / "newer").write_text("newer\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "newer")
    warnings: list[str] = []
    wt = start_work(repo_root=repo, branch="feat/x", warn=warnings.append)
    assert (wt / "newer").exists(), "must start from origin/main, not stale local"
    assert any("behind" in w for w in warnings)
    # --no-track: the feature branch must have no upstream
    rc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "feat/x@{upstream}"],
        cwd=repo, capture_output=True,
    ).returncode
    assert rc != 0, "feature branch must not track origin/main"


def test_diverged_base_refused(tmp_path: Path):
    origin = tmp_path / "origin"
    _init_repo(origin)
    repo = tmp_path / "r"
    _clone(origin, repo)
    # local main gains a commit AND origin/main gains a different one
    (repo / "local").write_text("local\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "local")
    (origin / "remote").write_text("remote\n", encoding="utf-8")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "remote")
    with pytest.raises(StartWorkError, match="diverged"):
        start_work(repo_root=repo, branch="feat/x")


def test_no_remote_warns_and_proceeds(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    warnings: list[str] = []
    wt = start_work(repo_root=repo, branch="feat/x", warn=warnings.append)
    assert wt.exists()
    assert any("no remote" in w for w in warnings)


def test_warns_when_worktrees_not_ignored(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    warnings: list[str] = []
    start_work(repo_root=repo, branch="feat/x", warn=warnings.append)
    assert any(".worktrees/" in w and "gitignore" in w.lower() for w in warnings)


def test_refuses_existing_worktree_dir(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    start_work(repo_root=repo, branch="feat/x")
    with pytest.raises(StartWorkError, match="already exists"):
        start_work(repo_root=repo, branch="fix/x")


def test_start_work_prints_echo_line(tmp_path: Path, capsys):
    repo = tmp_path / "r"
    _init_repo(repo)
    start_work(repo_root=repo, branch="feat/echo-check")
    out = capsys.readouterr().out
    assert "repo: " in out and "base: main" in out and "mode: worktree" in out


def _cfg_branch_mode(repo: Path, extra: str = "") -> None:
    (repo / ".harness").mkdir(exist_ok=True)
    (repo / ".harness" / "branches.yaml").write_text(
        "workflow: branch\n" + extra, encoding="utf-8"
    )


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo, text=True
    ).strip()


def test_branch_mode_checks_out_work_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    got = start_work(repo_root=repo, branch="feat/x-one")
    assert got == repo
    assert _head(repo) == "feat/x-one"
    assert not (repo / ".worktrees").exists()


def test_branch_mode_cuts_from_configured_base(tmp_path: Path):
    # the field failure: the branch MUST come off the declared base
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "prod"], cwd=repo)
    (repo / "main-only.txt").write_text("m\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-q", "-m", "main moves on"], cwd=repo)
    _cfg_branch_mode(repo, "base: prod\nlong_lived: [prod]\n")
    start_work(repo_root=repo, branch="feat/from-prod")
    assert _head(repo) == "feat/from-prod"
    prod_sha = subprocess.check_output(
        ["git", "rev-parse", "prod"], cwd=repo, text=True).strip()
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert head_sha == prod_sha        # cut from prod, not from main's tip


def test_branch_mode_behind_base_uses_remote_no_upstream(tmp_path: Path):
    # mirror of the worktree-mode no-track test: stale local base
    origin = tmp_path / "origin"
    _init_repo(origin)
    subprocess.check_call(["git", "branch", "prod"], cwd=origin)
    clone = tmp_path / "clone"
    subprocess.check_call(["git", "clone", "-q", str(origin), str(clone)])
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=clone)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=clone)
    subprocess.check_call(["git", "checkout", "-q", "-b", "prod", "origin/prod"],
                          cwd=clone)
    subprocess.check_call(["git", "checkout", "-q", "main"], cwd=clone)
    # advance origin/prod so the clone's local prod is behind
    subprocess.check_call(["git", "checkout", "-q", "prod"], cwd=origin)
    (origin / "newer.txt").write_text("n\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=origin)
    subprocess.check_call(["git", "commit", "-q", "-m", "newer"], cwd=origin)
    _cfg_branch_mode(clone, "base: prod\nlong_lived: [prod]\n")
    warnings: list[str] = []
    start_work(repo_root=clone, branch="feat/fresh", warn=warnings.append)
    assert _head(clone) == "feat/fresh"
    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "feat/fresh@{upstream}"],
        cwd=clone, capture_output=True)
    assert upstream.returncode != 0    # --no-track: no upstream set
    assert any("behind" in w for w in warnings)


def test_branch_mode_refuses_tracked_changes(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    (repo / "seed").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(StartWorkError, match="tracked changes"):
        start_work(repo_root=repo, branch="feat/x-one")


def test_branch_mode_untracked_only_warns_not_refuses(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    (repo / "scratch.env").write_text("x\n", encoding="utf-8")
    warnings: list[str] = []
    start_work(repo_root=repo, branch="feat/x-one", warn=warnings.append)
    assert _head(repo) == "feat/x-one"
    assert any("scratch.env" in w for w in warnings)


def test_branch_mode_refuses_when_already_on_work_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo)
    start_work(repo_root=repo, branch="feat/x-one")
    with pytest.raises(StartWorkError, match="already on work branch"):
        start_work(repo_root=repo, branch="feat/x-two")


def test_branch_mode_refuses_existing_branch(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    subprocess.check_call(["git", "branch", "feat/x-one"], cwd=repo)
    _cfg_branch_mode(repo)
    with pytest.raises(StartWorkError, match="already exists"):
        start_work(repo_root=repo, branch="feat/x-one")


def test_protected_slug_message_is_mode_appropriate(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(repo)
    _cfg_branch_mode(repo, "long_lived: [dev]\n")
    with pytest.raises(StartWorkError) as e:
        start_work(repo_root=repo, branch="feat/dev")
    assert ".worktrees" not in str(e.value)     # no false worktree claim
    assert "protected branch" in str(e.value)
