"""Stateless worktree-gate tests."""
from __future__ import annotations

from pathlib import Path

from scripts.harness.session_gate import (
    Decision, decide, list_worktrees, GATED_TOOLS,
)


def _mk(tmp_path: Path) -> tuple[Path, Path]:
    """Return (marker_path, log_path) under a fresh .harness."""
    harness = tmp_path / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    return harness / "allow-main-write", harness / "exceptions.log"


def test_non_gated_tool_allows(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Bash", tool_input={"command": "ls"},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_main_tree_write_denied(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(main_wt / "README.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is False
    assert "/leash-start-work" in d.reason


def test_linked_worktree_write_allowed(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    linked = tmp_path / "repo--wt"
    main_wt.mkdir()
    linked.mkdir()
    d = decide(
        tool_name="Write",
        tool_input={"file_path": str(linked / "x.py")},
        worktrees=[main_wt, linked], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_nested_worktree_beats_main_prefix(tmp_path: Path):
    """`.worktrees/<slug>` lives inside the repo; longest-prefix match
    must classify a target there as the *linked* worktree, not main."""
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    nested = main_wt / ".worktrees" / "feat-x"
    nested.mkdir(parents=True)
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(nested / "x.py")},
        worktrees=[main_wt, nested], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_outside_repo_allows(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(tmp_path / "elsewhere" / "x.py")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_sibling_prefix_attack_denied(tmp_path: Path):
    """A sibling whose name starts with the main name is still outside
    every linked worktree, so it falls back to... outside the repo →
    allow. The real regression we guard: a target literally inside main
    must not be mis-allowed by a startswith bug. Use a nested case."""
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    linked = main_wt / ".worktrees" / "abc"
    evil = main_wt / ".worktrees" / "abcEVIL"
    linked.mkdir(parents=True)
    evil.mkdir(parents=True)
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(evil / "bad.py")},
        worktrees=[main_wt, linked], marker_path=marker, log_path=log,
    )
    # abcEVIL is not inside `abc`; longest match is main → deny.
    assert d.allow is False
    assert "/leash-start-work" in d.reason


def test_one_shot_marker_allows_consumes_and_logs(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    marker.write_text('{"schema":1,"reason":"typo"}', encoding="utf-8")
    d = decide(
        tool_name="Edit",
        tool_input={"file_path": str(main_wt / "README.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log, gate_pid=42,
    )
    assert d.allow is True
    assert not marker.exists(), "marker must be consumed"
    assert log.exists() and "main-write" in log.read_text(encoding="utf-8")


def test_second_main_write_after_consume_denied(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    marker.write_text("{}", encoding="utf-8")
    first = decide(
        tool_name="Edit", tool_input={"file_path": str(main_wt / "a.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    second = decide(
        tool_name="Edit", tool_input={"file_path": str(main_wt / "b.md")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert first.allow is True
    assert second.allow is False


def test_fail_open_when_no_worktrees(tmp_path: Path):
    marker, log = _mk(tmp_path)
    d = decide(
        tool_name="Edit", tool_input={"file_path": str(tmp_path / "x.py")},
        worktrees=None, marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_notebook_edit_is_gated(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="NotebookEdit",
        tool_input={"notebook_path": str(main_wt / "n.ipynb")},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is False


def test_no_target_allows(tmp_path: Path):
    marker, log = _mk(tmp_path)
    main_wt = tmp_path / "repo"
    main_wt.mkdir()
    d = decide(
        tool_name="Edit", tool_input={},
        worktrees=[main_wt], marker_path=marker, log_path=log,
    )
    assert d.allow is True


def test_list_worktrees_on_real_repo(tmp_path: Path):
    import subprocess
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
