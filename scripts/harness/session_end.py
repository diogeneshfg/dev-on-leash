"""leash-session-end: remove this session's worktree + lockfile."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from scripts.harness import session_lockfile as sl


class SessionEndError(RuntimeError):
    pass


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SessionEndError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def _worktree_dirty(worktree: Path) -> bool:
    out = _git(["status", "--porcelain"], cwd=worktree)
    return bool(out.strip())


def _branch_is_merged(repo: Path, branch: str) -> bool:
    out = _git(["branch", "--merged"], cwd=repo)
    # Strip both `*` (current branch) and `+` (branch checked out in a
    # linked worktree) markers. See T07 for the same rationale.
    merged = {b.strip().lstrip("*+ ").strip() for b in out.splitlines()}
    return branch in merged


def end_session(
    *,
    repo_root: Path,
    self_pid: int,
    keep_branch: bool,
) -> None:
    lf_path = repo_root / ".harness" / "sessions" / f"{self_pid}.json"
    if not lf_path.exists():
        raise SessionEndError(f"no lockfile at {lf_path}")
    lf = sl.read_lockfile(lf_path)
    if lf.state != sl.STATE_IN_WORKTREE:
        raise SessionEndError(
            f"session state is {lf.state!r}; expected `in-worktree`"
        )
    if not lf.worktree_path or not lf.worktree_branch:
        raise SessionEndError("lockfile has no worktree_path / worktree_branch")
    wt = Path(lf.worktree_path)
    if not wt.exists():
        try:
            _git(["worktree", "prune"], cwd=repo_root)
        except SessionEndError:
            pass
        lf_path.unlink(missing_ok=True)
        return

    if _worktree_dirty(wt):
        raise SessionEndError(
            f"worktree {wt} has uncommitted changes; commit or stash first"
        )

    if not keep_branch:
        if not _branch_is_merged(repo_root, lf.worktree_branch):
            raise SessionEndError(
                f"branch {lf.worktree_branch} is unmerged; "
                "merge it first or pass --keep-branch"
            )

    _git(["worktree", "remove", str(wt)], cwd=repo_root)
    if not keep_branch:
        _git(["branch", "-d", lf.worktree_branch], cwd=repo_root)
    lf_path.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--repo-root", type=Path,
        default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    p.add_argument("--self-pid", type=int, default=os.getppid())
    p.add_argument("--keep-branch", action="store_true")
    args = p.parse_args(argv[1:])
    try:
        end_session(
            repo_root=args.repo_root.resolve(),
            self_pid=args.self_pid,
            keep_branch=args.keep_branch,
        )
    except SessionEndError as exc:
        sys.stderr.write(f"leash-session-end: {exc}\n")
        return 1
    print("Session ended; worktree removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
