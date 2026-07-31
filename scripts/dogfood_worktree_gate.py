#!/usr/bin/env python3
"""Dogfood the write gate on throwaway repos (both workflow modes)."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.harness.session_gate import decide  # noqa: E402
from scripts.harness.allow_main_write import write_marker  # noqa: E402


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.check_call(["git", "init", "-q", "-b", "main"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "d@d"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "d"], cwd=path)
    (path / "seed").write_text("seed\n", encoding="utf-8")
    subprocess.check_call(["git", "add", "."], cwd=path)
    subprocess.check_call(["git", "commit", "-q", "-m", "seed"], cwd=path)


def _edit(path: Path):
    return decide(tool_name="Edit", tool_input={"file_path": str(path)})


def main() -> int:
    parent = Path(tempfile.mkdtemp(prefix="dol-wtgate-"))
    repo = parent / "throwaway"
    try:
        _init_repo(repo)
        harness = repo / ".harness"
        harness.mkdir()                      # mark the repo leash-managed
        marker = harness / "allow-main-write"
        log = harness / "exceptions.log"

        d_main = _edit(repo / "README.md")
        assert not d_main.allow, "gate must deny main-tree write"
        assert "/leash-start-work" in d_main.reason

        wt = repo / ".worktrees" / "feat-x"
        subprocess.check_call(
            ["git", "worktree", "add", str(wt), "-b", "feat/x", "main"], cwd=repo)
        d_wt = _edit(wt / "y.py")
        assert d_wt.allow, f"gate must allow inside worktree: {d_wt.reason}"

        write_marker(harness_dir=harness, reason="dogfood")
        d_escape = _edit(repo / "README.md")
        assert d_escape.allow, "one-shot marker must allow"
        assert not marker.exists(), "marker must be consumed"
        assert log.exists() and "main-write" in log.read_text(encoding="utf-8")

        d_again = _edit(repo / "README.md")
        assert not d_again.allow, "second main write must deny after consume"

        # branch mode on a second throwaway repo
        br = parent / "throwaway-branch"
        _init_repo(br)
        (br / ".harness").mkdir()
        (br / ".harness" / "branches.yaml").write_text(
            "workflow: branch\n", encoding="utf-8")
        d_on_main = _edit(br / "seed")
        assert not d_on_main.allow, "branch mode must deny on main"
        subprocess.check_call(
            ["git", "checkout", "-q", "-b", "feat/y", "main"], cwd=br)
        d_on_work = _edit(br / "seed")
        assert d_on_work.allow, f"branch mode must allow on work branch: {d_on_work.reason}"

        print("WORKTREE-GATE DOGFOOD PASS")
        return 0
    except AssertionError as exc:
        print(f"WORKTREE-GATE DOGFOOD FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
