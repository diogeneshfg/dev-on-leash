"""leash-session-new: create a sibling worktree for a blocked session.

Called by the /leash-session-new skill. Reads this session's lockfile
(by os.getppid()), creates `../<repo>--session-<id>/` on a fresh
`session/<id>` branch from HEAD, and flips the lockfile to
`in-worktree`. Idempotent.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from scripts.harness import session_lockfile as sl


class SessionNewError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorktreeInfo:
    worktree_path: Path
    worktree_branch: str


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_id() -> str:
    return uuid.uuid4().hex[:6]


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SessionNewError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def create_worktree(*, repo_root: Path, self_pid: int) -> WorktreeInfo:
    sessions_dir = repo_root / ".harness" / "sessions"
    lf_path = sessions_dir / f"{self_pid}.json"
    if not lf_path.exists():
        raise SessionNewError(
            f"no session lockfile at {lf_path}; was SessionStart hook installed?"
        )
    lf = sl.read_lockfile(lf_path)

    if lf.state == sl.STATE_IN_WORKTREE and lf.worktree_path and lf.worktree_branch:
        wt = Path(lf.worktree_path)
        if wt.exists():
            return WorktreeInfo(worktree_path=wt, worktree_branch=lf.worktree_branch)

    if lf.state == sl.STATE_PRIMARY:
        raise SessionNewError(
            "session is `primary`; no worktree needed. /leash-session-new is a no-op."
        )

    sid = _short_id()
    branch = f"session/{sid}"
    worktree_path = repo_root.parent / f"{repo_root.name}--session-{sid}"

    if worktree_path.exists():
        raise SessionNewError(
            f"worktree path already exists: {worktree_path}. "
            "Pick a different id or remove the stale directory."
        )

    _git(
        ["worktree", "add", str(worktree_path), "-b", branch, "HEAD"],
        cwd=repo_root,
    )

    updated = sl.Lockfile(
        schema=lf.schema,
        pid=lf.pid,
        started_at=lf.started_at,
        session_id=lf.session_id,
        primary_cwd=lf.primary_cwd,
        state=sl.STATE_IN_WORKTREE,
        worktree_path=str(worktree_path),
        worktree_branch=branch,
    )
    sl.write_lockfile(lf_path, updated)
    return WorktreeInfo(worktree_path=worktree_path, worktree_branch=branch)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--repo-root", type=Path, default=Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()),
    )
    p.add_argument("--self-pid", type=int, default=os.getppid())
    args = p.parse_args(argv[1:])
    try:
        info = create_worktree(repo_root=args.repo_root.resolve(), self_pid=args.self_pid)
    except SessionNewError as exc:
        sys.stderr.write(f"leash-session-new: {exc}\n")
        return 1
    print(f"Worktree created at: {info.worktree_path}")
    print(f"Branch: {info.worktree_branch}")
    print(
        "From now on, use ABSOLUTE paths under that directory for all Edit, "
        "Write, MultiEdit, and file Read operations. Your session cwd has "
        "not moved; this is intentional. When you finish, invoke "
        "/leash-session-end to remove the worktree and the lockfile."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
