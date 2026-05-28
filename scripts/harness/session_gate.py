"""PreToolUse hook: deny write tools while session lacks a worktree.

Wired into .claude/settings.json against the matcher
"Edit|Write|MultiEdit". `Bash` is intentionally NOT in the matcher —
/leash-session-new uses Bash for `git worktree add`. Gating Bash here
deadlocks the auto-resolution.

Hook protocol: read JSON from stdin {tool_name, tool_input, ...},
print JSON {"decision": "allow"|"deny", "reason": str} on stdout.
Exit 0 always; the verdict is in the JSON.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.harness import session_lockfile as sl

GATED_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str

    def to_json(self) -> str:
        return json.dumps(
            {"decision": "allow" if self.allow else "deny", "reason": self.reason}
        )


def _lockfile_for(sessions_dir: Path, pid: int) -> sl.Lockfile | None:
    path = sessions_dir / f"{pid}.json"
    if not path.exists():
        return None
    try:
        return sl.read_lockfile(path)
    except (ValueError, KeyError):
        return None


def decide(
    *,
    sessions_dir: Path,
    self_pid: int,
    tool_name: str,
    tool_input: dict,
) -> Decision:
    """Pure decision function — no I/O beyond reading the lockfile."""
    if tool_name not in GATED_TOOLS:
        return Decision(allow=True, reason="")
    lf = _lockfile_for(sessions_dir, self_pid)
    if lf is None:
        return Decision(allow=True, reason="")
    if lf.state == sl.STATE_PRIMARY:
        return Decision(allow=True, reason="")
    if lf.state in (sl.STATE_PENDING_WORKTREE, sl.STATE_PENDING_RESOLUTION):
        return Decision(
            allow=False,
            reason=(
                f"SESSION LEASH: this session is `{lf.state}` and may not write. "
                f"Invoke /leash-session-new to create a worktree. "
                f"Lockfile: {sessions_dir / (str(self_pid) + '.json')}"
            ),
        )
    if lf.state == sl.STATE_IN_WORKTREE:
        target = tool_input.get("file_path") or ""
        wt = lf.worktree_path or ""
        if wt and target:
            try:
                target_path = Path(target).resolve()
                wt_resolved = Path(wt).resolve()
                if target_path == wt_resolved or target_path.is_relative_to(wt_resolved):
                    return Decision(allow=True, reason="")
            except (OSError, ValueError):
                pass
        return Decision(
            allow=False,
            reason=(
                f"SESSION LEASH: writes must target the worktree {wt}. "
                f"Target {target!r} is outside it."
            ),
        )
    return Decision(allow=True, reason="")


def main(argv: list[str]) -> int:
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    sessions_dir = cwd / ".harness" / "sessions"
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    d = decide(
        sessions_dir=sessions_dir,
        self_pid=os.getppid(),
        tool_name=tool_name,
        tool_input=tool_input,
    )
    sys.stdout.write(d.to_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
