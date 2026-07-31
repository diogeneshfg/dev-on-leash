"""Tests for the one-shot main-write authorization marker."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.harness.allow_main_write import main as amw_main, write_marker


def test_write_marker_creates_json(tmp_path: Path):
    harness = tmp_path / ".harness"
    marker = write_marker(harness_dir=harness, reason="quick typo")
    assert marker == harness / "allow-main-write"
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["reason"] == "quick typo"
    assert "created_at" in data


def test_write_marker_makes_dir(tmp_path: Path):
    harness = tmp_path / "nope" / ".harness"
    marker = write_marker(harness_dir=harness, reason="r")
    assert marker.exists()


def _git_amw(repo: Path, *args: str) -> None:
    subprocess.check_call(["git", *args], cwd=repo)


def _init_amw_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git_amw(path, "init", "-q", "-b", "main")
    _git_amw(path, "config", "user.email", "d@d")
    _git_amw(path, "config", "user.name", "d")
    (path / "seed").write_text("seed\n", encoding="utf-8")
    _git_amw(path, "add", ".")
    _git_amw(path, "commit", "-q", "-m", "seed")


def test_marker_lands_in_target_repo(tmp_path: Path, monkeypatch, capsys):
    session = tmp_path / "session-repo"
    target = tmp_path / "target-repo"
    _init_amw_repo(session)
    _init_amw_repo(target)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(session))
    rc = amw_main(["allow_main_write", "why", "--repo-root", str(target)])
    assert rc == 0
    assert (target / ".harness" / "allow-main-write").exists()
    assert not (session / ".harness" / "allow-main-write").exists()
    out = capsys.readouterr().out
    assert "repo: " in out and "mode: " in out     # context echo


def test_invalid_repo_root_refused(tmp_path: Path):
    rc = amw_main(["allow_main_write", "why", "--repo-root", str(tmp_path)])
    assert rc == 1
