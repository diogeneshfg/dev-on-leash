"""List live session lockfiles in the current repo."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from scripts.harness import session_lockfile as sl


def format_sessions(sessions_dir: Path, *, primary_cwd: str) -> str:
    sl.gc_dead_lockfiles(sessions_dir) if sessions_dir.exists() else None
    live = sl.list_live_lockfiles(sessions_dir, primary_cwd=primary_cwd)
    if not live:
        return "(no live sessions)\n"
    lines = ["pid\tstate\tstarted_at\tworktree"]
    for lf in live:
        lines.append(
            f"{lf.pid}\t{lf.state}\t{lf.started_at}\t{lf.worktree_path or '-'}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    sessions = cwd / ".harness" / "sessions"
    sys.stdout.write(format_sessions(sessions, primary_cwd=str(cwd)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
