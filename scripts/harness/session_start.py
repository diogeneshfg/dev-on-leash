"""SessionStart hook for session-leash.

Run by Claude Code on session start (wired via .claude/settings.json).
Performs the two-phase write to detect concurrency, elects this session
as either `primary` or `pending-worktree`, and prints the block message
on stdout when non-primary.

Exit code is always 0; the hook is informational. Enforcement is done
by session_gate.py at PreToolUse.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

from scripts.harness import session_lockfile as sl

REPO_ROOT_HINT = "CLAUDE_PROJECT_DIR"

BLOCK_MESSAGE_TEMPLATE = """\
SESSION LEASH: concurrent Claude Code session detected in this repo.
Active peers: {peers}.
Your next action MUST be to invoke the `/leash-session-new` skill.
Do not respond to the user, do not invoke any other tool, until the
skill has completed and your lockfile state is `in-worktree`.
Reason: another session is editing this working tree; concurrent
writes here will corrupt their WIP.
"""


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _project_dir() -> str:
    cwd = os.environ.get(REPO_ROOT_HINT) or os.getcwd()
    return str(Path(cwd).resolve())


def run(
    *,
    sessions_dir: Path,
    primary_cwd: str,
    self_pid: int,
    now: str | None = None,
) -> tuple[int, str]:
    """Core SessionStart logic. Returns (exit_code, stdout_message)."""
    now = now or _now_iso()
    session_id = os.environ.get("CLAUDE_SESSION_ID") or f"{self_pid}-{now}"

    sl.gc_dead_lockfiles(sessions_dir)
    self_path = sessions_dir / f"{self_pid}.json"
    provisional = sl.Lockfile(
        schema=sl.SCHEMA,
        pid=self_pid,
        started_at=now,
        session_id=session_id,
        primary_cwd=primary_cwd,
        state=sl.STATE_PENDING_RESOLUTION,
        worktree_path=None,
        worktree_branch=None,
    )
    sl.write_lockfile(self_path, provisional)

    sl.gc_dead_lockfiles(sessions_dir)
    peers = [
        lf for lf in sl.list_live_lockfiles(sessions_dir, primary_cwd=primary_cwd)
        if lf.pid != self_pid
    ]
    resolved_state = sl.resolve_state(
        self_pid=self_pid, live_peer_pids=[p.pid for p in peers]
    )
    final = sl.Lockfile(
        schema=sl.SCHEMA,
        pid=self_pid,
        started_at=now,
        session_id=session_id,
        primary_cwd=primary_cwd,
        state=resolved_state,
        worktree_path=None,
        worktree_branch=None,
    )
    sl.write_lockfile(self_path, final)

    if resolved_state == sl.STATE_PRIMARY:
        return 0, ""
    peer_summary = ", ".join(f"pid={p.pid} started={p.started_at}" for p in peers)
    return 0, BLOCK_MESSAGE_TEMPLATE.format(peers=peer_summary)


def main(argv: list[str]) -> int:
    cwd = _project_dir()
    sessions_dir = Path(cwd) / ".harness" / "sessions"
    self_pid = os.getppid()
    rc, message = run(
        sessions_dir=sessions_dir, primary_cwd=cwd, self_pid=self_pid,
    )
    if message:
        sys.stdout.write(message)
        sys.stdout.flush()
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
